"""Расписание: выборки, единое представление занятия и перенос.

Экран «Сегодня», раздел расписания и уведомления о переносе используют serialize_lesson(),
поэтому всегда показывают одно и то же актуальное состояние занятия.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from .. import clock
from ..errors import not_found, validation_error
from ..extensions import db
from ..models import Course, Lesson, User
from ..models.academics import LESSON_CANCELLED, LESSON_KIND_LABELS, LESSON_MOVED, LESSON_SCHEDULED

# Сетка пар (московское время).
PAIR_SLOTS: list[tuple[int, time, time]] = [
    (1, time(9, 0), time(10, 20)),
    (2, time(10, 30), time(11, 50)),
    (3, time(12, 0), time(13, 20)),
    (4, time(14, 0), time(15, 20)),
    (5, time(15, 30), time(16, 50)),
    (6, time(17, 0), time(18, 20)),
]
MAX_RANGE_DAYS = 42


def pair_number(starts_at: datetime) -> int | None:
    local = clock.to_local(starts_at).time()
    for number, start, _end in PAIR_SLOTS:
        if start == local:
            return number
    return None


def _group_lessons():
    return (
        select(Lesson)
        .join(Lesson.course)
        .options(joinedload(Lesson.course).joinedload(Course.subject), joinedload(Lesson.teacher))
    )


def lessons_between(group_id: int, start: datetime, end: datetime) -> list[Lesson]:
    """Занятия группы, которые по актуальному времени попадают в [start; end)."""
    return list(
        db.session.execute(
            _group_lessons()
            .where(Course.group_id == group_id, Lesson.starts_at >= start, Lesson.starts_at < end)
            .order_by(Lesson.starts_at, Lesson.id)
        ).scalars()
    )


def moved_away_between(group_id: int, start: datetime, end: datetime) -> list[Lesson]:
    """Перенесённые занятия, которые ИЗНАЧАЛЬНО стояли в [start; end).

    Нужны, чтобы показать «окно» на старом месте в расписании.
    """
    return list(
        db.session.execute(
            _group_lessons()
            .where(
                Course.group_id == group_id,
                Lesson.status == LESSON_MOVED,
                Lesson.original_starts_at >= start,
                Lesson.original_starts_at < end,
                Lesson.original_starts_at != Lesson.starts_at,
            )
            .order_by(Lesson.original_starts_at)
        ).scalars()
    )


def changes_between(group_id: int, start: datetime, end: datetime) -> list[Lesson]:
    """Изменённые занятия, затрагивающие период (по новому или по исходному времени)."""
    return list(
        db.session.execute(
            _group_lessons()
            .where(
                Course.group_id == group_id,
                Lesson.status.in_([LESSON_MOVED, LESSON_CANCELLED]),
                or_(
                    (Lesson.starts_at >= start) & (Lesson.starts_at < end),
                    (Lesson.original_starts_at >= start) & (Lesson.original_starts_at < end),
                ),
            )
            .order_by(Lesson.starts_at)
        ).scalars()
    )


def current_and_next(group_id: int, now: datetime) -> tuple[Lesson | None, Lesson | None]:
    """Занятие, которое идёт прямо сейчас, и ближайшее следующее (отменённые пропускаются)."""
    rows = list(
        db.session.execute(
            _group_lessons()
            .where(Course.group_id == group_id, Lesson.ends_at > now, Lesson.status != LESSON_CANCELLED)
            .order_by(Lesson.starts_at, Lesson.id)
            .limit(2)
        ).scalars()
    )
    current = rows[0] if rows and rows[0].starts_at <= now else None
    upcoming = next((row for row in rows if row.starts_at > now), None)
    return current, upcoming


def get_group_lesson(group_id: int, lesson_id: int) -> Lesson:
    """Занятие по идентификатору — только если оно принадлежит группе студента."""
    lesson = db.session.execute(
        _group_lessons().where(Lesson.id == lesson_id, Course.group_id == group_id)
    ).scalar_one_or_none()
    if lesson is None:
        raise not_found("Занятие не найдено.")
    return lesson


def _slot_text(starts_at: datetime, ends_at: datetime, room: str | None) -> str:
    local = clock.to_local(starts_at)
    text = f"{clock.human_date(local.date())}, {clock.human_time(starts_at)}–{clock.human_time(ends_at)}"
    return f"{text}, ауд. {room}" if room else text


def change_payload(lesson: Lesson) -> dict | None:
    if lesson.status == LESSON_SCHEDULED:
        return None
    original_start = lesson.original_starts_at or lesson.starts_at
    original_end = lesson.original_ends_at or lesson.ends_at
    original_room = lesson.original_room or lesson.room
    time_changed = original_start != lesson.starts_at or original_end != lesson.ends_at
    room_changed = original_room != lesson.room
    date_changed = clock.to_local(original_start).date() != clock.to_local(lesson.starts_at).date()
    was = _slot_text(original_start, original_end, original_room)
    if lesson.status == LESSON_CANCELLED:
        kind, summary = "cancelled", f"Отменено: {was}."
    else:
        kind = "moved" if time_changed else "room"
        summary = f"Было: {was}. Стало: {_slot_text(lesson.starts_at, lesson.ends_at, lesson.room)}."
    return {
        "type": kind,
        "originalStartsAt": clock.iso(original_start),
        "originalEndsAt": clock.iso(original_end),
        "originalRoom": original_room,
        "originalDate": clock.to_local(original_start).date().isoformat(),
        "timeChanged": time_changed,
        "roomChanged": room_changed,
        "dateChanged": date_changed,
        "reason": lesson.change_reason,
        "changedAt": clock.iso(lesson.changed_at),
        "summary": summary,
    }


def change_title(lesson: Lesson) -> str:
    subject = lesson.course.subject.name
    change = change_payload(lesson)
    if change is None:
        return f"Занятие пройдёт по расписанию: {subject}"
    return {
        "cancelled": f"Занятие отменено: {subject}",
        "moved": f"Перенос занятия: {subject}",
        "room": f"Смена аудитории: {subject}",
    }[change["type"]]


def change_text(lesson: Lesson) -> str:
    change = change_payload(lesson)
    if change is None:
        return _slot_text(lesson.starts_at, lesson.ends_at, lesson.room) + "."
    text = change["summary"]
    return f"{text} Причина: {lesson.change_reason}" if lesson.change_reason else text


def serialize_lesson(lesson: Lesson) -> dict:
    subject = lesson.course.subject
    teacher = lesson.teacher
    local_start = clock.to_local(lesson.starts_at)
    return {
        "id": lesson.id,
        "courseId": lesson.course_id,
        "subject": {"id": subject.id, "name": subject.name, "shortName": subject.short_name},
        "kind": lesson.kind,
        "kindLabel": LESSON_KIND_LABELS.get(lesson.kind, lesson.kind),
        "teacher": {
            "id": teacher.id,
            "name": teacher.full_name,
            "shortName": teacher.short_name,
            "title": teacher.title,
        },
        "room": lesson.room,
        "date": local_start.date().isoformat(),
        "startsAt": clock.iso(lesson.starts_at),
        "endsAt": clock.iso(lesson.ends_at),
        "pairNumber": pair_number(lesson.starts_at),
        "status": lesson.status,
        "change": change_payload(lesson),
    }


def week_payload(student: User, start: date, end: date) -> dict:
    """Расписание группы студента по дням за период [start; end]."""
    return group_week_payload(student.student.group_id, start, end)


def group_week_payload(group_id: int, start: date, end: date) -> dict:
    """Расписание группы по дням. Одно и то же представление у студента и в кабинете деканата."""
    range_start, range_end = clock.day_bounds(start, end)
    lessons = lessons_between(group_id, range_start, range_end)
    moved_away = moved_away_between(group_id, range_start, range_end)

    days: dict[date, dict] = {}
    cursor = start
    while cursor <= end:
        days[cursor] = {
            "date": cursor.isoformat(),
            "weekday": clock.WEEKDAYS_FULL[cursor.weekday()],
            "weekdayShort": clock.WEEKDAYS_SHORT[cursor.weekday()],
            "isToday": cursor == clock.today(),
            "lessons": [],
            "movedAway": [],
        }
        cursor += timedelta(days=1)

    for lesson in lessons:
        days[clock.to_local(lesson.starts_at).date()]["lessons"].append(serialize_lesson(lesson))
    for lesson in moved_away:
        days[clock.to_local(lesson.original_starts_at).date()]["movedAway"].append(serialize_lesson(lesson))

    changed = [lesson for lesson in lessons if lesson.status != LESSON_SCHEDULED]
    seen = {lesson.id for lesson in changed}
    changed += [lesson for lesson in moved_away if lesson.id not in seen]
    changed.sort(key=lambda item: item.starts_at)
    return {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "today": clock.today().isoformat(),
        "timezone": "Europe/Moscow",
        "days": list(days.values()),
        "changes": [serialize_lesson(lesson) for lesson in changed],
    }


def _ensure_free_slot(lesson: Lesson, starts_at: datetime, ends_at: datetime) -> None:
    clash = db.session.execute(
        select(Lesson.id)
        .join(Lesson.course)
        .where(
            Course.group_id == lesson.course.group_id,
            Lesson.id != lesson.id,
            Lesson.status != LESSON_CANCELLED,
            Lesson.starts_at < ends_at,
            Lesson.ends_at > starts_at,
        )
        .limit(1)
    ).scalar_one_or_none()
    if clash is not None:
        raise validation_error({"startsAt": "В это время у группы уже стоит другое занятие."})


def reschedule_lesson(
    lesson: Lesson,
    *,
    starts_at: datetime,
    ends_at: datetime,
    room: str,
    reason: str | None,
    actor: User | None,
) -> Lesson:
    """Перенести занятие и/или сменить аудиторию.

    Изменение занятия и уведомления студентам группы записываются в одной транзакции
    (фиксирует её вызывающий код), поэтому расписание и уведомление не расходятся.
    """
    from . import notifications  # локальный импорт: модули ссылаются друг на друга

    room = (room or "").strip()
    errors: dict[str, str] = {}
    if not room:
        errors["room"] = "Укажите аудиторию."
    if len(room) > 40:
        errors["room"] = "Слишком длинное название аудитории."
    if ends_at <= starts_at:
        errors["endsAt"] = "Окончание должно быть позже начала."
    if reason and len(reason) > 300:
        errors["reason"] = "Причина — не длиннее 300 символов."
    if errors:
        raise validation_error(errors)
    if starts_at == lesson.starts_at and ends_at == lesson.ends_at and room == lesson.room:
        raise validation_error({"startsAt": "Новые время и аудитория совпадают с текущими."})
    _ensure_free_slot(lesson, starts_at, ends_at)

    # Исходные значения запоминаем один раз — при первом изменении.
    if lesson.original_starts_at is None:
        lesson.original_starts_at = lesson.starts_at
        lesson.original_ends_at = lesson.ends_at
        lesson.original_room = lesson.room
    lesson.starts_at = starts_at
    lesson.ends_at = ends_at
    lesson.room = room
    lesson.change_reason = (reason or "").strip() or None
    lesson.changed_at = clock.now()
    lesson.changed_by_user_id = actor.id if actor else None

    back_to_original = (
        lesson.starts_at == lesson.original_starts_at
        and lesson.ends_at == lesson.original_ends_at
        and lesson.room == lesson.original_room
    )
    if back_to_original:
        lesson.status = LESSON_SCHEDULED
        lesson.original_starts_at = lesson.original_ends_at = lesson.original_room = None
    else:
        lesson.status = LESSON_MOVED
    db.session.flush()
    notifications.notify_lesson_change(lesson)
    return lesson


def cancel_lesson(lesson: Lesson, *, reason: str | None, actor: User | None) -> Lesson:
    from . import notifications

    if lesson.status == LESSON_CANCELLED:
        raise validation_error({"status": "Занятие уже отменено."})
    if lesson.original_starts_at is None:
        lesson.original_starts_at = lesson.starts_at
        lesson.original_ends_at = lesson.ends_at
        lesson.original_room = lesson.room
    lesson.status = LESSON_CANCELLED
    lesson.change_reason = (reason or "").strip()[:300] or None
    lesson.changed_at = clock.now()
    lesson.changed_by_user_id = actor.id if actor else None
    db.session.flush()
    notifications.notify_lesson_change(lesson)
    return lesson


def restore_lesson(lesson: Lesson, *, actor: User | None) -> Lesson:
    """Отменить перенос или отмену: вернуть занятию исходные время и аудиторию."""
    from . import notifications

    if lesson.status == LESSON_SCHEDULED or lesson.original_starts_at is None:
        raise validation_error({"status": "Занятие и так идёт по расписанию."})
    starts_at, ends_at = lesson.original_starts_at, lesson.original_ends_at
    _ensure_free_slot(lesson, starts_at, ends_at)
    lesson.starts_at, lesson.ends_at, lesson.room = starts_at, ends_at, lesson.original_room
    lesson.original_starts_at = lesson.original_ends_at = lesson.original_room = None
    lesson.status = LESSON_SCHEDULED
    lesson.change_reason = None
    lesson.changed_at = clock.now()
    lesson.changed_by_user_id = actor.id if actor else None
    db.session.flush()
    notifications.notify_lesson_change(lesson)
    return lesson
