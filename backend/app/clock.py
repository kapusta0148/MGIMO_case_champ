"""Единый источник времени.

В базе всё хранится в UTC, пользователю показывается московское время (Europe/Moscow):
расписание вуза привязано к Москве независимо от часового пояса телефона.
Тесты подменяют «сейчас» через freeze().
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MSK = ZoneInfo("Europe/Moscow")

_frozen: datetime | None = None

WEEKDAYS_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]  # fmt: skip


def freeze(moment: datetime | None) -> None:
    """Зафиксировать «сейчас» (только для тестов и сидов). None снимает фиксацию."""
    global _frozen
    if moment is not None and moment.tzinfo is None:
        raise ValueError("freeze() ожидает время с часовым поясом")
    _frozen = moment


@contextmanager
def frozen(moment: datetime) -> Iterator[None]:
    """Временно считать «сейчас» равным moment (сиды создают события задним числом)."""
    previous = _frozen
    freeze(moment)
    try:
        yield
    finally:
        freeze(previous)


def now() -> datetime:
    return _frozen if _frozen is not None else datetime.now(UTC)


def local_now() -> datetime:
    return now().astimezone(MSK)


def today() -> date:
    return local_now().date()


def to_local(moment: datetime) -> datetime:
    return moment.astimezone(MSK)


def local_dt(day: date, at: time) -> datetime:
    """Московские дата и время -> момент с часовым поясом."""
    return datetime.combine(day, at, tzinfo=MSK)


def day_bounds(start: date, end: date | None = None) -> tuple[datetime, datetime]:
    """Полуинтервал [начало первого дня; начало дня после последнего) в московском времени."""
    last = end or start
    return local_dt(start, time.min), local_dt(last + timedelta(days=1), time.min)


def week_start(day: date) -> date:
    return day - timedelta(days=day.weekday())


def iso(moment: datetime | None) -> str | None:
    """ISO-8601 с московским смещением, например 2026-11-16T10:30:00+03:00."""
    if moment is None:
        return None
    return to_local(moment).isoformat(timespec="seconds")


def human_date(day: date, with_weekday: bool = True) -> str:
    text = f"{day.day} {MONTHS_GENITIVE[day.month - 1]}"
    return f"{WEEKDAYS_SHORT[day.weekday()]}, {text}" if with_weekday else text


def human_time(moment: datetime) -> str:
    return to_local(moment).strftime("%H:%M")
