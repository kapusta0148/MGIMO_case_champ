"""Поддержание «живого» демо-стенда.

Жюри может открыть прототип в любой день до объявления итогов. Чтобы главный сценарий
(уведомление о переносе -> занятие в расписании) работал каждый день, раз в сутки сервер:
  1) следит, чтобы у каждой группы был свежий перенос ближайшего занятия;
  2) создаёт напоминания о дедлайнах, до которых осталось меньше двух суток;
  3) чистит устаревшие служебные записи.
Перенос делается тем же сервисом, которым пользуется сотрудник деканата.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert

from .. import clock
from ..errors import ApiError
from ..extensions import db
from ..models import AppState, AuthSession, Course, Deadline, Lesson, Notification, StudyGroup
from ..models.academics import LESSON_MOVED, LESSON_SCHEDULED
from ..models.comms import NOTIFY_DEADLINE, SOURCE_DEADLINE
from ..security import ratelimit
from . import notifications, schedule

log = logging.getLogger("campus.demo")

STATE_KEY = "demo_refresh_date"
# Три дня, а не два: в субботу вечером ближайшие пары — в понедельник, и перенос всё равно найдётся.
FRESH_WINDOW = timedelta(days=3)
REMINDER_WINDOW = timedelta(hours=48)

MOVE_REASONS = [
    "Преподаватель участвует в научной конференции.",
    "Аудитория занята под день открытых дверей.",
    "Занятие совмещено с гостевой лекцией.",
    "Технические работы в аудитории.",
]
SPARE_ROOMS = ["4017", "3208", "2314", "1126", "4102"]

_process_date: date | None = None  # дата, на которую этот процесс уже проверял обновление


def _has_fresh_move(group_id: int, day_start: datetime) -> bool:
    return (
        db.session.execute(
            select(Lesson.id)
            .join(Lesson.course)
            .where(
                Course.group_id == group_id,
                Lesson.status == LESSON_MOVED,
                Lesson.starts_at >= day_start,
                Lesson.starts_at < day_start + FRESH_WINDOW,
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _free_later_slot(group_id: int, lesson: Lesson) -> tuple[datetime, datetime] | None:
    """Свободная пара в тот же день позже текущей."""
    day = clock.to_local(lesson.starts_at).date()
    day_start, day_end = clock.day_bounds(day)
    busy = [
        (other.starts_at, other.ends_at)
        for other in schedule.lessons_between(group_id, day_start, day_end)
        if other.id != lesson.id
    ]
    for _number, start, end in schedule.PAIR_SLOTS:
        slot_start, slot_end = clock.local_dt(day, start), clock.local_dt(day, end)
        if slot_start <= lesson.starts_at:
            continue
        if all(slot_end <= b_start or slot_start >= b_end for b_start, b_end in busy):
            return slot_start, slot_end
    return None


def ensure_fresh_move(group: StudyGroup, now: datetime) -> Lesson | None:
    """Если у группы нет свежего переноса — переносим ближайшее подходящее занятие."""
    day_start, _ = clock.day_bounds(clock.to_local(now).date())
    if _has_fresh_move(group.id, day_start):
        return None
    candidates = [
        lesson
        for lesson in schedule.lessons_between(
            group.id, now + timedelta(minutes=60), day_start + FRESH_WINDOW
        )
        if lesson.status == LESSON_SCHEDULED
    ]
    # Семинары и языковые пары переносятся правдоподобнее, чем потоковые лекции.
    candidates.sort(key=lambda item: (item.kind == "lecture", item.starts_at))
    for lesson in candidates:
        slot = _free_later_slot(group.id, lesson)
        starts_at, ends_at = slot if slot else (lesson.starts_at, lesson.ends_at)
        room = next(r for r in SPARE_ROOMS[lesson.id % len(SPARE_ROOMS) :] + SPARE_ROOMS if r != lesson.room)
        try:
            return schedule.reschedule_lesson(
                lesson,
                starts_at=starts_at,
                ends_at=ends_at,
                room=room,
                reason=MOVE_REASONS[lesson.id % len(MOVE_REASONS)],
                actor=None,
            )
        except ApiError:
            continue
    return None


def create_deadline_reminders(now: datetime) -> int:
    created = 0
    soon = db.session.execute(
        select(Deadline).where(Deadline.due_at >= now, Deadline.due_at <= now + REMINDER_WINDOW)
    ).scalars()
    for item in soon:
        local_due = clock.to_local(item.due_at)
        days = (local_due.date() - clock.to_local(now).date()).days
        when = {0: "сегодня", 1: "завтра"}.get(days, clock.human_date(local_due.date()))
        for user_id in notifications.group_student_ids(item.group_id):
            key = f"deadline:{item.id}:soon"
            exists = db.session.execute(
                select(Notification.id).where(
                    Notification.recipient_user_id == user_id, Notification.dedupe_key == key
                )
            ).scalar_one_or_none()
            if exists is not None:
                continue  # напоминание уже было: не «поднимаем» его повторно
            notifications.notify(
                user_id,
                kind=NOTIFY_DEADLINE,
                title=f"Дедлайн {when}: {item.title}",
                body=f"Сдать до {local_due.strftime('%H:%M')}, {clock.human_date(local_due.date())}.",
                source_type=SOURCE_DEADLINE,
                source_id=item.id,
                dedupe_key=key,
            )
            created += 1
    return created


def refresh_demo_state() -> dict:
    """Идемпотентное обновление демо-данных. Фиксацию транзакции выполняет вызывающий код."""
    now = clock.now()
    moved = []
    for group in db.session.execute(select(StudyGroup)).scalars():
        lesson = ensure_fresh_move(group, now)
        if lesson is not None:
            moved.append(lesson.id)
    reminders = create_deadline_reminders(now)
    purged = ratelimit.purge_older_than(timedelta(days=1))
    db.session.execute(delete(AuthSession).where(AuthSession.expires_at < now - timedelta(days=1)))
    _set_state(clock.to_local(now).date())
    return {"movedLessons": moved, "deadlineReminders": reminders, "purgedRateEvents": purged}


def _set_state(day: date) -> None:
    statement = insert(AppState).values(key=STATE_KEY, value=day.isoformat(), updated_at=clock.now())
    db.session.execute(
        statement.on_conflict_do_update(
            index_elements=[AppState.key], set_={"value": day.isoformat(), "updated_at": clock.now()}
        )
    )


def refresh_if_stale() -> bool:
    """Ленивая проверка раз в сутки (вызывается перед запросами вошедших пользователей).

    Блокировка в Postgres гарантирует, что при нескольких процессах обновление выполнит один.
    """
    global _process_date
    today = clock.today()
    if _process_date == today:
        return False
    try:
        db.session.execute(text("select pg_advisory_xact_lock(727001)"))
        state = db.session.get(AppState, STATE_KEY)
        if state is not None and state.value == today.isoformat():
            db.session.rollback()
            _process_date = today
            return False
        result = refresh_demo_state()
        db.session.commit()
        _process_date = today
        log.info("demo refreshed: %s", result)
        return True
    except Exception:
        db.session.rollback()
        log.exception("demo refresh failed")
        return False
