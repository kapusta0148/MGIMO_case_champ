"""Кабинет студента: всё под /api/me относится только к вошедшему пользователю.

В адресах нет идентификатора пользователя: чей это кабинет, сервер определяет по сессии.
Объекты по номеру (заявка, занятие, уведомление) выдаются только после проверки владельца или группы.
"""

from __future__ import annotations

from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from .. import clock
from ..errors import not_found, validation_error
from ..extensions import db
from ..models import Announcement
from ..models.user import ROLE_STUDENT
from ..security.auth import current_user, roles_required
from ..services import dashboard as dashboard_service
from ..services import grades as grades_service
from ..services import notifications as notification_service
from ..services import requests as request_service
from ..services import schedule as schedule_service
from .auth import json_body
from .profile import user_payload

bp = Blueprint("me", __name__, url_prefix="/api/me")
student_only = roles_required(ROLE_STUDENT)


def _parse_day(name: str, default: date) -> date:
    raw = request.args.get(name)
    if not raw:
        return default
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise validation_error({name: "Дата должна быть в формате ГГГГ-ММ-ДД."}) from None


@bp.get("/profile")
@student_only
def profile():
    return jsonify({"user": user_payload(current_user())})


@bp.get("/dashboard")
@student_only
def dashboard():
    return jsonify(dashboard_service.dashboard(current_user()))


@bp.get("/schedule")
@student_only
def schedule():
    """Расписание по дням. Без параметров — текущая неделя с понедельника по воскресенье.

    В воскресенье занятий нет, поэтому по умолчанию показываем уже следующую неделю.
    """
    today = clock.today()
    monday = clock.week_start(today + timedelta(days=1) if today.weekday() == 6 else today)
    start = _parse_day("from", monday)
    end = _parse_day("to", start + timedelta(days=6))
    if end < start:
        raise validation_error({"to": "Конец периода раньше начала."})
    if (end - start).days >= schedule_service.MAX_RANGE_DAYS:
        raise validation_error({"to": f"Период — не больше {schedule_service.MAX_RANGE_DAYS} дней."})
    return jsonify(schedule_service.week_payload(current_user(), start, end))


@bp.get("/lessons/<int:lesson_id>")
@student_only
def lesson(lesson_id: int):
    item = schedule_service.get_group_lesson(current_user().student.group_id, lesson_id)
    return jsonify({"lesson": schedule_service.serialize_lesson(item)})


@bp.get("/grades")
@student_only
def grades():
    return jsonify(grades_service.grades_overview(current_user()))


@bp.get("/deadlines")
@student_only
def deadlines():
    now = clock.now()
    items = dashboard_service.upcoming_deadlines(current_user().student.group_id, now, limit=50)
    return jsonify({"items": [dashboard_service.serialize_deadline(item, now) for item in items]})


@bp.get("/deadlines/<int:deadline_id>")
@student_only
def deadline(deadline_id: int):
    item = dashboard_service.get_group_deadline(current_user().student.group_id, deadline_id)
    if item is None:
        raise not_found("Дедлайн не найден.")
    return jsonify({"deadline": dashboard_service.serialize_deadline(item, clock.now())})


# ── Заявки ────────────────────────────────────────────────────────────────────


@bp.get("/requests")
@student_only
def list_requests():
    items = request_service.list_owned(current_user())
    return jsonify({"items": [request_service.serialize_summary(item) for item in items]})


@bp.post("/requests")
@student_only
def create_request():
    user = current_user()
    item, created = request_service.create_request(
        user, json_body(), client_token=request.headers.get("Idempotency-Key")
    )
    db.session.commit()
    item = request_service.get_owned(user, item.id)
    return jsonify({"request": request_service.serialize_detail(item, user), "created": created}), (
        201 if created else 200
    )


@bp.get("/requests/<int:request_id>")
@student_only
def get_request(request_id: int):
    user = current_user()
    return jsonify(
        {"request": request_service.serialize_detail(request_service.get_owned(user, request_id), user)}
    )


@bp.post("/requests/<int:request_id>/comments")
@student_only
def comment_request(request_id: int):
    user = current_user()
    item = request_service.get_owned(user, request_id)
    request_service.add_student_comment(item, actor=user, comment=json_body().get("comment"))
    db.session.commit()
    return jsonify(
        {"request": request_service.serialize_detail(request_service.get_owned(user, request_id), user)}
    ), 201


# ── Уведомления и объявления ──────────────────────────────────────────────────


@bp.get("/notifications")
@student_only
def list_notifications():
    user = current_user()
    unread_only = request.args.get("unread") in {"1", "true"}
    items = notification_service.list_for_user(user.id, unread_only=unread_only)
    return jsonify(
        {
            "items": notification_service.serialize_many(items),
            "unreadCount": notification_service.unread_count(user.id),
        }
    )


@bp.patch("/notifications/<int:notification_id>/read")
@student_only
def read_notification(notification_id: int):
    user = current_user()
    item = notification_service.mark_read(user.id, notification_id)
    db.session.commit()
    return jsonify(
        {
            "notification": notification_service.serialize_many([item])[0],
            "unreadCount": notification_service.unread_count(user.id),
        }
    )


@bp.post("/notifications/read-all")
@student_only
def read_all_notifications():
    user = current_user()
    changed = notification_service.mark_all_read(user.id)
    db.session.commit()
    return jsonify({"changed": changed, "unreadCount": 0})


@bp.get("/announcements/<int:announcement_id>")
@student_only
def announcement(announcement_id: int):
    user = current_user()
    item = db.session.get(Announcement, announcement_id)
    # Объявление чужого факультета или группы неотличимо от несуществующего.
    if item is None or not notification_service.announcement_visible_to(item, user):
        raise not_found("Объявление не найдено.")
    audience = "Всем студентам"
    if item.group is not None:
        audience = f"Группа {item.group.name}"
    elif item.faculty is not None:
        audience = item.faculty.name
    return jsonify(
        {
            "announcement": {
                "id": item.id,
                "title": item.title,
                "body": item.body,
                "publishedAt": clock.iso(item.published_at),
                "audience": audience,
                "author": item.author.staff.position if item.author and item.author.staff else "Деканат",
            }
        }
    )
