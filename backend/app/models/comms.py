"""Объявления деканата и персональные уведомления."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import clock
from ..extensions import db
from .org import Faculty, StudyGroup
from .user import User

NOTIFY_LESSON_CHANGE = "lesson_change"
NOTIFY_ANNOUNCEMENT = "announcement"
NOTIFY_DEADLINE = "deadline"
NOTIFY_REQUEST = "request_status"
NOTIFY_GRADE = "grade"

SOURCE_LESSON = "lesson"
SOURCE_ANNOUNCEMENT = "announcement"
SOURCE_DEADLINE = "deadline"
SOURCE_REQUEST = "request"
SOURCE_COURSE = "course"

NOTIFICATION_KIND_LABELS = {
    NOTIFY_LESSON_CHANGE: "Расписание",
    NOTIFY_ANNOUNCEMENT: "Деканат",
    NOTIFY_DEADLINE: "Дедлайн",
    NOTIFY_REQUEST: "Заявка",
    NOTIFY_GRADE: "Оценка",
}


class Announcement(db.Model):
    """Объявление деканата. Адресаты: вся аудитория, факультет или одна группа."""

    __tablename__ = "announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    author_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculties.id"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("study_groups.id"))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    author: Mapped[User | None] = relationship()
    faculty: Mapped[Faculty | None] = relationship()
    group: Mapped[StudyGroup | None] = relationship()


class Notification(db.Model):
    """Уведомление конкретному пользователю.

    Хранит ссылку на объект-источник (source_type + source_id). Для переносов, объявлений и
    дедлайнов текст при выдаче собирается из актуального состояния источника, поэтому уведомление
    не может разойтись с расписанием.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    recipient_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str | None] = mapped_column(String(24))
    source_id: Mapped[int | None] = mapped_column()
    # Ключ против дублей: одно уведомление на событие (например, «перенос занятия №N»).
    dedupe_key: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_notifications_recipient_created", "recipient_user_id", "created_at"),
        UniqueConstraint("recipient_user_id", "dedupe_key"),
    )
