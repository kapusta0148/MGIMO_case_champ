"""Структура вуза: факультеты, направления подготовки, учебные группы. Все записи вымышленные."""

from __future__ import annotations

from sqlalchemy import ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..extensions import db


class Faculty(db.Model):
    __tablename__ = "faculties"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    name: Mapped[str] = mapped_column(String(200))

    programs: Mapped[list[Program]] = relationship(back_populates="faculty")


class Program(db.Model):
    """Направление подготовки."""

    __tablename__ = "programs"

    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_id: Mapped[int] = mapped_column(ForeignKey("faculties.id"), index=True)
    code: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    degree: Mapped[str] = mapped_column(String(40), default="бакалавриат")

    faculty: Mapped[Faculty] = relationship(back_populates="programs")
    groups: Mapped[list[StudyGroup]] = relationship(back_populates="program")


class StudyGroup(db.Model):
    """Академическая группа. Расписание, дедлайны и объявления привязаны к группе."""

    __tablename__ = "study_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int] = mapped_column(ForeignKey("programs.id"), index=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)
    year: Mapped[int] = mapped_column(SmallInteger)  # курс обучения
    admission_year: Mapped[int] = mapped_column(SmallInteger)
    # Резерв для отбора групп при добавлении демо-регистрации.
    open_for_demo: Mapped[bool] = mapped_column(default=True)

    program: Mapped[Program] = relationship(back_populates="groups")

    @property
    def faculty(self) -> Faculty:
        return self.program.faculty
