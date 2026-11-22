"""Планировщик учёбы: объяснимый алгоритм без языковой модели.

1. Свободные окна на 7 дней: с 09:00 до 21:00 минус занятия группы (+10 минут на дорогу)
   и минус уже запланированные личные задачи.
2. Что нужно сделать: дедлайны группы и личные задачи с оценкой времени; из оценки вычитается
   уже запланированное или выполненное по этому дедлайну.
3. Раскладка «ближайший срок — первым» (EDF); при равных сроках первыми идут дисциплины
   из зоны внимания. Блоки по 45–120 минут, каждый заканчивается не позже чем за час до срока.
4. Предупреждения: не хватает свободного времени до срока, два и больше дедлайна в один день,
   дисциплины в зоне внимания.

Алгоритм только предлагает. В личные задачи блок попадает по явному действию студента.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .. import clock
from ..extensions import db
from ..models import Course, Deadline, PersonalTask, User
from ..models.academics import LESSON_CANCELLED
from . import grades as grades_service
from . import schedule as schedule_service
from .dashboard import DEADLINE_KIND_LABELS

HORIZON_DAYS = 7
DAY_START = time(9, 0)
DAY_END = time(21, 0)
TRAVEL = timedelta(minutes=10)
MIN_BLOCK = 45
MAX_BLOCK = 120
SAFETY = timedelta(hours=1)
BREAK = timedelta(minutes=15)

# Оценка времени на подготовку по виду задания (минуты). Показывается студенту как допущение.
ESTIMATES = {"essay": 180, "project": 240, "report": 150, "homework": 90, "test": 120, "document": 30}

RULES = [
    "Свободное время — с 09:00 до 21:00, кроме пар группы и 10 минут после каждой пары на дорогу.",
    "Сначала то, у чего ближе срок; при равных сроках — дисциплины из зоны внимания.",
    "Блок работы — от 45 до 120 минут и заканчивается минимум за час до срока.",
    "Время на задание оценено по его виду: эссе 3 ч, проект 4 ч, доклад 2,5 ч, домашнее 1,5 ч, "
    "подготовка к контрольной 2 ч, документы 30 мин.",
    "Это алгоритм, а не прогноз: ничего не попадает в ваши задачи без нажатия «Добавить».",
]


@dataclass
class Window:
    start: datetime
    end: datetime

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


@dataclass
class Need:
    key: str
    title: str
    kind_label: str
    subject: str | None
    due_at: datetime
    minutes: int
    estimate: int
    at_risk: bool
    deadline_id: int | None
    task_id: int | None
    blocks: list[tuple[datetime, datetime]] = field(default_factory=list)


def _subtract(windows: list[Window], busy_start: datetime, busy_end: datetime) -> list[Window]:
    result = []
    for w in windows:
        if busy_end <= w.start or busy_start >= w.end:
            result.append(w)
            continue
        if busy_start > w.start:
            result.append(Window(w.start, busy_start))
        if busy_end < w.end:
            result.append(Window(busy_end, w.end))
    return result


def _ceil_quarter(moment: datetime) -> datetime:
    """Округлить вверх до четверти часа: блок «с 16:45», а не «с 16:34»."""
    local = clock.to_local(moment).replace(second=0, microsecond=0)
    extra = (-local.minute) % 15
    return local + timedelta(minutes=extra) if extra or moment.second or moment.microsecond else local


def free_windows(student: User, now: datetime, tasks: list[PersonalTask]) -> dict[date, list[Window]]:
    group_id = student.student.group_id
    today = clock.to_local(now).date()
    first, last = clock.day_bounds(today, today + timedelta(days=HORIZON_DAYS - 1))
    lessons = [
        lesson
        for lesson in schedule_service.lessons_between(group_id, first, last)
        if lesson.status != LESSON_CANCELLED
    ]
    days: dict[date, list[Window]] = {}
    for offset in range(HORIZON_DAYS):
        day = today + timedelta(days=offset)
        start = max(clock.local_dt(day, DAY_START), _ceil_quarter(now))
        end = clock.local_dt(day, DAY_END)
        windows = [Window(start, end)] if end > start else []
        for lesson in lessons:
            if clock.to_local(lesson.starts_at).date() == day:
                windows = _subtract(windows, lesson.starts_at, lesson.ends_at + TRAVEL)
        for task in tasks:
            if task.planned_start and task.completed_at is None:
                windows = _subtract(windows, task.planned_start, task.planned_end)
        days[day] = [w for w in windows if w.minutes >= MIN_BLOCK]
    return days


def _needs(student: User, now: datetime, tasks: list[PersonalTask], at_risk: set[str]) -> list[Need]:
    horizon_end = now + timedelta(days=HORIZON_DAYS + 7)
    deadlines = db.session.execute(
        select(Deadline)
        .where(
            Deadline.group_id == student.student.group_id,
            Deadline.due_at > now,
            Deadline.due_at <= horizon_end,
        )
        .options(joinedload(Deadline.course).joinedload(Course.subject))
        .order_by(Deadline.due_at, Deadline.id)
    ).scalars()

    covered: dict[int, int] = {}
    for task in tasks:
        if task.deadline_id is None:
            continue
        if task.planned_start and task.planned_end:
            covered[task.deadline_id] = covered.get(task.deadline_id, 0) + int(
                (task.planned_end - task.planned_start).total_seconds() // 60
            )
        elif task.completed_at is not None:
            covered[task.deadline_id] = covered.get(task.deadline_id, 0) + (task.estimated_minutes or 0)

    needs: list[Need] = []
    for item in deadlines:
        estimate = ESTIMATES.get(item.kind, 90)
        remaining = estimate - covered.get(item.id, 0)
        if remaining < 15:
            continue
        subject = item.course.subject.name if item.course else None
        needs.append(
            Need(
                key=f"d{item.id}",
                title=item.title,
                kind_label=DEADLINE_KIND_LABELS.get(item.kind, "Задание"),
                subject=subject,
                due_at=item.due_at,
                minutes=remaining,
                estimate=estimate,
                at_risk=subject in at_risk,
                deadline_id=item.id,
                task_id=None,
            )
        )
    for task in tasks:
        if task.completed_at or task.planned_start or not task.due_at or not task.estimated_minutes:
            continue
        if task.deadline_id is not None or task.due_at <= now:
            continue
        needs.append(
            Need(
                key=f"t{task.id}",
                title=task.title,
                kind_label="Личная задача",
                subject=None,
                due_at=task.due_at,
                minutes=task.estimated_minutes,
                estimate=task.estimated_minutes,
                at_risk=False,
                deadline_id=None,
                task_id=task.id,
            )
        )
    needs.sort(key=lambda n: (n.due_at, not n.at_risk, n.key))
    return needs


def _allocate(needs: list[Need], days: dict[date, list[Window]]) -> list[Need]:
    """Жадная раскладка по окнам в хронологическом порядке. Окна уменьшаются по мере заполнения.

    В одном окне может стоять несколько блоков подряд — с перерывом 15 минут между ними.
    """
    pool = sorted((w for windows in days.values() for w in windows), key=lambda w: w.start)
    unmet = []
    for need in needs:
        left = need.minutes
        limit = need.due_at - SAFETY
        for window in pool:
            while left > 0:
                end_cap = min(window.end, limit)
                available = int((end_cap - window.start).total_seconds() // 60)
                if available < min(MIN_BLOCK, left):
                    break
                take = min(left, MAX_BLOCK, available)
                rest = left - take
                if 0 < rest < MIN_BLOCK:
                    # Не оставлять хвост короче 45 минут: этот блок чуть короче, следующий — 45.
                    take = max(MIN_BLOCK, take - (MIN_BLOCK - rest))
                start = window.start
                end = start + timedelta(minutes=take)
                need.blocks.append((start, end))
                window.start = end + BREAK
                left -= take
            if left <= 0:
                break
        if left > 0:
            unmet.append(need)
        need.minutes = left  # остаток, который не удалось разместить
    return unmet


def _hours(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h} ч {m} мин" if h and m else (f"{h} ч" if h else f"{m} мин")


def _neighbours(lessons: list, start: datetime, end: datetime) -> str:
    """Где блок стоит относительно пар того же дня (по московскому времени)."""
    day = clock.to_local(start).date()
    same_day = [lesson for lesson in lessons if clock.to_local(lesson.starts_at).date() == day]
    before = [lesson for lesson in same_day if lesson.ends_at <= start]
    after = [lesson for lesson in same_day if lesson.starts_at >= end]
    if before and after:
        first, second = before[-1].course.subject.short_name, after[0].course.subject.short_name
        return f"окно между парами «{first}» и «{second}»"
    if before:
        return f"после пары «{before[-1].course.subject.short_name}»"
    if after:
        return f"до пары «{after[0].course.subject.short_name}»"
    return "день без пар"


def build_plan(student: User) -> dict:
    now = clock.now()
    today = clock.to_local(now).date()
    tasks = list(
        db.session.execute(
            select(PersonalTask).where(PersonalTask.owner_user_id == student.id).order_by(PersonalTask.id)
        ).scalars()
    )
    overview = grades_service.grades_overview(student)
    at_risk = set(overview["currentTerm"]["summary"]["atRisk"]) if overview["currentTerm"] else set()

    days = free_windows(student, now, tasks)
    free_by_day = {day: sum(w.minutes for w in windows) for day, windows in days.items()}
    needs = _needs(student, now, tasks, at_risk)
    unmet = _allocate(needs, days)

    first, last = clock.day_bounds(today, today + timedelta(days=HORIZON_DAYS - 1))
    lessons = [
        lesson
        for lesson in schedule_service.lessons_between(student.student.group_id, first, last)
        if lesson.status != LESSON_CANCELLED
    ]

    blocks = []
    for need in needs:
        total = len(need.blocks)
        for index, (start, end) in enumerate(need.blocks, start=1):
            minutes = int((end - start).total_seconds() // 60)
            left_hours = int((need.due_at - start).total_seconds() // 3600)
            due_text = (
                f"{clock.human_date(clock.to_local(need.due_at).date())}, {clock.human_time(need.due_at)}"
            )
            reasons = [
                f"Срок — {due_text}: через {left_hours} ч от начала блока.",
                f"Оценка времени: {_hours(need.estimate)} ({need.kind_label.lower()})"
                + (f", это часть {index} из {total}." if total > 1 else "."),
            ]
            place = _neighbours(lessons, start, end)
            if place:
                reasons.append(f"Место в расписании: {place}.")
            if need.at_risk:
                reasons.append(f"«{need.subject}» в зоне внимания — при равных сроках идёт первой.")
            blocks.append(
                {
                    "key": f"{need.key}-{clock.to_local(start).strftime('%Y%m%d%H%M')}",
                    "title": need.title + (f" — часть {index} из {total}" if total > 1 else ""),
                    "subject": need.subject,
                    "kindLabel": need.kind_label,
                    "date": clock.to_local(start).date().isoformat(),
                    "startsAt": clock.iso(start),
                    "endsAt": clock.iso(end),
                    "minutes": minutes,
                    "dueAt": clock.iso(need.due_at),
                    "deadlineId": need.deadline_id,
                    "taskId": need.task_id,
                    "atRisk": need.at_risk,
                    "reasons": reasons,
                }
            )
    blocks.sort(key=lambda b: b["startsAt"])

    warnings = []
    for need in unmet:
        warnings.append(
            {
                "type": "not_enough_time",
                "text": f"«{need.title}»: до срока не хватает {_hours(need.minutes)} свободного времени. "
                "Начните раньше, освободите вечер или уточните срок у преподавателя.",
            }
        )
    by_day: dict[date, list[Need]] = {}
    for need in needs:
        by_day.setdefault(clock.to_local(need.due_at).date(), []).append(need)
    for day, items in sorted(by_day.items()):
        if len(items) >= 2:
            warnings.append(
                {
                    "type": "same_day",
                    "text": f"{clock.human_date(day).capitalize()}: {len(items)} дедлайна — "
                    + ", ".join(f"«{n.title}»" for n in items)
                    + ". Блоки по ним разнесены на предыдущие дни.",
                }
            )
    for subject in sorted(at_risk):
        warnings.append(
            {
                "type": "at_risk",
                "text": f"«{subject}» в зоне внимания (рейтинг ниже {grades_service.RISK_THRESHOLD}). "
                "Задания по этой дисциплине стоят первыми при равных сроках.",
            }
        )

    planned_by_day: dict[str, int] = {}
    for task in tasks:
        if task.planned_start and task.completed_at is None:
            key = clock.to_local(task.planned_start).date().isoformat()
            planned_by_day[key] = planned_by_day.get(key, 0) + int(
                (task.planned_end - task.planned_start).total_seconds() // 60
            )
    lessons_by_day: dict[str, int] = {}
    for lesson in lessons:
        key = clock.to_local(lesson.starts_at).date().isoformat()
        lessons_by_day[key] = lessons_by_day.get(key, 0) + int(
            (lesson.ends_at - lesson.starts_at).total_seconds() // 60
        )

    return {
        "generatedAt": clock.iso(now),
        "today": today.isoformat(),
        "method": "rules",
        "rules": RULES,
        "blocks": blocks,
        "warnings": warnings,
        "days": [
            {
                "date": day.isoformat(),
                "weekdayShort": clock.WEEKDAYS_SHORT[day.weekday()],
                "lessonsMinutes": lessons_by_day.get(day.isoformat(), 0),
                "plannedMinutes": planned_by_day.get(day.isoformat(), 0),
                "suggestedMinutes": sum(b["minutes"] for b in blocks if b["date"] == day.isoformat()),
                "freeMinutes": free_by_day[day],
            }
            for day in sorted(days)
        ],
    }
