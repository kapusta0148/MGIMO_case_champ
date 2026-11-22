"""Служебные таблицы: аудит действий сотрудников, счётчики ограничения частоты, состояние демо."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .. import clock
from ..extensions import db


class AuditEvent(db.Model):
    """Кто, что и когда изменил. Пароли, токены и содержимое файлов сюда не пишутся."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(48))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[int | None] = mapped_column()
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    __table_args__ = (Index("ix_audit_events_entity", "entity_type", "entity_id"),)


class RateLimitEvent(db.Model):
    """Отметка о событии для ограничения частоты (неудачный вход, регистрация)."""

    __tablename__ = "rate_limit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    scope: Mapped[str] = mapped_column(String(32))
    key: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    __table_args__ = (Index("ix_rate_limit_events_lookup", "scope", "key", "created_at"),)


class AppState(db.Model):
    """Простое хранилище «ключ — значение» для служебных отметок (например, дата обновления демо)."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(48), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=clock.now, onupdate=clock.now
    )
