"""Кабинет деканата: заявки, расписание групп и объявления.

Сотрудник деканата видит и меняет только объекты своих факультетов (StaffScope).
Администратор работает в служебном режиме по всем факультетам.
Объект вне зоны ответственности неотличим от несуществующего (404).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, time, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from .. import clock
from ..errors import ApiError, forbidden, not_found, validation_error
from ..extensions import db
from ..models import (
    Announcement,
    Course,
    Faculty,
    Lesson,
    Program,
    RequestEvent,
    ServiceRequest,
    StudentProfile,
    StudyGroup,
    User,
)
from ..models.requests import FINAL_STATUSES, REQUEST_STATUS_LABELS, STATUS_SUBMITTED
from ..models.user import ROLE_ADMIN, ROLE_DEAN
from ..security.auth import current_user, roles_required
from ..services import audit, notifications
from ..services import requests as request_service
from ..services import schedule as schedule_service
from .auth import json_body

bp = Blueprint("staff", __name__, url_prefix="/api/staff")
staff_only = roles_required(ROLE_DEAN, ROLE_ADMIN)

PAGE_SIZE = 50
STALE_AFTER = timedelta(hours=24)


# ── Зона ответственности ──────────────────────────────────────────────────────


def scope_faculty_ids(user: User) -> set[int] | None:
    """Факультеты сотрудника; None — без ограничения (администратор)."""
    if user.role == ROLE_ADMIN:
        return None
    return user.staff.faculty_ids if user.staff else set()


def _in_scope(faculty_id: int, scope: set[int] | None) -> bool:
    return scope is None or faculty_id in scope


def _scoped(query, column, scope: set[int] | None):
    return query if scope is None else query.where(column.in_(scope or {-1}))


# ── Заявки ────────────────────────────────────────────────────────────────────


def _owner_payload(owner: User) -> dict:
    profile = owner.student
    group = profile.group
    return {
        "id": owner.id,
        "name": profile.full_name,
        "group": group.name,
        "year": group.year,
        "faculty": group.program.faculty.code,
        "program": group.program.name,
        "recordBook": profile.record_book,
    }


def _hours_open(item: ServiceRequest) -> int:
    end = item.updated_at if item.status in FINAL_STATUSES else clock.now()
    return max(0, int((end - item.created_at).total_seconds() // 3600))


def _staff_summary(item: ServiceRequest) -> dict:
    return {
        **request_service.serialize_summary(item),
        "owner": _owner_payload(item.owner),
        "hoursOpen": _hours_open(item),
        "isStale": item.status == STATUS_SUBMITTED and clock.now() - item.created_at > STALE_AFTER,
    }


def _owner_options():
    return (
        joinedload(ServiceRequest.owner)
        .joinedload(User.student)
        .joinedload(StudentProfile.group)
        .joinedload(StudyGroup.program)
        .joinedload(Program.faculty)
    )


def _get_scoped_request(request_id: int, user: User) -> ServiceRequest:
    item = db.session.execute(
        request_service._detail_query().options(_owner_options()).where(ServiceRequest.id == request_id)
    ).scalar_one_or_none()
    if item is None or not _in_scope(item.faculty_id, scope_faculty_ids(user)):
        raise not_found("Заявка не найдена.")
    return item


def _staff_detail(item: ServiceRequest, viewer: User) -> dict:
    return {
        **request_service.serialize_detail(item, viewer),
        "owner": _owner_payload(item.owner),
        "hoursOpen": _hours_open(item),
        "allowedTransitions": request_service.allowed_transitions(item.status),
        "canComment": item.status not in FINAL_STATUSES,
    }


@bp.get("/summary")
@staff_only
def summary():
    user = current_user()
    scope = scope_faculty_ids(user)
    rows = db.session.execute(
        _scoped(
            select(ServiceRequest.status, ServiceRequest.type, ServiceRequest.created_at),
            ServiceRequest.faculty_id,
            scope,
        )
    ).all()
    by_status = Counter(row.status for row in rows)
    now = clock.now()
    stale = sum(1 for row in rows if row.status == STATUS_SUBMITTED and now - row.created_at > STALE_AFTER)

    # Среднее время до решения — по фактическим событиям истории за 30 дней.
    decided = db.session.execute(
        _scoped(
            select(ServiceRequest.created_at, func.min(RequestEvent.created_at))
            .join(RequestEvent, RequestEvent.request_id == ServiceRequest.id)
            .where(
                RequestEvent.to_status.in_(FINAL_STATUSES),
                RequestEvent.created_at >= now - timedelta(days=30),
            )
            .group_by(ServiceRequest.id, ServiceRequest.created_at),
            ServiceRequest.faculty_id,
            scope,
        )
    ).all()
    hours = [(done - created).total_seconds() / 3600 for created, done in decided]
    by_type = Counter(row.type for row in rows if row.status not in FINAL_STATUSES)

    faculties = db.session.execute(_scoped(select(Faculty).order_by(Faculty.id), Faculty.id, scope)).scalars()
    return jsonify(
        {
            "counts": {status: by_status.get(status, 0) for status in REQUEST_STATUS_LABELS},
            "open": sum(count for status, count in by_status.items() if status not in FINAL_STATUSES),
            "stale": stale,
            "decidedLast30Days": len(hours),
            "averageDecisionHours": round(sum(hours) / len(hours), 1) if hours else None,
            "openByType": [
                {
                    "type": key,
                    "title": request_service.REQUEST_TYPES.get(key, {}).get("title", key),
                    "count": count,
                }
                for key, count in by_type.most_common()
            ],
            "faculties": [{"code": f.code, "name": f.name} for f in faculties],
            "explanation": "Время до решения — от подачи до первого итогового статуса за последние 30 дней.",
        }
    )


@bp.get("/requests")
@staff_only
def list_requests():
    user = current_user()
    scope = scope_faculty_ids(user)
    query = (
        select(ServiceRequest)
        .join(User, User.id == ServiceRequest.owner_user_id)
        .join(StudentProfile, StudentProfile.user_id == User.id)
        .options(_owner_options())
    )
    query = _scoped(query, ServiceRequest.faculty_id, scope)

    status = request.args.get("status", "open")
    if status == "open":
        query = query.where(ServiceRequest.status.notin_(FINAL_STATUSES))
    elif status in REQUEST_STATUS_LABELS:
        query = query.where(ServiceRequest.status == status)
    elif status != "all":
        raise validation_error({"status": "Неизвестный статус."})

    request_type = request.args.get("type")
    if request_type:
        if request_type not in request_service.REQUEST_TYPES:
            raise validation_error({"type": "Неизвестный тип заявки."})
        query = query.where(ServiceRequest.type == request_type)

    q = (request.args.get("q") or "").strip()[:80]
    if q:
        # Поиск по номеру, теме и ФИО; спецсимволы LIKE экранируются.
        pattern = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.where(
            or_(
                ServiceRequest.number.ilike(pattern, escape="\\"),
                ServiceRequest.title.ilike(pattern, escape="\\"),
                StudentProfile.full_name.ilike(pattern, escape="\\"),
            )
        )

    order = (
        ServiceRequest.created_at.asc()
        if request.args.get("sort") == "oldest"
        else ServiceRequest.created_at.desc()
    )
    items = list(
        db.session.execute(query.order_by(order, ServiceRequest.id.desc()).limit(PAGE_SIZE)).scalars()
    )
    return jsonify({"items": [_staff_summary(item) for item in items], "limit": PAGE_SIZE})


@bp.get("/requests/<int:request_id>")
@staff_only
def get_request(request_id: int):
    user = current_user()
    return jsonify({"request": _staff_detail(_get_scoped_request(request_id, user), user)})


@bp.post("/requests/<int:request_id>/transition")
@staff_only
def transition_request(request_id: int):
    user = current_user()
    item = _get_scoped_request(request_id, user)
    data = json_body()
    to_status = data.get("toStatus")
    if to_status not in REQUEST_STATUS_LABELS:
        raise validation_error({"toStatus": "Выберите новый статус."})
    before = item.status
    request_service.transition(item, actor=user, to_status=to_status, comment=data.get("comment"))
    audit.record(
        user, "request.transition", "request", item.id, before={"status": before}, after={"status": to_status}
    )
    db.session.commit()
    return jsonify({"request": _staff_detail(_get_scoped_request(request_id, user), user)})


@bp.post("/requests/<int:request_id>/comments")
@staff_only
def comment_request(request_id: int):
    user = current_user()
    item = _get_scoped_request(request_id, user)
    request_service.add_staff_comment(item, actor=user, comment=json_body().get("comment"))
    audit.record(user, "request.comment", "request", item.id)
    db.session.commit()
    return jsonify({"request": _staff_detail(_get_scoped_request(request_id, user), user)}), 201


# ── Расписание групп ──────────────────────────────────────────────────────────


def _scoped_groups(user: User) -> list[StudyGroup]:
    query = (
        select(StudyGroup)
        .join(Program, Program.id == StudyGroup.program_id)
        .options(joinedload(StudyGroup.program).joinedload(Program.faculty))
        .order_by(StudyGroup.name)
    )
    return list(db.session.execute(_scoped(query, Program.faculty_id, scope_faculty_ids(user))).scalars())


def _get_scoped_group(group_id: int, user: User) -> StudyGroup:
    group = next((g for g in _scoped_groups(user) if g.id == group_id), None)
    if group is None:
        raise not_found("Группа не найдена.")
    return group


@bp.get("/groups")
@staff_only
def groups():
    user = current_user()
    counts = dict(
        db.session.execute(
            select(StudentProfile.group_id, func.count())
            .join(User, User.id == StudentProfile.user_id)
            .where(User.is_active.is_(True))
            .group_by(StudentProfile.group_id)
        ).all()
    )
    return jsonify(
        {
            "items": [
                {
                    "id": g.id,
                    "name": g.name,
                    "year": g.year,
                    "faculty": g.program.faculty.code,
                    "program": g.program.name,
                    "students": counts.get(g.id, 0),
                }
                for g in _scoped_groups(user)
            ]
        }
    )


def _parse_date(raw: str | None, field: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise validation_error({field: "Дата должна быть в формате ГГГГ-ММ-ДД."}) from None


@bp.get("/schedule")
@staff_only
def group_schedule():
    user = current_user()
    try:
        group_id = int(request.args.get("group", ""))
    except ValueError:
        raise validation_error({"group": "Выберите группу."}) from None
    group = _get_scoped_group(group_id, user)
    today = clock.today()
    start = _parse_date(request.args.get("from"), "from") or clock.week_start(
        today + timedelta(days=1) if today.weekday() == 6 else today
    )
    end = start + timedelta(days=6)
    payload = schedule_service.group_week_payload(group.id, start, end)
    payload["group"] = {"id": group.id, "name": group.name}
    payload["pairSlots"] = [
        {"number": n, "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M")}
        for n, s, e in schedule_service.PAIR_SLOTS
    ]
    return jsonify(payload)


def _get_scoped_lesson(lesson_id: int, user: User) -> Lesson:
    lesson = db.session.execute(
        select(Lesson)
        .where(Lesson.id == lesson_id)
        .options(
            joinedload(Lesson.course).joinedload(Course.group).joinedload(StudyGroup.program),
            joinedload(Lesson.course).joinedload(Course.subject),
            joinedload(Lesson.teacher),
        )
    ).scalar_one_or_none()
    if lesson is None or not _in_scope(lesson.course.group.program.faculty_id, scope_faculty_ids(user)):
        raise not_found("Занятие не найдено.")
    return lesson


def _lesson_state(lesson: Lesson) -> dict:
    return {
        "status": lesson.status,
        "startsAt": clock.iso(lesson.starts_at),
        "endsAt": clock.iso(lesson.ends_at),
        "room": lesson.room,
    }


def _parse_time(raw: object, field: str) -> time:
    try:
        value = time.fromisoformat(str(raw))
    except ValueError:
        raise validation_error({field: "Время в формате ЧЧ:ММ."}) from None
    if not time(8, 0) <= value <= time(21, 0):
        raise validation_error({field: "Занятия проводятся с 08:00 до 21:00."})
    return value


@bp.patch("/lessons/<int:lesson_id>")
@staff_only
def change_lesson(lesson_id: int):
    """Перенос, отмена или возврат занятия. Занятие и уведомления группе — в одной транзакции."""
    user = current_user()
    lesson = _get_scoped_lesson(lesson_id, user)
    data = json_body()
    action = data.get("action")
    before = _lesson_state(lesson)
    reason = request_service.clean_text(data.get("reason"), 300)

    if action == "move":
        day = _parse_date(data.get("date"), "date")
        if day is None:
            raise validation_error({"date": "Укажите дату."})
        term_end = lesson.course.term.ends_on
        if not clock.today() <= day <= term_end:
            raise validation_error({"date": f"Дата — с сегодняшнего дня до {term_end.strftime('%d.%m.%Y')}."})
        if day.weekday() == 6:
            raise validation_error({"date": "В воскресенье занятий нет."})
        starts_at = clock.local_dt(day, _parse_time(data.get("startTime"), "startTime"))
        ends_at = clock.local_dt(day, _parse_time(data.get("endTime"), "endTime"))
        if not timedelta(minutes=30) <= ends_at - starts_at <= timedelta(hours=4):
            raise validation_error({"endTime": "Длительность занятия — от 30 минут до 4 часов."})
        schedule_service.reschedule_lesson(
            lesson,
            starts_at=starts_at,
            ends_at=ends_at,
            room=data.get("room") or "",
            reason=reason,
            actor=user,
        )
    elif action == "cancel":
        if len(reason) < 5:
            raise validation_error({"reason": "Укажите причину отмены — студенты увидят её в уведомлении."})
        schedule_service.cancel_lesson(lesson, reason=reason, actor=user)
    elif action == "restore":
        schedule_service.restore_lesson(lesson, actor=user)
    else:
        raise validation_error({"action": "Неизвестное действие."})

    audit.record(user, f"lesson.{action}", "lesson", lesson.id, before=before, after=_lesson_state(lesson))
    recipients = len(notifications.group_student_ids(lesson.course.group_id))
    db.session.commit()
    return jsonify({"lesson": schedule_service.serialize_lesson(lesson), "notified": recipients})


# ── Объявления ────────────────────────────────────────────────────────────────


def _audience_label(item: Announcement) -> str:
    if item.group is not None:
        return f"Группа {item.group.name}"
    if item.faculty is not None:
        return item.faculty.name
    return "Все студенты"


def _announcement_payload(item: Announcement) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "body": item.body,
        "publishedAt": clock.iso(item.published_at),
        "audience": _audience_label(item),
        "author": item.author.full_name if item.author else "Деканат",
    }


@bp.get("/announcements")
@staff_only
def list_announcements():
    user = current_user()
    scope = scope_faculty_ids(user)
    query = select(Announcement).options(
        joinedload(Announcement.group).joinedload(StudyGroup.program),
        joinedload(Announcement.faculty),
        joinedload(Announcement.author),
    )
    if scope is not None:
        group_ids = [g.id for g in _scoped_groups(user)]
        query = query.where(
            or_(
                Announcement.faculty_id.in_(scope or {-1}),
                Announcement.group_id.in_(group_ids or [-1]),
                (Announcement.faculty_id.is_(None) & Announcement.group_id.is_(None)),
            )
        )
    items = db.session.execute(query.order_by(Announcement.published_at.desc()).limit(100)).scalars()
    return jsonify({"items": [_announcement_payload(item) for item in items]})


@bp.post("/announcements")
@staff_only
def create_announcement():
    user = current_user()
    scope = scope_faculty_ids(user)
    data = json_body()
    title = request_service.clean_text(data.get("title"), 200)
    body = request_service.clean_text(data.get("body"), 4000)
    errors = {}
    if len(title) < 5:
        errors["title"] = "Заголовок — от 5 символов."
    elif len(title) > 200:
        errors["title"] = "Заголовок — не длиннее 200 символов."
    if len(body) < 10:
        errors["body"] = "Текст — от 10 символов."
    elif len(body) > 4000:
        errors["body"] = "Текст — не длиннее 4000 символов."

    item = Announcement(author_user_id=user.id, title=title, body=body, published_at=clock.now())
    audience = data.get("audience")
    if audience == "all":
        if scope is not None:
            raise forbidden()
    elif audience == "faculty":
        faculty = db.session.execute(
            select(Faculty).where(Faculty.code == data.get("faculty"))
        ).scalar_one_or_none()
        if faculty is None or not _in_scope(faculty.id, scope):
            errors["faculty"] = "Выберите факультет из своей зоны."
        else:
            item.faculty_id = faculty.id
    elif audience == "group":
        try:
            item.group_id = _get_scoped_group(int(data.get("groupId")), user).id
        except (TypeError, ValueError, ApiError):
            errors["groupId"] = "Выберите группу из своей зоны."
    else:
        errors["audience"] = "Выберите, кому адресовано объявление."
    if errors:
        raise validation_error(errors)

    db.session.add(item)
    db.session.flush()
    recipients = notifications.notify_announcement(item)
    audit.record(
        user, "announcement.create", "announcement", item.id, after={"title": title, "audience": audience}
    )
    db.session.commit()
    db.session.refresh(item)
    return jsonify({"announcement": _announcement_payload(item), "notified": recipients}), 201
