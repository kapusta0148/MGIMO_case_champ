"""Вход, выход, текущий пользователь и CSRF-токен."""

from __future__ import annotations

from flask import Blueprint, current_app, g, jsonify, request
from flask_wtf.csrf import generate_csrf
from sqlalchemy import select

from ..errors import ApiError, validation_error
from ..extensions import db
from ..models import User
from ..security import auth, ratelimit
from .profile import user_payload

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

SCOPE_ACCOUNT = "login_fail_account"
SCOPE_IP = "login_fail_ip"


def _client_ip() -> str:
    return request.remote_addr or "unknown"


def json_body() -> dict:
    """Тело запроса — только JSON-объект. Иначе 400/415 в общем формате ошибок."""
    if not request.is_json:
        raise ApiError(415, "unsupported_media_type", "Ожидается запрос в формате JSON.")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(400, "bad_request", "Некорректное тело запроса.")
    return data


@bp.get("/csrf")
def csrf_token():
    """Токен для заголовка X-CSRF-Token. Нужен для любого изменяющего запроса, включая вход."""
    return jsonify({"csrfToken": generate_csrf()})


@bp.post("/login")
def login():
    data = json_body()
    username = data.get("username")
    password = data.get("password")
    errors = {}
    if not isinstance(username, str) or not username.strip():
        errors["username"] = "Введите логин."
    if not isinstance(password, str) or not password:
        errors["password"] = "Введите пароль."  # noqa: S105 (текст ошибки, не пароль)
    if errors:
        raise validation_error(errors)
    username = username.strip().lower()[:40]
    if len(password) > 200:
        raise validation_error({"password": "Слишком длинный пароль."})

    cfg = current_app.config
    window = cfg["LOGIN_FAILURE_WINDOW"]
    ip = _client_ip()
    account_key = f"{ip}|{username}"
    too_many = "Слишком много неудачных попыток входа. Подождите 10 минут и попробуйте снова."
    ratelimit.ensure_below(SCOPE_IP, ip, cfg["LOGIN_MAX_FAILURES_PER_IP"], window, too_many)
    ratelimit.ensure_below(
        SCOPE_ACCOUNT, account_key, cfg["LOGIN_MAX_FAILURES_PER_ACCOUNT"], window, too_many
    )

    user = db.session.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        auth.burn_password_check(password)
        valid = False
    else:
        valid = auth.verify_password(user.password_hash, password) and user.is_active

    if not valid:
        ratelimit.record(SCOPE_IP, ip)
        ratelimit.record(SCOPE_ACCOUNT, account_key)
        db.session.commit()
        # Одинаковый ответ для неверного логина и неверного пароля.
        raise ApiError(401, "invalid_credentials", "Неверный логин или пароль.")

    ratelimit.clear(SCOPE_ACCOUNT, account_key)
    auth.start_session(user)
    db.session.commit()
    return jsonify({"user": user_payload(user), "csrfToken": generate_csrf()})


@bp.post("/logout")
def logout():
    """Выход отзывает серверную сессию: прежняя cookie больше не даёт доступа."""
    auth.end_session()
    return jsonify({"ok": True, "csrfToken": generate_csrf()})


@bp.get("/me")
def me():
    user = g.get("current_user")
    if user is None:
        raise ApiError(401, "unauthorized", "Войдите в кабинет, чтобы продолжить.")
    return jsonify({"user": user_payload(user)})
