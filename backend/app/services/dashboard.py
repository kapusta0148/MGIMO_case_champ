"""Экран «Сегодня»: собирает главное из тех же сервисов, что питают остальные разделы."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .. import clock
from ..extensions import db
from ..models import Course, Deadline, ServiceRequest, User
from ..models.academics import LESSON_CANCELLED, LESSON_SCHEDULED
from ..models.requests import FINAL_STATUSES
from . import notifications, schedule
from . import requests as request_service

DEADLINE_KIND_LABELS = {
    "essay": "Эссе",
    "homework": "Домашнее задание",
    "test": "Контрольная",
    "project": "Проект",
    "report": "Доклад",
    "document": "Документы",
}
SOON = timedelta(hours=48)


def serialize_deadline(item: Deadline, now: datetime) -> dict:
    subject = item.course.subject if item.course else None
    remaining = item.due_at - now
    return {
        "id": item.id,
        "kind": item.kind,
        "kindLabel": DEADLINE_KIND_LABELS.get(item.kind, "Дедлайн"),
        "title": item.title,
        "description": item.description,
        "subject": {"id": subject.id, "name": subject.name, "shortName": subject.short_name}
        if subject
        else None,
        "dueAt": clock.iso(item.due_at),
        "date": clock.to_local(item.due_at).date().isoformat(),
        "hoursLeft": max(0, int(remaining.total_seconds() // 3600)),
        "isSoon": timedelta(0) <= remaining <= SOON,
        "isOverdue": remaining < timedelta(0),
    }


def upcoming_deadlines(
    group_id: int, now: datetime, *, limit: int | None = None, until: datetime | None = None
):
    query = (
        select(Deadline)
        .where(Deadline.group_id == group_id, Deadline.due_at >= now)
        .options(joinedload(Deadline.course).joinedload(Course.subject))
        .order_by(Deadline.due_at, Deadline.id)
    )
    if until is not None:
        query = query.where(Deadline.due_at < until)
    if limit is not None:
        query = query.limit(limit)
    return list(db.session.execute(query).scalars())


def get_group_deadline(group_id: int, deadline_id: int) -> Deadline | None:
    return db.session.execute(
        select(Deadline)
        .where(Deadline.id == deadline_id, Deadline.group_id == group_id)
        .options(joinedload(Deadline.course).joinedload(Course.subject))
    ).scalar_one_or_none()


def _active_request(student: User) -> ServiceRequest | None:
    """Последняя заявка в работе; если таких нет — самая свежая из закрытых."""
    base = select(ServiceRequest).where(ServiceRequest.owner_user_id == student.id)
    active = db.session.execute(
        base.where(ServiceRequest.status.notin_(FINAL_STATUSES))
        .order_by(ServiceRequest.updated_at.desc(), ServiceRequest.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if active is not None:
        return active
    return db.session.execute(
        base.order_by(ServiceRequest.updated_at.desc(), ServiceRequest.id.desc()).limit(1)
    ).scalar_one_or_none()


def _minutes_until(moment: datetime, now: datetime) -> int:
    return max(0, int((moment - now).total_seconds() // 60))


def dashboard(student: User) -> dict:
    now = clock.now()
    today = clock.today()
    group_id = student.student.group_id
    day_start, day_end = clock.day_bounds(today)

    today_lessons = schedule.lessons_between(group_id, day_start, day_end)
    current, upcoming = schedule.current_and_next(group_id, now)
    # Изменения на неделю вперёд (по новому или исходному времени), начиная с сегодняшнего дня.
    changes = schedule.changes_between(group_id, day_start, day_start + timedelta(days=7))
    changes = [lesson for lesson in changes if lesson.status != LESSON_SCHEDULED]

    deadlines = upcoming_deadlines(group_id, now, limit=3)
    active = _active_request(student)
    latest = notifications.list_for_user(student.id, limit=3, unread_only=True)

    active_today = [lesson for lesson in today_lessons if lesson.status != LESSON_CANCELLED]
    changes_today = [
        lesson
        for lesson in changes
        if clock.to_local(lesson.starts_at).date() == today
        or (lesson.original_starts_at and clock.to_local(lesson.original_starts_at).date() == today)
    ]
    soon = [item for item in deadlines if item.due_at - now <= SOON]

    next_payload = None
    if upcoming is not None:
        next_payload = schedule.serialize_lesson(upcoming)
        next_payload["minutesUntil"] = _minutes_until(upcoming.starts_at, now)
        next_payload["isToday"] = clock.to_local(upcoming.starts_at).date() == today
    current_payload = None
    if current is not None:
        current_payload = schedule.serialize_lesson(current)
        current_payload["minutesLeft"] = _minutes_until(current.ends_at, now)

    return {
        "now": clock.iso(now),
        "today": today.isoformat(),
        "weekday": clock.WEEKDAYS_FULL[today.weekday()],
        "firstName": _first_name(student.student.full_name),
        "summary": {
            "lessonsToday": len(active_today),
            "lessonsLeftToday": len([lesson for lesson in active_today if lesson.ends_at > now]),
            "changesToday": len(changes_today),
            "deadlinesSoon": len(soon),
            "unreadNotifications": notifications.unread_count(student.id),
        },
        "currentLesson": current_payload,
        "nextLesson": next_payload,
        "todayLessons": [schedule.serialize_lesson(lesson) for lesson in today_lessons],
        "changes": [schedule.serialize_lesson(lesson) for lesson in changes],
        "deadlines": [serialize_deadline(item, now) for item in deadlines],
        "activeRequest": request_service.serialize_summary(active)
        | {"steps": request_service.progress_steps(active.status)}
        if active
        else None,
        "notifications": notifications.serialize_many(latest),
    }


def _first_name(full_name: str) -> str:
    """«Северцева Мира Олеговна» -> «Мира»."""
    parts = full_name.split()
    return parts[1] if len(parts) >= 2 else full_name
