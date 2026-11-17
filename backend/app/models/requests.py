"""Заявки студентов, их история и вложения."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import clock
from ..extensions import db
from .user import User

STATUS_SUBMITTED = "submitted"
STATUS_IN_REVIEW = "in_review"
STATUS_NEEDS_INFO = "needs_info"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

REQUEST_STATUS_LABELS = {
    STATUS_SUBMITTED: "Создана",
    STATUS_IN_REVIEW: "На рассмотрении",
    STATUS_NEEDS_INFO: "Требует уточнения",
    STATUS_APPROVED: "Одобрена",
    STATUS_REJECTED: "Отклонена",
}
FINAL_STATUSES = (STATUS_APPROVED, STATUS_REJECTED)

EVENT_CREATED = "created"
EVENT_STATUS = "status"
EVENT_COMMENT = "comment"


class ServiceRequest(db.Model):
    __tablename__ = "service_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[str | None] = mapped_column(String(24), unique=True)  # человекочитаемый номер
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Факультет фиксируется при подаче: по нему определяется, какой деканат видит заявку.
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculties.id"))
    type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    fields: Mapped[dict] = mapped_column(JSONB, default=dict)  # проверенные поля формы данного типа
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_SUBMITTED)
    assigned_staff_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Ключ идемпотентности от клиента: повторная отправка той же формы не создаёт дубль.
    client_token: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    owner: Mapped[User] = relationship(foreign_keys=[owner_user_id])
    events: Mapped[list[RequestEvent]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="RequestEvent.id"
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="Attachment.id"
    )

    __table_args__ = (
        Index("ix_service_requests_owner_created", "owner_user_id", "created_at"),
        Index("ix_service_requests_faculty_status", "faculty_id", "status"),
        UniqueConstraint("owner_user_id", "client_token"),
        db.CheckConstraint(
            "status in ('submitted','in_review','needs_info','approved','rejected')", name="status_valid"
        ),
    )


class RequestEvent(db.Model):
    """Запись истории заявки: создание, смена статуса или комментарий."""

    __tablename__ = "request_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("service_requests.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str | None] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    request: Mapped[ServiceRequest] = relationship(back_populates="events")
    actor: Mapped[User | None] = relationship()


class Attachment(db.Model):
    """Файл, приложенный к заявке. Лежит в закрытом каталоге под случайным именем."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("service_requests.id", ondelete="CASCADE"), index=True)
    uploader_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    display_name: Mapped[str] = mapped_column(String(160))
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    media_type: Mapped[str] = mapped_column(String(32))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    request: Mapped[ServiceRequest] = relationship(back_populates="attachments")
