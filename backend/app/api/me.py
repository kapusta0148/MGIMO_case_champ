"""Кабинет студента: всё под /api/me относится только к вошедшему пользователю.

В адресах нет идентификатора пользователя: чей это кабинет, сервер определяет по сессии.
Объекты по номеру (заявка, занятие, уведомление) выдаются только после проверки владельца или группы.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func, select

from .. import clock
from ..errors import ApiError, not_found, validation_error
from ..extensions import db
from ..models import Announcement, Deadline, PersonalTask
from ..models.user import ROLE_STUDENT
from ..security.auth import current_user, roles_required
from ..services import dashboard as dashboard_service
from ..services import grades as grades_service
from ..services import notifications as notification_service
from ..services import planner as planner_service
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


# ── Планировщик и личные задачи ───────────────────────────────────────────────

TASK_LIMIT = 100


def _task_payload(task: PersonalTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "dueAt": clock.iso(task.due_at),
        "plannedStart": clock.iso(task.planned_start),
        "plannedEnd": clock.iso(task.planned_end),
        "estimatedMinutes": task.estimated_minutes,
        "deadlineId": task.deadline_id,
        "fromPlanner": task.source_key is not None,
        "completed": task.completed_at is not None,
        "completedAt": clock.iso(task.completed_at),
        "createdAt": clock.iso(task.created_at),
    }


def _own_task(user_id: int, task_id: int) -> PersonalTask:
    task = db.session.execute(
        select(PersonalTask).where(PersonalTask.id == task_id, PersonalTask.owner_user_id == user_id)
    ).scalar_one_or_none()
    if task is None:
        raise not_found("Задача не найдена.")
    return task


def _parse_moment(raw: object, field: str, errors: dict) -> datetime | None:
    if raw in (None, ""):
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        errors[field] = "Дата и время в формате ГГГГ-ММ-ДДTЧЧ:ММ."
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=clock.MSK)  # время из формы — московское
    if abs(value - clock.now()) > timedelta(days=366):
        errors[field] = "Дата слишком далеко от сегодняшней."
    return value


@bp.get("/planner")
@student_only
def planner():
    return jsonify(planner_service.build_plan(current_user()))


@bp.get("/tasks")
@student_only
def list_tasks():
    user = current_user()
    tasks = db.session.execute(
        select(PersonalTask)
        .where(PersonalTask.owner_user_id == user.id)
        .order_by(
            PersonalTask.completed_at.is_not(None),
            func.coalesce(PersonalTask.planned_start, PersonalTask.due_at).asc().nulls_last(),
            PersonalTask.id,
        )
    ).scalars()
    return jsonify({"items": [_task_payload(t) for t in tasks]})


@bp.post("/tasks")
@student_only
def create_task():
    """Своя задача или принятый блок планировщика (sourceKey). Повторное добавление блока не создаёт дубль."""
    user = current_user()
    data = json_body()
    errors: dict[str, str] = {}
    title = request_service.clean_text(data.get("title"), 160)
    if len(title) < 2:
        errors["title"] = "Опишите задачу (от 2 символов)."
    elif len(title) > 160:
        errors["title"] = "Не длиннее 160 символов."
    due_at = _parse_moment(data.get("dueAt"), "dueAt", errors)
    start = _parse_moment(data.get("plannedStart"), "plannedStart", errors)
    end = _parse_moment(data.get("plannedEnd"), "plannedEnd", errors)
    if (start is None) != (end is None) or (start and end and end <= start):
        errors["plannedEnd"] = "Укажите начало и конец, конец позже начала."
    estimate = data.get("estimatedMinutes")
    if estimate not in (None, ""):
        if isinstance(estimate, bool) or not isinstance(estimate, int) or not 5 <= estimate <= 600:
            errors["estimatedMinutes"] = "Оценка времени — от 5 до 600 минут."
    else:
        estimate = None
    deadline_id = data.get("deadlineId")
    if deadline_id is not None:
        deadline = db.session.get(Deadline, deadline_id) if isinstance(deadline_id, int) else None
        if deadline is None or deadline.group_id != user.student.group_id:
            errors["deadlineId"] = "Дедлайн не найден."
    source_key = data.get("sourceKey")
    if source_key is not None and (not isinstance(source_key, str) or not 3 <= len(source_key) <= 80):
        errors["sourceKey"] = "Некорректный ключ предложения."
    if errors:
        raise validation_error(errors)

    if source_key:
        existing = db.session.execute(
            select(PersonalTask).where(
                PersonalTask.owner_user_id == user.id, PersonalTask.source_key == source_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            return jsonify({"task": _task_payload(existing), "created": False})
    count = db.session.execute(
        select(func.count()).select_from(PersonalTask).where(PersonalTask.owner_user_id == user.id)
    ).scalar_one()
    if count >= TASK_LIMIT:
        raise ApiError(409, "too_many_tasks", f"Не больше {TASK_LIMIT} задач. Удалите выполненные.")

    if start and end and estimate is None:
        estimate = int((end - start).total_seconds() // 60)
    task = PersonalTask(
        owner_user_id=user.id,
        title=title,
        due_at=due_at,
        planned_start=start,
        planned_end=end,
        estimated_minutes=estimate,
        deadline_id=deadline_id,
        source_key=source_key,
        created_at=clock.now(),
    )
    db.session.add(task)
    db.session.commit()
    return jsonify({"task": _task_payload(task), "created": True}), 201


@bp.patch("/tasks/<int:task_id>")
@student_only
def update_task(task_id: int):
    user = current_user()
    task = _own_task(user.id, task_id)
    completed = json_body().get("completed")
    if not isinstance(completed, bool):
        raise validation_error({"completed": "Ожидается true или false."})
    task.completed_at = clock.now() if completed else None
    db.session.commit()
    return jsonify({"task": _task_payload(task)})


@bp.delete("/tasks/<int:task_id>")
@student_only
def delete_task(task_id: int):
    user = current_user()
    db.session.delete(_own_task(user.id, task_id))
    db.session.commit()
    return jsonify({"ok": True})
