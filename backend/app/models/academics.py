"""Учебный процесс: семестры, дисциплины, преподаватели, курсы, занятия, оценки, сессия."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .. import clock
from ..extensions import db
from .org import StudyGroup

CONTROL_EXAM = "exam"
CONTROL_CREDIT = "credit"
CONTROL_GRADED_CREDIT = "graded_credit"
CONTROL_FORM_LABELS = {
    CONTROL_EXAM: "Экзамен",
    CONTROL_CREDIT: "Зачёт",
    CONTROL_GRADED_CREDIT: "Зачёт с оценкой",
}

LESSON_KIND_LABELS = {
    "lecture": "Лекция",
    "seminar": "Семинар",
    "practice": "Практическое занятие",
    "language": "Языковая практика",
}

LESSON_SCHEDULED = "scheduled"
LESSON_MOVED = "moved"
LESSON_CANCELLED = "cancelled"

ASSESSMENT_CONTROL = "control"  # текущий контроль в семестре
ASSESSMENT_FINAL = "final"  # итог: экзамен или зачёт
STATUS_GRADED = "graded"
STATUS_EXPECTED = "expected"


class Term(db.Model):
    """Семестр."""

    __tablename__ = "terms"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True)
    title: Mapped[str] = mapped_column(String(80))
    starts_on: Mapped[date] = mapped_column(Date)
    ends_on: Mapped[date] = mapped_column(Date)
    session_title: Mapped[str] = mapped_column(String(80))
    session_starts_on: Mapped[date] = mapped_column(Date)
    session_ends_on: Mapped[date] = mapped_column(Date)
    is_current: Mapped[bool] = mapped_column(default=False)


class Subject(db.Model):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    short_name: Mapped[str] = mapped_column(String(40))


class Teacher(db.Model):
    """Преподаватель как персона в расписании. Учётная запись есть не у каждого."""

    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    short_name: Mapped[str] = mapped_column(String(60))  # «Корнилова Е. А.»
    title: Mapped[str] = mapped_column(String(40))  # «доц.», «проф.»
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)


class Course(db.Model):
    """Дисциплина, которую конкретный преподаватель ведёт у конкретной группы в семестре.

    Это и есть «назначение» преподавателя: менять оценки он может только в своих курсах.
    """

    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("study_groups.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    control_form: Mapped[str] = mapped_column(String(16))

    term: Mapped[Term] = relationship()
    group: Mapped[StudyGroup] = relationship()
    subject: Mapped[Subject] = relationship()
    teacher: Mapped[Teacher] = relationship()

    __table_args__ = (
        UniqueConstraint("term_id", "group_id", "subject_id"),
        db.CheckConstraint("control_form in ('exam','credit','graded_credit')", name="control_form_valid"),
    )


class Lesson(db.Model):
    """Занятие. Единственный источник правды для расписания, экрана «Сегодня» и уведомлений о переносе.

    При переносе текущие значения перезаписываются, а исходные сохраняются в original_*.
    """

    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"))
    kind: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    room: Mapped[str] = mapped_column(String(40))

    status: Mapped[str] = mapped_column(String(16), default=LESSON_SCHEDULED)
    original_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_room: Mapped[str | None] = mapped_column(String(40))
    change_reason: Mapped[str | None] = mapped_column(String(300))
    changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    changed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    course: Mapped[Course] = relationship()
    teacher: Mapped[Teacher] = relationship()

    __table_args__ = (
        Index("ix_lessons_course_starts", "course_id", "starts_at"),
        Index("ix_lessons_starts_at", "starts_at"),
        db.CheckConstraint("ends_at > starts_at", name="time_order"),
        db.CheckConstraint("status in ('scheduled','moved','cancelled')", name="status_valid"),
    )


class Assessment(db.Model):
    """Результат студента: текущий контроль (control) или итог по дисциплине (final).

    Хранится балл 0–100; буква, оценка и «зачтено» выводятся из него по единой шкале (services/grades.py).
    status='expected' означает, что работа или экзамен ещё впереди.
    """

    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    student_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(160))
    position: Mapped[int] = mapped_column(SmallInteger, default=0)  # порядок внутри курса
    score: Mapped[int | None] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_EXPECTED)
    assessed_on: Mapped[date | None] = mapped_column(Date)  # дата проведения (план или факт)
    retakes: Mapped[int] = mapped_column(SmallInteger, default=0)  # число пересдач итога
    updated_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=clock.now, onupdate=clock.now
    )

    course: Mapped[Course] = relationship()

    __table_args__ = (
        Index("ix_assessments_student_course", "student_user_id", "course_id"),
        UniqueConstraint("course_id", "student_user_id", "kind", "position"),
        db.CheckConstraint("kind in ('control','final')", name="kind_valid"),
        db.CheckConstraint("status in ('graded','expected')", name="status_valid"),
        db.CheckConstraint("score is null or (score >= 0 and score <= 100)", name="score_range"),
        db.CheckConstraint("(status = 'graded') = (score is not null)", name="score_matches_status"),
    )


class ExamEvent(db.Model):
    """Экзамен или зачёт в расписании сессии."""

    __tablename__ = "exam_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), unique=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    room: Mapped[str] = mapped_column(String(40))

    course: Mapped[Course] = relationship()


class Deadline(db.Model):
    """Учебный дедлайн группы по дисциплине (эссе, контрольная, подача документов)."""

    __tablename__ = "deadlines"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("study_groups.id"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    course: Mapped[Course | None] = relationship()

    __table_args__ = (Index("ix_deadlines_group_due", "group_id", "due_at"),)


class PersonalTask(db.Model):
    """Личная задача студента: своя или принятая из предложения планировщика.

    source_key — ключ предложения планировщика: повторное «Добавить» не создаёт дубль.
    """

    __tablename__ = "personal_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(160))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    deadline_id: Mapped[int | None] = mapped_column(ForeignKey("deadlines.id", ondelete="SET NULL"))
    source_key: Mapped[str | None] = mapped_column(String(80))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    deadline: Mapped[Deadline | None] = relationship()

    __table_args__ = (
        Index("ix_personal_tasks_owner_completed", "owner_user_id", "completed_at"),
        UniqueConstraint("owner_user_id", "source_key"),
        db.CheckConstraint(
            "planned_start is null or (planned_end is not null and planned_end > planned_start)",
            name="planned_order",
        ),
        db.CheckConstraint(
            "estimated_minutes is null or (estimated_minutes between 5 and 600)", name="estimate_range"
        ),
    )
