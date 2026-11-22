"""Администратор демо-стенда: список демо-аккаунтов, включение/отключение, журнал действий.

Пароли не показываются и не меняются через интерфейс: их выдаёт команда при развёртывании.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

from .. import clock
from ..errors import ApiError, not_found, validation_error
from ..extensions import db
from ..models import AuthSession, User
from ..models.user import ROLE_ADMIN, ROLE_LABELS
from ..security.auth import current_user, roles_required
from ..services import audit
from .auth import json_body

bp = Blueprint("admin", __name__, url_prefix="/api/admin")
admin_only = roles_required(ROLE_ADMIN)


def _user_payload(user: User) -> dict:
    detail = None
    if user.student:
        detail = f"{user.student.group.name}, {user.student.group.program.faculty.code}"
    elif user.staff:
        detail = user.staff.position
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "roleLabel": ROLE_LABELS[user.role],
        "fullName": user.full_name,
        "detail": detail,
        "isActive": user.is_active,
        "isGenerated": user.is_generated,
        "createdAt": clock.iso(user.created_at),
        "lastLoginAt": clock.iso(user.last_login_at),
    }


@bp.get("/users")
@admin_only
def users():
    rows = db.session.execute(
        select(User)
        .options(joinedload(User.student), joinedload(User.staff))
        .order_by(User.role, User.username)
    ).scalars()
    return jsonify({"items": [_user_payload(u) for u in rows.unique()]})


@bp.patch("/users/<int:user_id>")
@admin_only
def set_active(user_id: int):
    admin = current_user()
    target = db.session.get(User, user_id)
    if target is None:
        raise not_found("Пользователь не найден.")
    value = json_body().get("isActive")
    if not isinstance(value, bool):
        raise validation_error({"isActive": "Ожидается true или false."})
    if target.id == admin.id:
        raise ApiError(409, "self_change", "Нельзя отключить собственный аккаунт.")
    if target.is_active != value:
        target.is_active = value
        if not value:
            # Отключённый пользователь сразу теряет все открытые сессии.
            db.session.execute(
                update(AuthSession)
                .where(AuthSession.user_id == target.id, AuthSession.revoked_at.is_(None))
                .values(revoked_at=clock.now())
            )
        audit.record(
            admin,
            "user.activate" if value else "user.deactivate",
            "user",
            target.id,
            before={"isActive": not value},
            after={"isActive": value, "username": target.username},
        )
        db.session.commit()
    return jsonify({"user": _user_payload(target)})


@bp.get("/audit")
@admin_only
def audit_log():
    try:
        limit = max(1, min(200, int(request.args.get("limit", 100))))
    except ValueError:
        limit = 100
    return jsonify({"items": audit.recent(limit)})
