"""Пароли, серверные сессии и проверки доступа.

Личность пользователя определяется только здесь: по идентификатору сессии из подписанной cookie.
Никакие user_id из тела запроса или адреса не используются как источник полномочий.
"""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from datetime import timedelta
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import Flask, current_app, g, session
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .. import clock
from ..errors import forbidden, unauthorized
from ..extensions import db
from ..models import AuthSession, User

SESSION_KEY = "sid"
_LAST_SEEN_STEP = timedelta(minutes=5)


def _hasher() -> PasswordHasher:
    cfg = current_app.config
    return PasswordHasher(
        time_cost=cfg["ARGON2_TIME_COST"],
        memory_cost=cfg["ARGON2_MEMORY_KIB"],
        parallelism=cfg["ARGON2_PARALLELISM"],
    )


def hash_password(password: str) -> str:
    """Argon2id с солью; в базе хранится только хеш."""
    return _hasher().hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher().verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def burn_password_check(password: str) -> None:
    """Тратим столько же времени, сколько на настоящую проверку, если логина не существует.

    Иначе по времени ответа можно было бы понять, какие логины зарегистрированы.
    """
    dummy = current_app.extensions.get("campus_dummy_hash")
    if dummy is None:
        dummy = hash_password(secrets.token_urlsafe(16))
        current_app.extensions["campus_dummy_hash"] = dummy
    verify_password(dummy, password)


def _sid_hash(sid: str) -> str:
    return hashlib.sha256(sid.encode("utf-8")).hexdigest()


def start_session(user: User) -> AuthSession:
    """Создать новую сессию после успешного входа. Старое содержимое cookie сбрасывается."""
    session.clear()
    g.pop("csrf_token", None)
    sid = secrets.token_urlsafe(32)
    record = AuthSession(
        sid_hash=_sid_hash(sid),
        user_id=user.id,
        expires_at=clock.now() + current_app.config["PERMANENT_SESSION_LIFETIME"],
    )
    db.session.add(record)
    user.last_login_at = clock.now()
    session[SESSION_KEY] = sid
    session.permanent = True
    g.current_user = user
    g.auth_session = record
    return record


def end_session() -> None:
    """Выход: отзываем серверную запись и очищаем cookie."""
    record: AuthSession | None = g.get("auth_session")
    if record is not None and record.revoked_at is None:
        record.revoked_at = clock.now()
        db.session.commit()
    session.clear()
    g.pop("csrf_token", None)
    g.current_user = None
    g.auth_session = None


def load_current_user() -> None:
    """Выполняется перед каждым запросом: находит действующую сессию и её пользователя."""
    g.current_user = None
    g.auth_session = None
    sid = session.get(SESSION_KEY)
    if not sid or not isinstance(sid, str):
        return
    record = db.session.execute(
        select(AuthSession)
        .options(joinedload(AuthSession.user))
        .where(AuthSession.sid_hash == _sid_hash(sid))
    ).scalar_one_or_none()
    now = clock.now()
    if (
        record is None
        or record.revoked_at is not None
        or record.expires_at <= now
        or not record.user.is_active
    ):
        session.pop(SESSION_KEY, None)
        return
    if now - record.last_seen_at > _LAST_SEEN_STEP:
        record.last_seen_at = now
        db.session.commit()
    g.current_user = record.user
    g.auth_session = record


def current_user() -> User:
    user = g.get("current_user")
    if user is None:
        raise unauthorized()
    return user


def login_required(view: Callable) -> Callable:
    @wraps(view)
    def wrapper(*args, **kwargs):
        current_user()
        return view(*args, **kwargs)

    return wrapper


def roles_required(*roles: str) -> Callable:
    """401 — если не вошёл, 403 — если роль не подходит."""

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args, **kwargs):
            if current_user().role not in roles:
                raise forbidden()
            return view(*args, **kwargs)

        return wrapper

    return decorator


def init_app(app: Flask) -> None:
    app.before_request(load_current_user)
