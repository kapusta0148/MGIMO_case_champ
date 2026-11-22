"""Кабинет преподавателя: только закреплённые за ним курсы (дисциплина × группа × семестр).

Чужой курс или оценка чужого курса неотличимы от несуществующих (404).
Оценки меняются только в текущем семестре; каждое изменение пишется в журнал аудита,
студент получает уведомление.
"""

from __future__ import annotations

from collections import defaultdict

from flask import Blueprint, jsonify
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .. import clock
from ..errors import ApiError, not_found, validation_error
from ..extensions import db
from ..models import Assessment, Course, StudentProfile, StudyGroup, Teacher, User
from ..models.academics import (
    ASSESSMENT_CONTROL,
    ASSESSMENT_FINAL,
    CONTROL_FORM_LABELS,
    STATUS_EXPECTED,
    STATUS_GRADED,
)
from ..models.comms import NOTIFY_GRADE, SOURCE_COURSE
from ..models.user import ROLE_TEACHER
from ..security.auth import current_user, roles_required
from ..services import audit, notifications
from ..services.grades import current_score, grade_for, result_payload
from .auth import json_body

bp = Blueprint("teacher", __name__, url_prefix="/api/teacher")
teacher_only = roles_required(ROLE_TEACHER)


def _course_query(user: User):
    return (
        select(Course)
        .join(Teacher, Teacher.id == Course.teacher_id)
        .where(Teacher.user_id == user.id)
        .options(
            joinedload(Course.subject),
            joinedload(Course.term),
            joinedload(Course.group).joinedload(StudyGroup.program),
        )
    )


def _get_own_course(course_id: int, user: User) -> Course:
    course = db.session.execute(_course_query(user).where(Course.id == course_id)).scalar_one_or_none()
    if course is None:
        raise not_found("Курс не найден.")
    return course


def _course_payload(course: Course, students: int | None = None) -> dict:
    payload = {
        "id": course.id,
        "subject": course.subject.name,
        "group": course.group.name,
        "faculty": course.group.program.faculty.code,
        "term": course.term.title,
        "isCurrent": course.term.is_current,
        "controlForm": course.control_form,
        "controlFormLabel": CONTROL_FORM_LABELS[course.control_form],
    }
    if students is not None:
        payload["students"] = students
    return payload


def _students_of(course: Course) -> list[StudentProfile]:
    return list(
        db.session.execute(
            select(StudentProfile)
            .join(User, User.id == StudentProfile.user_id)
            .where(StudentProfile.group_id == course.group_id, User.is_active.is_(True))
            .order_by(StudentProfile.full_name)
        ).scalars()
    )


@bp.get("/courses")
@teacher_only
def courses():
    user = current_user()
    items = list(db.session.execute(_course_query(user)).scalars())
    items.sort(key=lambda c: (not c.term.is_current, c.subject.name, c.group.name))
    return jsonify({"items": [_course_payload(c, len(_students_of(c))) for c in items]})


def _assessment_payload(item: Assessment) -> dict:
    return {
        "id": item.id,
        "kind": item.kind,
        "title": item.title,
        "position": item.position,
        "date": item.assessed_on.isoformat() if item.assessed_on else None,
        "score": item.score,
        "status": item.status,
        "letter": grade_for(item.score)[0] if item.score is not None else None,
        "updatedAt": clock.iso(item.updated_at),
    }


@bp.get("/courses/<int:course_id>")
@teacher_only
def course_grades(course_id: int):
    user = current_user()
    course = _get_own_course(course_id, user)
    students = _students_of(course)
    rows = db.session.execute(
        select(Assessment)
        .where(Assessment.course_id == course.id)
        .order_by(Assessment.kind, Assessment.position)
    ).scalars()
    by_student: dict[int, list[Assessment]] = defaultdict(list)
    for row in rows:
        by_student[row.student_user_id].append(row)

    columns: dict[int, dict] = {}
    result = []
    for student in students:
        items = by_student.get(student.user_id, [])
        controls = [i for i in items if i.kind == ASSESSMENT_CONTROL]
        final = next((i for i in items if i.kind == ASSESSMENT_FINAL), None)
        for control in controls:
            columns.setdefault(control.position, {"position": control.position, "title": control.title})
        rating = current_score(controls)
        result.append(
            {
                "userId": student.user_id,
                "name": student.full_name,
                "recordBook": student.record_book,
                "controls": [_assessment_payload(c) for c in controls],
                "final": _assessment_payload(final) if final else None,
                "finalResult": result_payload(final.score, course.control_form) if final else None,
                "currentScore": rating,
            }
        )
    return jsonify(
        {
            "course": _course_payload(course, len(students)),
            "editable": course.term.is_current,
            "columns": [columns[k] for k in sorted(columns)],
            "students": result,
        }
    )


@bp.patch("/assessments/<int:assessment_id>")
@teacher_only
def update_assessment(assessment_id: int):
    """Поставить или снять балл. Только в своём курсе текущего семестра."""
    user = current_user()
    item = db.session.get(Assessment, assessment_id)
    if item is None:
        raise not_found("Оценка не найдена.")
    course = _get_own_course(item.course_id, user)  # 404 для чужого курса
    if not course.term.is_current:
        raise ApiError(409, "term_closed", "Ведомость прошлого семестра закрыта для изменений.")

    raw = json_body().get("score", ...)
    if raw is ...:
        raise validation_error({"score": "Укажите балл от 0 до 100 или пустое значение."})
    if raw is None or raw == "":
        score = None
    elif isinstance(raw, bool) or not isinstance(raw, int | str):
        raise validation_error({"score": "Балл — целое число от 0 до 100."})
    else:
        try:
            score = int(raw)
        except ValueError:
            raise validation_error({"score": "Балл — целое число от 0 до 100."}) from None
        if not 0 <= score <= 100:
            raise validation_error({"score": "Балл — целое число от 0 до 100."})

    before = {"score": item.score, "status": item.status}
    if score == item.score:
        return jsonify({"assessment": _assessment_payload(item), "changed": False})
    item.score = score
    item.status = STATUS_GRADED if score is not None else STATUS_EXPECTED
    item.updated_by_user_id = user.id
    item.updated_at = clock.now()
    audit.record(
        user,
        "assessment.update",
        "assessment",
        item.id,
        before=before,
        after={"score": item.score, "status": item.status, "studentUserId": item.student_user_id},
    )
    if score is not None:
        title = "Итог" if item.kind == ASSESSMENT_FINAL else item.title
        notifications.notify(
            item.student_user_id,
            kind=NOTIFY_GRADE,
            title=f"Новая оценка: {course.subject.name}",
            body=f"{title} — {score} из 100.",
            source_type=SOURCE_COURSE,
            source_id=course.id,
            dedupe_key=f"assessment:{item.id}",
        )
    db.session.commit()
    controls = list(
        db.session.execute(
            select(Assessment).where(
                Assessment.course_id == course.id,
                Assessment.student_user_id == item.student_user_id,
                Assessment.kind == ASSESSMENT_CONTROL,
            )
        ).scalars()
    )
    return jsonify(
        {
            "assessment": _assessment_payload(item),
            "changed": True,
            "currentScore": current_score(controls),
            "finalResult": result_payload(item.score, course.control_form)
            if item.kind == ASSESSMENT_FINAL
            else None,
        }
    )
