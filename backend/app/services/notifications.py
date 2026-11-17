"""Уведомления внутри кабинета.

Создаются только сервером из реальных событий (перенос, объявление, статус заявки, оценка,
дедлайн). При выдаче текст уведомлений о занятиях и объявлениях собирается из текущего
состояния источника, а ссылка ведёт на сам объект.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func, select, update
from sqlalchemy.orm import joinedload

from .. import clock
from ..errors import not_found
from ..extensions import db
from ..models import (
    Announcement,
    Course,
    Deadline,
    Lesson,
    Notification,
    Program,
    ServiceRequest,
    StudentProfile,
    StudyGroup,
    User,
)
from ..models.comms import (
    NOTIFICATION_KIND_LABELS,
    NOTIFY_ANNOUNCEMENT,
    NOTIFY_LESSON_CHANGE,
    SOURCE_ANNOUNCEMENT,
    SOURCE_COURSE,
    SOURCE_DEADLINE,
    SOURCE_LESSON,
    SOURCE_REQUEST,
)

EXCERPT_LENGTH = 220


def notify(
    recipient_user_id: int,
    *,
    kind: str,
    title: str,
    body: str = "",
    source_type: str | None = None,
    source_id: int | None = None,
    dedupe_key: str | None = None,
) -> Notification:
    """Создать уведомление.

    С dedupe_key повторное событие «поднимает» старое уведомление, а не плодит дубли.
    """
    if dedupe_key:
        existing = db.session.execute(
            select(Notification).where(
                Notification.recipient_user_id == recipient_user_id, Notification.dedupe_key == dedupe_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.title, existing.body = title[:200], body
            existing.created_at = clock.now()
            existing.read_at = None
            return existing
    item = Notification(
        recipient_user_id=recipient_user_id,
        kind=kind,
        title=title[:200],
        body=body,
        source_type=source_type,
        source_id=source_id,
        dedupe_key=dedupe_key,
        created_at=clock.now(),
    )
    db.session.add(item)
    return item


def group_student_ids(group_id: int) -> list[int]:
    return list(
        db.session.execute(
            select(StudentProfile.user_id)
            .join(StudentProfile.user)
            .where(StudentProfile.group_id == group_id, User.is_active.is_(True))
        ).scalars()
    )


def announcement_recipient_ids(announcement: Announcement) -> list[int]:
    query = select(StudentProfile.user_id).join(StudentProfile.user).where(User.is_active.is_(True))
    if announcement.group_id is not None:
        query = query.where(StudentProfile.group_id == announcement.group_id)
    elif announcement.faculty_id is not None:
        query = (
            query.join(StudyGroup, StudyGroup.id == StudentProfile.group_id)
            .join(Program, Program.id == StudyGroup.program_id)
            .where(Program.faculty_id == announcement.faculty_id)
        )
    return list(db.session.execute(query).scalars())


def announcement_visible_to(announcement: Announcement, student: User) -> bool:
    group = student.student.group
    if announcement.group_id is not None:
        return announcement.group_id == group.id
    if announcement.faculty_id is not None:
        return announcement.faculty_id == group.program.faculty_id
    return True


def notify_lesson_change(lesson: Lesson) -> int:
    """Одно уведомление о занятии на студента; при повторном изменении оно обновляется."""
    from .schedule import change_text, change_title

    title, body = change_title(lesson), change_text(lesson)
    recipients = group_student_ids(lesson.course.group_id)
    for user_id in recipients:
        notify(
            user_id,
            kind=NOTIFY_LESSON_CHANGE,
            title=title,
            body=body,
            source_type=SOURCE_LESSON,
            source_id=lesson.id,
            dedupe_key=f"lesson:{lesson.id}",
        )
    return len(recipients)


def notify_announcement(announcement: Announcement) -> int:
    recipients = announcement_recipient_ids(announcement)
    for user_id in recipients:
        notify(
            user_id,
            kind=NOTIFY_ANNOUNCEMENT,
            title=announcement.title,
            body=_excerpt(announcement.body),
            source_type=SOURCE_ANNOUNCEMENT,
            source_id=announcement.id,
            dedupe_key=f"announcement:{announcement.id}",
        )
    return len(recipients)


def _excerpt(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= EXCERPT_LENGTH else text[: EXCERPT_LENGTH - 1].rstrip() + "…"


def unread_count(user_id: int) -> int:
    return db.session.execute(
        select(func.count())
        .select_from(Notification)
        .where(Notification.recipient_user_id == user_id, Notification.read_at.is_(None))
    ).scalar_one()


def list_for_user(user_id: int, *, limit: int = 100, unread_only: bool = False) -> list[Notification]:
    query = select(Notification).where(Notification.recipient_user_id == user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    return list(
        db.session.execute(
            query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
        ).scalars()
    )


def mark_read(user_id: int, notification_id: int) -> Notification:
    item = db.session.execute(
        select(Notification).where(
            Notification.id == notification_id, Notification.recipient_user_id == user_id
        )
    ).scalar_one_or_none()
    if item is None:
        raise not_found("Уведомление не найдено.")
    if item.read_at is None:
        item.read_at = clock.now()
    return item


def mark_all_read(user_id: int) -> int:
    result = db.session.execute(
        update(Notification)
        .where(Notification.recipient_user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=clock.now())
    )
    return result.rowcount or 0


def _load_sources(items: list[Notification]) -> dict[tuple[str, int], object]:
    """Подгружаем объекты-источники пачками, без запроса на каждое уведомление."""
    ids: dict[str, set[int]] = defaultdict(set)
    for item in items:
        if item.source_type and item.source_id:
            ids[item.source_type].add(item.source_id)
    found: dict[tuple[str, int], object] = {}
    if ids.get(SOURCE_LESSON):
        rows = db.session.execute(
            select(Lesson)
            .where(Lesson.id.in_(ids[SOURCE_LESSON]))
            .options(joinedload(Lesson.course).joinedload(Course.subject), joinedload(Lesson.teacher))
        ).scalars()
        found.update({(SOURCE_LESSON, row.id): row for row in rows})
    for source, model in (
        (SOURCE_ANNOUNCEMENT, Announcement),
        (SOURCE_DEADLINE, Deadline),
        (SOURCE_REQUEST, ServiceRequest),
    ):
        if ids.get(source):
            rows = db.session.execute(select(model).where(model.id.in_(ids[source]))).scalars()
            found.update({(source, row.id): row for row in rows})
    return found


def serialize_many(items: list[Notification]) -> list[dict]:
    from .schedule import change_text, change_title, serialize_lesson

    sources = _load_sources(items)
    result = []
    for item in items:
        source = sources.get((item.source_type, item.source_id)) if item.source_type else None
        payload = {
            "id": item.id,
            "kind": item.kind,
            "kindLabel": NOTIFICATION_KIND_LABELS.get(item.kind, "Сообщение"),
            "title": item.title,
            "body": item.body,
            "createdAt": clock.iso(item.created_at),
            "read": item.read_at is not None,
            "link": None,
        }
        if item.source_type == SOURCE_LESSON and isinstance(source, Lesson):
            # Текст и вложенное занятие берутся из той же строки, что и расписание.
            payload["title"] = change_title(source)
            payload["body"] = change_text(source)
            payload["lesson"] = serialize_lesson(source)
            payload["link"] = {
                "type": "lesson",
                "id": source.id,
                "date": clock.to_local(source.starts_at).date().isoformat(),
            }
        elif item.source_type == SOURCE_ANNOUNCEMENT and isinstance(source, Announcement):
            payload["title"] = source.title
            payload["body"] = _excerpt(source.body)
            payload["link"] = {"type": "announcement", "id": source.id}
        elif item.source_type == SOURCE_DEADLINE and isinstance(source, Deadline):
            payload["link"] = {
                "type": "deadline",
                "id": source.id,
                "date": clock.to_local(source.due_at).date().isoformat(),
            }
        elif item.source_type == SOURCE_REQUEST and isinstance(source, ServiceRequest):
            payload["link"] = {"type": "request", "id": source.id}
        elif item.source_type == SOURCE_COURSE and item.source_id:
            payload["link"] = {"type": "grades", "courseId": item.source_id}
        result.append(payload)
    return result
