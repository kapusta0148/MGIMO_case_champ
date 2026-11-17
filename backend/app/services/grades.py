"""Успеваемость: единая шкала и объяснимые расчёты.

Все производные величины (буква, оценка, «зачтено», текущий рейтинг) считаются здесь из баллов,
чтобы экран оценок, «Сегодня» и планировщик показывали одно и то же.
Шкала демонстрационная: 100-балльная система с буквенными уровнями A–F.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .. import clock
from ..extensions import db
from ..models import Assessment, Course, ExamEvent, Term, User
from ..models.academics import (
    ASSESSMENT_CONTROL,
    ASSESSMENT_FINAL,
    CONTROL_CREDIT,
    CONTROL_FORM_LABELS,
    STATUS_GRADED,
)

PASS_THRESHOLD = 60
RISK_THRESHOLD = 67  # ниже — «зона внимания»: до порога зачёта меньше одного уровня шкалы

# (буква, минимум, максимум, оценка, подпись)
SCALE = [
    ("A", 90, 100, 5, "отлично"),
    ("B", 82, 89, 4, "хорошо"),
    ("C", 75, 81, 4, "хорошо"),
    ("D", 67, 74, 3, "удовлетворительно"),
    ("E", 60, 66, 3, "удовлетворительно"),
    ("F", 0, 59, 2, "неудовлетворительно"),
]


def scale_payload() -> list[dict]:
    return [
        {"letter": letter, "min": low, "max": high, "mark": mark, "label": label}
        for letter, low, high, mark, label in SCALE
    ]


def grade_for(score: int) -> tuple[str, int, str]:
    for letter, low, _high, mark, label in SCALE:
        if score >= low:
            return letter, mark, label
    raise ValueError(f"балл вне шкалы: {score}")


def result_payload(score: int | None, control_form: str) -> dict | None:
    """Итог по дисциплине в понятном виде. Для зачёта — «зачтено/не зачтено», иначе оценка."""
    if score is None:
        return None
    letter, mark, label = grade_for(score)
    passed = score >= PASS_THRESHOLD
    if control_form == CONTROL_CREDIT:
        return {
            "type": "credit",
            "score": score,
            "letter": letter,
            "passed": passed,
            "label": "зачтено" if passed else "не зачтено",
        }
    return {"type": "mark", "score": score, "letter": letter, "mark": mark, "passed": passed, "label": label}


def _subject_payload(course: Course) -> dict:
    return {"id": course.subject_id, "name": course.subject.name, "shortName": course.subject.short_name}


def _teacher_payload(course: Course) -> dict:
    teacher = course.teacher
    return {
        "id": teacher.id,
        "name": teacher.full_name,
        "shortName": teacher.short_name,
        "title": teacher.title,
    }


def _load(student: User) -> tuple[list[Course], dict[int, list[Assessment]], dict[int, ExamEvent]]:
    group_id = student.student.group_id
    courses = (
        db.session.execute(
            select(Course)
            .where(Course.group_id == group_id)
            .options(joinedload(Course.subject), joinedload(Course.teacher), joinedload(Course.term))
        )
        .scalars()
        .all()
    )
    by_course: dict[int, list[Assessment]] = defaultdict(list)
    # Только строки этого студента: фильтр по владельцу задаётся сервером, не клиентом.
    rows = db.session.execute(
        select(Assessment)
        .where(Assessment.student_user_id == student.id)
        .order_by(Assessment.course_id, Assessment.position)
    ).scalars()
    for row in rows:
        by_course[row.course_id].append(row)
    exams = {
        event.course_id: event
        for event in db.session.execute(
            select(ExamEvent).where(ExamEvent.course_id.in_([c.id for c in courses] or [0]))
        ).scalars()
    }
    return list(courses), by_course, exams


def _control_payload(item: Assessment) -> dict:
    payload = {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "score": item.score,
        "maxScore": 100,
        "date": item.assessed_on.isoformat() if item.assessed_on else None,
    }
    if item.score is not None:
        payload["letter"] = grade_for(item.score)[0]
    return payload


def current_score(controls: list[Assessment]) -> int | None:
    """Текущий рейтинг — среднее арифметическое проверенных работ текущего контроля."""
    scores = [c.score for c in controls if c.status == STATUS_GRADED and c.score is not None]
    if not scores:
        return None
    return round(sum(scores) / len(scores))


def _course_payload(course: Course, items: list[Assessment], exam: ExamEvent | None) -> dict:
    controls = [i for i in items if i.kind == ASSESSMENT_CONTROL]
    final = next((i for i in items if i.kind == ASSESSMENT_FINAL), None)
    rating = current_score(controls)
    final_payload = {
        "status": final.status if final else "expected",
        "result": result_payload(final.score, course.control_form) if final else None,
        "retakes": final.retakes if final else 0,
        "date": final.assessed_on.isoformat() if final and final.assessed_on else None,
        "startsAt": clock.iso(exam.starts_at) if exam else None,
        "room": exam.room if exam else None,
    }
    return {
        "courseId": course.id,
        "subject": _subject_payload(course),
        "teacher": _teacher_payload(course),
        "controlForm": course.control_form,
        "controlFormLabel": CONTROL_FORM_LABELS[course.control_form],
        "currentScore": rating,
        "currentLetter": grade_for(rating)[0] if rating is not None else None,
        "atRisk": rating is not None and rating < RISK_THRESHOLD,
        "controls": [_control_payload(c) for c in controls],
        "final": final_payload,
    }


def _session_state(term: Term, today: date) -> str:
    if today < term.session_starts_on:
        return "upcoming"
    if today <= term.session_ends_on:
        return "in_progress"
    return "closed"


def _term_payload(term: Term, courses: list[dict], today: date) -> dict:
    graded = [c["currentScore"] for c in courses if c["currentScore"] is not None]
    finals = [c["final"]["result"] for c in courses if c["final"]["result"]]
    debts = [
        c["subject"]["name"]
        for c in courses
        if c["final"]["result"] is not None and not c["final"]["result"]["passed"]
    ]
    retaken = [c["subject"]["name"] for c in courses if c["final"]["retakes"] > 0]
    final_scores = [r["score"] for r in finals]
    return {
        "id": term.id,
        "title": term.title,
        "isCurrent": term.is_current,
        "courses": courses,
        "summary": {
            "averageCurrentScore": round(sum(graded) / len(graded)) if graded else None,
            "averageFinalScore": round(sum(final_scores) / len(final_scores)) if final_scores else None,
            "coursesTotal": len(courses),
            "finalsDone": len(finals),
            "debts": debts,
            "retaken": retaken,
            "atRisk": [c["subject"]["name"] for c in courses if c["atRisk"]],
        },
        "session": {
            "title": term.session_title,
            "state": _session_state(term, today),
            "startsOn": term.session_starts_on.isoformat(),
            "endsOn": term.session_ends_on.isoformat(),
        },
    }


def grades_overview(student: User) -> dict:
    """Полная картина успеваемости одного студента."""
    today = clock.today()
    courses, by_course, exams = _load(student)
    by_term: dict[int, list[dict]] = defaultdict(list)
    terms: dict[int, Term] = {}
    for course in sorted(courses, key=lambda c: c.subject.name):
        terms[course.term_id] = course.term
        by_term[course.term_id].append(
            _course_payload(course, by_course.get(course.id, []), exams.get(course.id))
        )

    payloads = [_term_payload(terms[term_id], items, today) for term_id, items in by_term.items()]
    payloads.sort(key=lambda t: terms[t["id"]].starts_on, reverse=True)
    current = next((t for t in payloads if t["isCurrent"]), None)
    past = [t for t in payloads if not t["isCurrent"]]

    return {
        "scale": scale_payload(),
        "passThreshold": PASS_THRESHOLD,
        "riskThreshold": RISK_THRESHOLD,
        "currentTerm": current,
        "pastTerms": past,
        "explanations": {
            "currentScore": "Текущий рейтинг — среднее баллов за проверенные работы семестра.",
            "atRisk": f"Зона внимания — текущий рейтинг ниже {RISK_THRESHOLD} баллов.",
            "expected": "«Ожидается» — работа, зачёт или экзамен ещё впереди, результата пока нет.",
        },
    }
