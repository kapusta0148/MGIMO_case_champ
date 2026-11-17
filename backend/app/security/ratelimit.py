"""Ограничение частоты на базе Postgres.

Счётчики лежат в таблице, поэтому работают одинаково при нескольких процессах Gunicorn
и переживают перезапуск. Для нагрузки конкурсного прототипа этого достаточно без Redis.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select

from .. import clock
from ..errors import ApiError
from ..extensions import db
from ..models import RateLimitEvent


def count_recent(scope: str, key: str, window: timedelta) -> int:
    since = clock.now() - window
    return db.session.execute(
        select(func.count())
        .select_from(RateLimitEvent)
        .where(RateLimitEvent.scope == scope, RateLimitEvent.key == key, RateLimitEvent.created_at >= since)
    ).scalar_one()


def record(scope: str, key: str) -> None:
    db.session.add(RateLimitEvent(scope=scope, key=key[:120]))


def clear(scope: str, key: str) -> None:
    db.session.execute(delete(RateLimitEvent).where(RateLimitEvent.scope == scope, RateLimitEvent.key == key))


def ensure_below(scope: str, key: str, limit: int, window: timedelta, message: str) -> None:
    if count_recent(scope, key, window) >= limit:
        raise ApiError(
            429, "rate_limited", message, headers={"Retry-After": str(int(window.total_seconds()))}
        )


def purge_older_than(age: timedelta) -> int:
    result = db.session.execute(delete(RateLimitEvent).where(RateLimitEvent.created_at < clock.now() - age))
    return result.rowcount or 0
