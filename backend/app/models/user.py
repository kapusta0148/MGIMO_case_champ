"""Учётные записи, профили и серверные сессии."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import clock
from ..extensions import db
from .org import Faculty, StudyGroup

ROLE_STUDENT = "student"
ROLE_DEAN = "dean_staff"
ROLE_TEACHER = "teacher"
ROLE_ADMIN = "admin"
ROLES = (ROLE_STUDENT, ROLE_DEAN, ROLE_TEACHER, ROLE_ADMIN)
STAFF_ROLES = (ROLE_DEAN, ROLE_TEACHER, ROLE_ADMIN)

ROLE_LABELS = {
    ROLE_STUDENT: "Студент",
    ROLE_DEAN: "Сотрудник деканата",
    ROLE_TEACHER: "Преподаватель",
    ROLE_ADMIN: "Администратор",
}


class User(db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    # Признак автоматически сгенерированного демо-аккаунта; открытая регистрация пока не реализована.
    is_generated: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    student: Mapped[StudentProfile | None] = relationship(back_populates="user", uselist=False)
    staff: Mapped[StaffProfile | None] = relationship(back_populates="user", uselist=False)

    __table_args__ = (
        db.CheckConstraint("role in ('student','dean_staff','teacher','admin')", name="role_valid"),
        db.CheckConstraint("username = lower(username)", name="username_lowercase"),
    )

    @property
    def full_name(self) -> str:
        if self.student:
            return self.student.full_name
        if self.staff:
            return self.staff.full_name
        return self.username

    @property
    def is_student(self) -> bool:
        return self.role == ROLE_STUDENT


class StudentProfile(db.Model):
    __tablename__ = "student_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))  # вымышленное ФИО
    group_id: Mapped[int] = mapped_column(ForeignKey("study_groups.id"), index=True)
    record_book: Mapped[str] = mapped_column(String(32), unique=True)  # вымышленный номер зачётки

    user: Mapped[User] = relationship(back_populates="student")
    group: Mapped[StudyGroup] = relationship()


class StaffProfile(db.Model):
    __tablename__ = "staff_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    position: Mapped[str] = mapped_column(String(160))

    user: Mapped[User] = relationship(back_populates="staff")
    scopes: Mapped[list[StaffScope]] = relationship(back_populates="staff", cascade="all, delete-orphan")

    @property
    def faculty_ids(self) -> set[int]:
        return {scope.faculty_id for scope in self.scopes}


class StaffScope(db.Model):
    """Зона ответственности сотрудника деканата: факультеты, чьи заявки и расписание он видит."""

    __tablename__ = "staff_scopes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("staff_profiles.user_id", ondelete="CASCADE"), index=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculties.id"))

    staff: Mapped[StaffProfile] = relationship(back_populates="scopes")
    faculty: Mapped[Faculty] = relationship()

    __table_args__ = (UniqueConstraint("user_id", "faculty_id"),)


class AuthSession(db.Model):
    """Серверная запись о сессии.

    В подписанной cookie лежит только случайный идентификатор; здесь хранится его SHA-256.
    Выход помечает запись отозванной, поэтому украденная или сохранённая cookie перестаёт работать.
    """

    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    sid_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()

    __table_args__ = (Index("ix_auth_sessions_expires_at", "expires_at"),)
