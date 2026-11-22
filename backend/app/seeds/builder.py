"""Наполнение базы демонстрационными данными.

События (объявления, статусы заявок, перенос занятия) создаются теми же сервисами, которыми
пользуется работающее приложение, поэтому уведомления и разделы изначально согласованы.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from .. import clock
from ..extensions import db
from ..models import (
    Announcement,
    Assessment,
    Course,
    Deadline,
    ExamEvent,
    Faculty,
    Lesson,
    Notification,
    Program,
    StaffProfile,
    StaffScope,
    StudentProfile,
    StudyGroup,
    Subject,
    Teacher,
    Term,
    User,
)
from ..models.academics import ASSESSMENT_CONTROL, ASSESSMENT_FINAL, STATUS_EXPECTED, STATUS_GRADED
from ..models.comms import NOTIFY_GRADE, SOURCE_COURSE
from ..models.requests import STATUS_APPROVED, STATUS_IN_REVIEW, STATUS_NEEDS_INFO
from ..models.user import ROLE_STUDENT
from ..security.auth import hash_password
from ..services import demo, notifications, schedule
from ..services import requests as request_service
from . import data

CHECK_DELAY = timedelta(days=3)  # работа считается проверенной через три дня после сдачи


def _score(seed: str, subject: str, title: str, base: int, spread: int, offset: int = 0) -> int:
    """Детерминированный вымышленный балл: один и тот же при каждом пересоздании базы."""
    rng = random.Random(f"{seed}|{subject}|{title}")
    return max(38, min(100, round(rng.gauss(base + offset, spread))))


def _shift(day: date, offset: int) -> date:
    """Сдвинуть дату на несколько дней, не попадая на воскресенье."""
    shifted = day + timedelta(days=offset)
    return shifted + timedelta(days=1) if shifted.weekday() == 6 else shifted


def _control_plan(course: Course, template_key: str, index: int) -> list[tuple[str, date]]:
    return [(title, _shift(day, index % 4)) for title, day in data.CONTROL_TEMPLATES[template_key]]


def enroll_student(
    *,
    username: str,
    password: str,
    full_name: str,
    group: StudyGroup,
    record_book: str,
    base: int,
    spread: int,
    offsets: dict[str, int] | None = None,
    final_overrides: dict[str, tuple[int, int]] | None = None,
    is_generated: bool = False,
) -> User:
    """Создать студента и его личные учебные результаты по всем дисциплинам группы."""
    offsets = offsets or {}
    final_overrides = final_overrides or {}
    today = clock.today()
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=ROLE_STUDENT,
        is_generated=is_generated,
        created_at=clock.now(),
    )
    user.student = StudentProfile(full_name=full_name, group_id=group.id, record_book=record_book)
    db.session.add(user)
    db.session.flush()

    courses = db.session.execute(
        select(Course).where(Course.group_id == group.id).order_by(Course.id)
    ).scalars()
    for course in courses:
        subject = course.subject.name
        offset = offsets.get(subject, 0)
        plan = COURSE_PLANS.get(course.id)
        if course.term.is_current and plan is not None:
            pe = plan["controls"] == "pe"
            for position, (title, day) in enumerate(plan["items"]):
                graded = day + CHECK_DELAY <= today
                score = None
                if graded:
                    score = _score(
                        username, subject, title, 94 if pe else base, 3 if pe else spread, 0 if pe else offset
                    )
                db.session.add(
                    Assessment(
                        course_id=course.id,
                        student_user_id=user.id,
                        kind=ASSESSMENT_CONTROL,
                        title=title,
                        position=position,
                        score=score,
                        status=STATUS_GRADED if graded else STATUS_EXPECTED,
                        assessed_on=day,
                    )
                )
            db.session.add(
                Assessment(
                    course_id=course.id,
                    student_user_id=user.id,
                    kind=ASSESSMENT_FINAL,
                    title="Итог по дисциплине",
                    position=100,
                    status=STATUS_EXPECTED,
                    assessed_on=plan["exam_day"],
                )
            )
        else:
            score, retakes = final_overrides.get(subject, (None, 0))
            if score is None:
                score = max(60, _score(username, subject, "итог", base, spread, offset))
            db.session.add(
                Assessment(
                    course_id=course.id,
                    student_user_id=user.id,
                    kind=ASSESSMENT_FINAL,
                    title="Итог по дисциплине",
                    position=100,
                    score=score,
                    status=STATUS_GRADED,
                    assessed_on=PAST_FINAL_DAYS.get(course.id),
                    retakes=retakes,
                )
            )
    db.session.flush()
    return user


# Планы контроля и даты итогов; подготовлены для будущего создания демо-профилей.
COURSE_PLANS: dict[int, dict] = {}
PAST_FINAL_DAYS: dict[int, date] = {}


def load_course_plans() -> None:
    """Восстановить планы курсов из демонстрационных данных после перезапуска приложения."""
    COURSE_PLANS.clear()
    PAST_FINAL_DAYS.clear()
    groups = {g.name: g for g in db.session.execute(select(StudyGroup)).scalars()}
    courses = {
        (c.group_id, c.subject.name, c.term.is_current): c
        for c in db.session.execute(select(Course)).scalars()
    }
    for group_name, specs in data.AUTUMN_COURSES.items():
        group = groups.get(group_name)
        if group is None:
            continue
        for index, spec in enumerate(specs):
            course = courses.get((group.id, spec["subject"], True))
            if course is not None:
                COURSE_PLANS[course.id] = {
                    "controls": spec["controls"],
                    "items": _control_plan(course, spec["controls"], index),
                    "exam_day": spec["exam"][0],
                }
    for group_name, specs in data.SPRING_COURSES.items():
        group = groups.get(group_name)
        if group is None:
            continue
        for subject, _short, _teacher, _form, day in specs:
            course = courses.get((group.id, subject, False))
            if course is not None:
                PAST_FINAL_DAYS[course.id] = day


def _subject(cache: dict[str, Subject], name: str, short: str) -> Subject:
    if name not in cache:
        cache[name] = Subject(name=name, short_name=short)
        db.session.add(cache[name])
    return cache[name]


def _build_structure() -> tuple[dict[str, Faculty], dict[str, StudyGroup]]:
    faculties = {code: Faculty(code=code, name=name) for code, name in data.FACULTIES}
    db.session.add_all(faculties.values())
    programs = {}
    for faculty_code, code, name in data.PROGRAMS:
        programs[code] = Program(faculty=faculties[faculty_code], code=code, name=name)
    db.session.add_all(programs.values())
    groups = {}
    for spec in data.GROUPS:
        groups[spec["name"]] = StudyGroup(
            program=programs[spec["program"]],
            name=spec["name"],
            year=spec["year"],
            admission_year=spec["admission_year"],
        )
    db.session.add_all(groups.values())
    db.session.flush()
    return faculties, groups


def _build_courses(
    groups: dict[str, StudyGroup], teachers: dict[str, Teacher]
) -> dict[tuple[str, str], Course]:
    spring = Term(**data.TERM_SPRING)
    autumn = Term(**data.TERM_AUTUMN)
    db.session.add_all([spring, autumn])
    subjects: dict[str, Subject] = {}
    current: dict[tuple[str, str], Course] = {}
    for group_name, specs in data.AUTUMN_COURSES.items():
        for spec in specs:
            course = Course(
                term=autumn,
                group=groups[group_name],
                subject=_subject(subjects, spec["subject"], spec["short"]),
                teacher=teachers[spec["teacher"]],
                control_form=spec["form"],
            )
            db.session.add(course)
            current[(group_name, spec["subject"])] = course
    for group_name, specs in data.SPRING_COURSES.items():
        for subject, short, teacher, form, _day in specs:
            db.session.add(
                Course(
                    term=spring,
                    group=groups[group_name],
                    subject=_subject(subjects, subject, short),
                    teacher=teachers[teacher],
                    control_form=form,
                )
            )
    db.session.flush()
    for (group_name, subject), course in current.items():
        spec = next(s for s in data.AUTUMN_COURSES[group_name] if s["subject"] == subject)
        day, at, room = spec["exam"]
        db.session.add(ExamEvent(course_id=course.id, starts_at=clock.local_dt(day, at), room=room))
    load_course_plans()
    return current


def _build_lessons(courses: dict[tuple[str, str], Course], first: date, last: date) -> int:
    slots = {number: (start, end) for number, start, end in schedule.PAIR_SLOTS}
    first = max(first, data.TERM_AUTUMN["starts_on"])
    last = min(last, data.TERM_AUTUMN["ends_on"])
    count = 0
    for (group_name, subject), course in courses.items():
        spec = next(s for s in data.AUTUMN_COURSES[group_name] if s["subject"] == subject)
        for weekday, pair, kind, room in spec["slots"]:
            day = first + timedelta(days=(weekday - first.weekday()) % 7)
            while day <= last:
                if day not in data.HOLIDAYS:
                    start, end = slots[pair]
                    db.session.add(
                        Lesson(
                            course_id=course.id,
                            teacher_id=course.teacher_id,
                            kind=kind,
                            starts_at=clock.local_dt(day, start),
                            ends_at=clock.local_dt(day, end),
                            room=room,
                        )
                    )
                    count += 1
                day += timedelta(days=7)
    db.session.flush()
    return count


def _build_deadlines(groups: dict[str, StudyGroup], courses: dict[tuple[str, str], Course]) -> None:
    for group_name, items in data.DEADLINES.items():
        for day, at, subject, kind, title, description in items:
            course = courses[(group_name, subject)] if subject else None
            db.session.add(
                Deadline(
                    group_id=groups[group_name].id,
                    course_id=course.id if course else None,
                    kind=kind,
                    title=title,
                    description=description,
                    due_at=clock.local_dt(day, at),
                )
            )
    db.session.flush()


def _build_staff(
    passwords: dict[str, str], faculties: dict[str, Faculty], teachers: dict[str, Teacher]
) -> dict[str, User]:
    staff: dict[str, User] = {}
    for spec in data.STAFF:
        user = User(
            username=spec["username"],
            password_hash=hash_password(passwords[spec["key"]]),
            role=spec["role"],
            created_at=clock.now(),
        )
        user.staff = StaffProfile(full_name=spec["full_name"], position=spec["position"])
        user.staff.scopes = [StaffScope(faculty=faculties[code]) for code in spec["faculties"]]
        db.session.add(user)
        db.session.flush()
        if spec.get("teacher_key"):
            teachers[spec["teacher_key"]].user_id = user.id
        staff[spec["key"]] = user
    return staff


def _past(now: datetime, day: date, at: time) -> datetime:
    """Момент в прошлом для «исторических» событий; не позже текущего времени."""
    return min(clock.local_dt(day, at), now - timedelta(minutes=5))


def _build_announcements(now: datetime, faculties, groups, author: User) -> None:
    for day, at, audience, title, body in data.ANNOUNCEMENTS:
        moment = _past(now, day, at)
        with clock.frozen(moment):
            item = Announcement(author_user_id=author.id, title=title, body=body, published_at=moment)
            if audience[0] == "faculty":
                item.faculty_id = faculties[audience[1]].id
            elif audience[0] == "group":
                item.group_id = groups[audience[1]].id
            db.session.add(item)
            db.session.flush()
            notifications.notify_announcement(item)


def _build_requests(now: datetime, students: dict[str, User], dean: User) -> None:
    """Несколько заявок с историей, чтобы разделы не были пустыми и различались у студентов."""
    today = clock.to_local(now).date()

    def at(days_ago: int, hour: int, minute: int = 0) -> datetime:
        return _past(now, today - timedelta(days=days_ago), time(hour, minute))

    mira, timur = students["student1"], students["student2"]

    with clock.frozen(at(12, 11, 20)):
        done, _ = request_service.create_request(
            mira, {"type": "transcript", "fields": {"period": "last_term", "copies": 1, "delivery": "office"}}
        )
    with clock.frozen(at(12, 15, 5)):
        request_service.transition(done, actor=dean, to_status=STATUS_IN_REVIEW, comment=None)
    with clock.frozen(at(10, 12, 40)):
        request_service.transition(
            done, actor=dean, to_status=STATUS_APPROVED,
            comment="Справка готова. Забрать можно в деканате, кабинет 2010, с 10:00 до 17:00.",
        )  # fmt: skip

    with clock.frozen(at(2, 18, 12)):
        pending, _ = request_service.create_request(
            mira,
            {"type": "study_certificate", "fields": {"purpose": "visa", "copies": 2, "delivery": "office"},
             "comment": "Нужна для подачи документов на визу до конца месяца."},
        )  # fmt: skip
    with clock.frozen(at(1, 10, 30)):
        request_service.transition(pending, actor=dean, to_status=STATUS_IN_REVIEW, comment=None)

    with clock.frozen(at(30, 13, 0)):
        old, _ = request_service.create_request(
            timur,
            {
                "type": "study_certificate",
                "fields": {"purpose": "employer", "copies": 1, "delivery": "electronic"},
            },
        )
    with clock.frozen(at(29, 9, 45)):
        request_service.transition(old, actor=dean, to_status=STATUS_IN_REVIEW, comment=None)
    with clock.frozen(at(27, 16, 10)):
        request_service.transition(
            old,
            actor=dean,
            to_status=STATUS_APPROVED,
            comment="Электронная копия справки направлена в кабинет.",
        )

    absence_from = today - timedelta(days=6)
    with clock.frozen(at(4, 9, 30)):
        absence, _ = request_service.create_request(
            timur,
            {"type": "absence",
             "fields": {"date_from": absence_from.isoformat(),
                        "date_to": (absence_from + timedelta(days=1)).isoformat(), "reason": "illness"},
             "comment": "Болел два дня, справка из поликлиники есть."},
        )  # fmt: skip
    with clock.frozen(at(4, 14, 0)):
        request_service.transition(absence, actor=dean, to_status=STATUS_IN_REVIEW, comment=None)
    with clock.frozen(at(3, 11, 15)):
        request_service.transition(
            absence, actor=dean, to_status=STATUS_NEEDS_INFO,
            comment="Пожалуйста, приложите скан или фото медицинской справки.",
        )  # fmt: skip


def _build_grade_notifications(now: datetime, students: dict[str, User]) -> None:
    """«Новая оценка» по работам, проверенным за последнюю неделю."""
    today = clock.to_local(now).date()
    for user in students.values():
        recent = db.session.execute(
            select(Assessment)
            .where(
                Assessment.student_user_id == user.id,
                Assessment.kind == ASSESSMENT_CONTROL,
                Assessment.status == STATUS_GRADED,
                Assessment.assessed_on >= today - timedelta(days=9),
            )
            .order_by(Assessment.assessed_on.desc(), Assessment.id)
            .limit(2)
        ).scalars()
        for item in recent:
            moment = _past(now, item.assessed_on + CHECK_DELAY, time(14, 30))
            with clock.frozen(moment):
                notifications.notify(
                    user.id,
                    kind=NOTIFY_GRADE,
                    title=f"Новая оценка: {item.course.subject.name}",
                    body=f"{item.title} — {item.score} из 100.",
                    source_type=SOURCE_COURSE,
                    source_id=item.course_id,
                    dedupe_key=f"assessment:{item.id}",
                )


def seed_demo(
    passwords: dict[str, str], *, lessons_from: date | None = None, lessons_to: date | None = None
) -> dict:
    """Создать полный набор демо-данных в пустой базе. Транзакцию фиксирует вызывающий код."""
    now = clock.now()
    faculties, groups = _build_structure()
    teachers = {
        key: Teacher(full_name=full, short_name=short, title=title)
        for key, (full, short, title) in data.TEACHERS.items()
    }
    db.session.add_all(teachers.values())
    db.session.flush()

    courses = _build_courses(groups, teachers)
    lessons = _build_lessons(
        courses, lessons_from or data.TERM_AUTUMN["starts_on"], lessons_to or data.TERM_AUTUMN["ends_on"]
    )
    _build_deadlines(groups, courses)

    staff = _build_staff(passwords, faculties, teachers)
    students: dict[str, User] = {}
    for spec in data.STUDENTS:
        students[spec["key"]] = enroll_student(
            username=spec["username"],
            password=passwords[spec["key"]],
            full_name=spec["full_name"],
            group=groups[spec["group"]],
            record_book=spec["record_book"],
            base=spec["base"],
            spread=spec["spread"],
            offsets=spec["offsets"],
            final_overrides=spec["final_overrides"],
        )

    _build_announcements(now, faculties, groups, staff["dean"])
    _build_requests(now, students, staff["dean"])
    _build_grade_notifications(now, students)

    # Демо-уведомления старше двух суток отмечаются прочитанными.
    for item in db.session.execute(select(Notification)).scalars():
        if item.created_at < now - timedelta(days=2):
            item.read_at = item.created_at + timedelta(hours=3)

    refreshed = demo.refresh_demo_state()
    db.session.flush()
    return {
        "users": len(staff) + len(students),
        "lessons": lessons,
        "movedLessons": refreshed["movedLessons"],
        "deadlineReminders": refreshed["deadlineReminders"],
    }
