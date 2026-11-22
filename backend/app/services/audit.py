"""Журнал действий сотрудников: кто, что и когда изменил.

Пароли, токены и содержимое файлов сюда не пишутся — только служебные поля «было/стало».
"""

from __future__ import annotations

from flask import g, has_request_context
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from .. import clock
from ..extensions import db
from ..models import AuditEvent, User

ACTION_LABELS = {
    "request.transition": "Смена статуса заявки",
    "request.comment": "Комментарий к заявке",
    "lesson.move": "Перенос занятия",
    "lesson.cancel": "Отмена занятия",
    "lesson.restore": "Возврат занятия в расписание",
    "announcement.create": "Объявление",
    "assessment.update": "Изменение оценки",
    "user.activate": "Включение аккаунта",
    "user.deactivate": "Отключение аккаунта",
}


def record(
    actor: User | None,
    action: str,
    entity_type: str,
    entity_id: int | None,
    *,
    before: dict | None = None,
    after: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        request_id=g.get("request_id") if has_request_context() else None,
        created_at=clock.now(),
    )
    db.session.add(event)
    return event


def recent(limit: int = 100) -> list[dict]:
    rows = db.session.execute(
        select(AuditEvent, User)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .options(joinedload(User.staff), joinedload(User.student))
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": event.id,
            "action": event.action,
            "actionLabel": ACTION_LABELS.get(event.action, event.action),
            "entityType": event.entity_type,
            "entityId": event.entity_id,
            "before": event.before,
            "after": event.after,
            "actor": {"name": actor.full_name, "role": actor.role}
            if actor
            else {"name": "Система", "role": "system"},
            "createdAt": clock.iso(event.created_at),
        }
        for event, actor in rows
    ]
