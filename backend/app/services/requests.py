"""Заявки и справки: типы, проверка формы, создание, история и смена статуса.

Описание типов заявок хранится в одном месте (REQUEST_TYPES): по нему сервер проверяет форму,
а интерфейс получает его через /api/meta/request-types и рисует поля.
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from .. import clock
from ..errors import ApiError, not_found, validation_error
from ..extensions import db
from ..models import RequestEvent, ServiceRequest, User
from ..models.comms import NOTIFY_REQUEST, SOURCE_REQUEST
from ..models.requests import (
    EVENT_COMMENT,
    EVENT_CREATED,
    EVENT_STATUS,
    FINAL_STATUSES,
    REQUEST_STATUS_LABELS,
    STATUS_APPROVED,
    STATUS_IN_REVIEW,
    STATUS_NEEDS_INFO,
    STATUS_REJECTED,
    STATUS_SUBMITTED,
)
from ..models.user import ROLE_LABELS, ROLE_STUDENT
from . import notifications

COMMENT_MAX = 1000
MAX_OPEN_REQUESTS = 20  # защита демо-стенда от засорения

DELIVERY_OPTIONS = [
    {"value": "office", "label": "Забрать в деканате"},
    {"value": "electronic", "label": "Электронная копия в кабинете"},
]
COPIES_FIELD = {"key": "copies", "label": "Количество экземпляров", "kind": "number", "min": 1, "max": 5,
                "default": 1, "required": True}  # fmt: skip
DELIVERY_FIELD = {"key": "delivery", "label": "Способ получения", "kind": "select",
                  "options": DELIVERY_OPTIONS, "default": "office", "required": True}  # fmt: skip

REQUEST_TYPES: dict[str, dict] = {
    "study_certificate": {
        "title": "Справка об обучении",
        "description": "Подтверждает, что вы учитесь в университете: для работы, банка, визы, военкомата.",
        "eta": "обычно 2–3 рабочих дня",
        "commentRequired": False,
        "fields": [
            {
                "key": "purpose",
                "label": "Куда предоставляется",
                "kind": "select",
                "required": True,
                "options": [
                    {"value": "employer", "label": "По месту работы"},
                    {"value": "bank", "label": "В банк"},
                    {"value": "visa", "label": "Для оформления визы"},
                    {"value": "military", "label": "В военкомат"},
                    {"value": "social", "label": "В Социальный фонд"},
                    {"value": "other", "label": "По месту требования"},
                ],
            },  # fmt: skip
            COPIES_FIELD,
            DELIVERY_FIELD,
        ],
    },
    "transcript": {
        "title": "Справка об успеваемости",
        "description": "Выписка с оценками и зачётами за выбранный период.",
        "eta": "обычно 3–5 рабочих дней",
        "commentRequired": False,
        "fields": [
            {
                "key": "period",
                "label": "Период",
                "kind": "select",
                "required": True,
                "options": [
                    {"value": "last_term", "label": "Последний завершённый семестр"},
                    {"value": "last_year", "label": "Последний учебный год"},
                    {"value": "all", "label": "Весь период обучения"},
                ],
            },  # fmt: skip
            COPIES_FIELD,
            DELIVERY_FIELD,
        ],
    },
    "absence": {
        "title": "Заявление о пропуске занятий",
        "description": "Сообщите деканату о пропуске по уважительной причине и приложите подтверждение.",
        "eta": "обычно 1–2 рабочих дня",
        "commentRequired": False,
        "fields": [
            {"key": "date_from", "label": "Первый день пропуска", "kind": "date", "required": True},
            {"key": "date_to", "label": "Последний день пропуска", "kind": "date", "required": True},
            {
                "key": "reason",
                "label": "Причина",
                "kind": "select",
                "required": True,
                "options": [
                    {"value": "illness", "label": "Болезнь"},
                    {"value": "family", "label": "Семейные обстоятельства"},
                    {"value": "event", "label": "Олимпиада, конференция, соревнования"},
                    {"value": "other", "label": "Другая причина"},
                ],
            },  # fmt: skip
        ],
    },
    "retake": {
        "title": "Заявление на пересдачу",
        "description": "Запрос на пересдачу экзамена или зачёта в дополнительный срок.",
        "eta": "обычно 3–5 рабочих дней",
        "commentRequired": True,
        "fields": [
            {"key": "subject", "label": "Дисциплина", "kind": "text", "required": True, "maxLength": 120},
        ],
    },
    "free_form": {
        "title": "Обращение в деканат",
        "description": "Вопрос или просьба в свободной форме.",
        "eta": "обычно до 5 рабочих дней",
        "commentRequired": True,
        "fields": [
            {"key": "subject", "label": "Тема обращения", "kind": "text", "required": True, "maxLength": 120},
        ],
    },
}

# Разрешённые переходы статуса для сотрудника деканата.
STAFF_TRANSITIONS: dict[str, tuple[str, ...]] = {
    STATUS_SUBMITTED: (STATUS_IN_REVIEW,),
    STATUS_IN_REVIEW: (STATUS_APPROVED, STATUS_REJECTED, STATUS_NEEDS_INFO),
    STATUS_NEEDS_INFO: (STATUS_IN_REVIEW,),
}
# Для этих переходов сотрудник обязан написать комментарий студенту.
COMMENT_REQUIRED_FOR = (STATUS_REJECTED, STATUS_NEEDS_INFO)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def types_payload() -> list[dict]:
    return [{"type": key, **spec} for key, spec in REQUEST_TYPES.items()]


def clean_text(value: object, max_length: int) -> str:
    """Обрезаем пробелы и управляющие символы. HTML не интерпретируется: React выводит текст как текст."""
    if not isinstance(value, str):
        return ""
    return _CONTROL_CHARS.sub("", value).strip()[: max_length + 1]


def _validate_fields(spec: dict, raw: object) -> tuple[dict, dict[str, str]]:
    raw = raw if isinstance(raw, dict) else {}
    clean: dict = {}
    errors: dict[str, str] = {}
    for field in spec["fields"]:
        key, kind = field["key"], field["kind"]
        value = raw.get(key, field.get("default"))
        if value is None or value == "":
            if field.get("required"):
                errors[key] = "Заполните это поле."
            continue
        if kind == "select":
            allowed = {option["value"] for option in field["options"]}
            if value not in allowed:
                errors[key] = "Выберите вариант из списка."
            else:
                clean[key] = value
        elif kind == "number":
            if isinstance(value, bool) or not isinstance(value, int | str):
                errors[key] = "Введите целое число."
                continue
            try:
                number = int(value)
            except ValueError:
                errors[key] = "Введите целое число."
                continue
            if not field["min"] <= number <= field["max"]:
                errors[key] = f"Допустимо от {field['min']} до {field['max']}."
            else:
                clean[key] = number
        elif kind == "date":
            try:
                clean[key] = date.fromisoformat(str(value)).isoformat()
            except ValueError:
                errors[key] = "Укажите дату."
        else:  # text
            text = clean_text(value, field["maxLength"])
            if not text:
                if field.get("required"):
                    errors[key] = "Заполните это поле."
            elif len(text) > field["maxLength"]:
                errors[key] = f"Не длиннее {field['maxLength']} символов."
            else:
                clean[key] = text
    return clean, errors


def _cross_checks(request_type: str, clean: dict, errors: dict[str, str]) -> None:
    if request_type == "absence" and "date_from" in clean and "date_to" in clean:
        start, end = date.fromisoformat(clean["date_from"]), date.fromisoformat(clean["date_to"])
        if end < start:
            errors["date_to"] = "Последний день не может быть раньше первого."
        elif (end - start).days > 60:
            errors["date_to"] = "Период пропуска — не больше 60 дней."
        if abs((start - clock.today()).days) > 180:
            errors["date_from"] = "Дата слишком далеко от сегодняшней."


def _title_for(request_type: str, clean: dict) -> str:
    spec = REQUEST_TYPES[request_type]
    if request_type in ("free_form", "retake") and clean.get("subject"):
        return f"{spec['title']}: {clean['subject']}"[:200]
    return spec["title"]


def details_payload(item: ServiceRequest) -> list[dict]:
    """Поля заявки в виде «подпись — значение» для показа человеку."""
    spec = REQUEST_TYPES.get(item.type)
    if spec is None:
        return []
    rows = []
    for field in spec["fields"]:
        value = item.fields.get(field["key"])
        if value is None:
            continue
        if field["kind"] == "select":
            value = next((o["label"] for o in field["options"] if o["value"] == value), value)
        elif field["kind"] == "date":
            value = clock.human_date(date.fromisoformat(value), with_weekday=False) + f" {value[:4]}"
        rows.append({"key": field["key"], "label": field["label"], "value": str(value)})
    return rows


def create_request(
    owner: User, payload: object, client_token: str | None = None
) -> tuple[ServiceRequest, bool]:
    """Создать заявку от имени вошедшего студента. Возвращает (заявка, создана_ли_сейчас)."""
    payload = payload if isinstance(payload, dict) else {}
    request_type = payload.get("type")
    if request_type not in REQUEST_TYPES:
        raise validation_error({"type": "Выберите тип заявки."})
    spec = REQUEST_TYPES[request_type]

    if client_token is not None and not _TOKEN_RE.match(client_token):
        client_token = None
    if client_token:
        existing = db.session.execute(
            select(ServiceRequest).where(
                ServiceRequest.owner_user_id == owner.id, ServiceRequest.client_token == client_token
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False

    clean, errors = _validate_fields(spec, payload.get("fields"))
    _cross_checks(request_type, clean, errors)
    comment = clean_text(payload.get("comment"), COMMENT_MAX)
    if len(comment) > COMMENT_MAX:
        errors["comment"] = f"Комментарий — не длиннее {COMMENT_MAX} символов."
    elif spec["commentRequired"] and len(comment) < 10:
        errors["comment"] = "Опишите ситуацию подробнее (от 10 символов)."
    if errors:
        raise validation_error(errors)

    open_count = len(
        db.session.execute(
            select(ServiceRequest.id).where(
                ServiceRequest.owner_user_id == owner.id, ServiceRequest.status.notin_(FINAL_STATUSES)
            )
        ).all()
    )
    if open_count >= MAX_OPEN_REQUESTS:
        raise ApiError(
            409, "too_many_open_requests", "Слишком много заявок в работе. Дождитесь ответа по текущим."
        )

    now = clock.now()
    item = ServiceRequest(
        owner_user_id=owner.id,
        faculty_id=owner.student.group.program.faculty_id,
        type=request_type,
        title=_title_for(request_type, clean),
        fields=clean,
        comment=comment or None,
        status=STATUS_SUBMITTED,
        client_token=client_token,
        created_at=now,
        updated_at=now,
    )
    item.events.append(
        RequestEvent(actor_user_id=owner.id, kind=EVENT_CREATED, to_status=STATUS_SUBMITTED, created_at=now)
    )
    db.session.add(item)
    try:
        db.session.flush()
    except IntegrityError:
        # Два одинаковых запроса пришли одновременно: отдаём уже созданную заявку.
        db.session.rollback()
        existing = db.session.execute(
            select(ServiceRequest).where(
                ServiceRequest.owner_user_id == owner.id, ServiceRequest.client_token == client_token
            )
        ).scalar_one()
        return existing, False
    item.number = f"MC-{clock.to_local(now).year}-{item.id:05d}"
    return item, True


def _detail_query():
    return select(ServiceRequest).options(
        selectinload(ServiceRequest.events).joinedload(RequestEvent.actor),
        selectinload(ServiceRequest.attachments),
        joinedload(ServiceRequest.owner),
    )


def list_owned(owner: User) -> list[ServiceRequest]:
    return list(
        db.session.execute(
            select(ServiceRequest)
            .where(ServiceRequest.owner_user_id == owner.id)
            .order_by(ServiceRequest.created_at.desc(), ServiceRequest.id.desc())
        ).scalars()
    )


def get_owned(owner: User, request_id: int) -> ServiceRequest:
    """Заявка по номеру — только своя. Чужая неотличима от несуществующей (404)."""
    item = db.session.execute(
        _detail_query().where(ServiceRequest.id == request_id, ServiceRequest.owner_user_id == owner.id)
    ).scalar_one_or_none()
    if item is None:
        raise not_found("Заявка не найдена.")
    return item


def _notify_owner(item: ServiceRequest, title: str, body: str) -> None:
    notifications.notify(
        item.owner_user_id,
        kind=NOTIFY_REQUEST,
        title=title,
        body=body,
        source_type=SOURCE_REQUEST,
        source_id=item.id,
    )


def transition(item: ServiceRequest, *, actor: User, to_status: str, comment: str | None) -> ServiceRequest:
    """Смена статуса сотрудником. Событие истории и уведомление студенту — в той же транзакции."""
    allowed = STAFF_TRANSITIONS.get(item.status, ())
    if to_status not in allowed:
        raise ApiError(
            409,
            "invalid_transition",
            f"Из статуса «{REQUEST_STATUS_LABELS[item.status]}» такой переход невозможен.",
        )
    text = clean_text(comment, COMMENT_MAX)
    if len(text) > COMMENT_MAX:
        raise validation_error({"comment": f"Комментарий — не длиннее {COMMENT_MAX} символов."})
    if to_status in COMMENT_REQUIRED_FOR and len(text) < 5:
        raise validation_error({"comment": "Напишите студенту, что именно нужно или почему отказано."})

    now = clock.now()
    previous = item.status
    item.status = to_status
    item.updated_at = now
    if item.assigned_staff_id is None:
        item.assigned_staff_id = actor.id
    item.events.append(
        RequestEvent(
            actor_user_id=actor.id,
            kind=EVENT_STATUS,
            from_status=previous,
            to_status=to_status,
            comment=text or None,
            created_at=now,
        )
    )
    label = REQUEST_STATUS_LABELS[to_status].lower()
    _notify_owner(item, f"Заявка {item.number}: {label}", text or f"{item.title} — статус: {label}.")
    return item


def add_student_comment(item: ServiceRequest, *, actor: User, comment: object) -> ServiceRequest:
    """Комментарий студента. Ответ на «требует уточнения» возвращает заявку на рассмотрение."""
    if item.status in FINAL_STATUSES:
        raise ApiError(409, "request_closed", "Заявка закрыта, добавить комментарий нельзя.")
    text = clean_text(comment, COMMENT_MAX)
    if not text:
        raise validation_error({"comment": "Напишите комментарий."})
    if len(text) > COMMENT_MAX:
        raise validation_error({"comment": f"Комментарий — не длиннее {COMMENT_MAX} символов."})
    now = clock.now()
    if item.status == STATUS_NEEDS_INFO:
        item.events.append(
            RequestEvent(
                actor_user_id=actor.id,
                kind=EVENT_STATUS,
                from_status=STATUS_NEEDS_INFO,
                to_status=STATUS_IN_REVIEW,
                comment=text,
                created_at=now,
            )
        )
        item.status = STATUS_IN_REVIEW
    else:
        item.events.append(
            RequestEvent(actor_user_id=actor.id, kind=EVENT_COMMENT, comment=text, created_at=now)
        )
    item.updated_at = now
    return item


def add_staff_comment(item: ServiceRequest, *, actor: User, comment: object) -> ServiceRequest:
    """Комментарий сотрудника студенту без смены статуса (например, уточнение срока)."""
    if item.status in FINAL_STATUSES:
        raise ApiError(409, "request_closed", "Заявка закрыта, добавить комментарий нельзя.")
    text = clean_text(comment, COMMENT_MAX)
    if not text:
        raise validation_error({"comment": "Напишите комментарий."})
    if len(text) > COMMENT_MAX:
        raise validation_error({"comment": f"Комментарий — не длиннее {COMMENT_MAX} символов."})
    now = clock.now()
    item.events.append(RequestEvent(actor_user_id=actor.id, kind=EVENT_COMMENT, comment=text, created_at=now))
    item.updated_at = now
    if item.assigned_staff_id is None:
        item.assigned_staff_id = actor.id
    _notify_owner(item, f"Заявка {item.number}: комментарий деканата", text)
    return item


def allowed_transitions(status: str) -> list[dict]:
    return [
        {
            "status": target,
            "label": REQUEST_STATUS_LABELS[target],
            "commentRequired": target in COMMENT_REQUIRED_FOR,
        }
        for target in STAFF_TRANSITIONS.get(status, ())
    ]


def _status_payload(status: str) -> dict:
    return {
        "status": status,
        "statusLabel": REQUEST_STATUS_LABELS[status],
        "isFinal": status in FINAL_STATUSES,
    }


def serialize_summary(item: ServiceRequest) -> dict:
    return {
        "id": item.id,
        "number": item.number,
        "type": item.type,
        "typeTitle": REQUEST_TYPES.get(item.type, {}).get("title", item.type),
        "title": item.title,
        **_status_payload(item.status),
        "createdAt": clock.iso(item.created_at),
        "updatedAt": clock.iso(item.updated_at),
    }


def _actor_payload(event: RequestEvent, viewer: User) -> dict:
    actor = event.actor
    if actor is None:
        return {"role": "system", "label": "Система", "isMe": False}
    if actor.role == ROLE_STUDENT:
        return {"role": actor.role, "label": actor.full_name, "isMe": actor.id == viewer.id}
    # Студенту показываем должность и имя сотрудника, но не его логин.
    return {
        "role": actor.role,
        "label": f"{ROLE_LABELS[actor.role]} · {actor.full_name}",
        "isMe": actor.id == viewer.id,
    }


def serialize_event(event: RequestEvent, viewer: User) -> dict:
    return {
        "id": event.id,
        "kind": event.kind,
        "fromStatus": event.from_status,
        "toStatus": event.to_status,
        "toStatusLabel": REQUEST_STATUS_LABELS.get(event.to_status) if event.to_status else None,
        "comment": event.comment,
        "actor": _actor_payload(event, viewer),
        "createdAt": clock.iso(event.created_at),
    }


def serialize_detail(item: ServiceRequest, viewer: User) -> dict:
    spec = REQUEST_TYPES.get(item.type, {})
    return {
        **serialize_summary(item),
        "description": spec.get("description"),
        "eta": spec.get("eta"),
        "details": details_payload(item),
        "comment": item.comment,
        "events": [serialize_event(event, viewer) for event in item.events],
        "attachments": [
            {
                "id": a.id,
                "name": a.display_name,
                "mediaType": a.media_type,
                "sizeBytes": a.size_bytes,
                "createdAt": clock.iso(a.created_at),
            }
            for a in item.attachments
        ],
        "canComment": item.status not in FINAL_STATUSES,
        "steps": progress_steps(item.status),
    }


def progress_steps(status: str) -> list[dict]:
    """Три понятных шага для индикатора прогресса."""
    order = [STATUS_SUBMITTED, STATUS_IN_REVIEW, "decision"]
    labels = {STATUS_SUBMITTED: "Создана", STATUS_IN_REVIEW: "На рассмотрении", "decision": "Решение"}
    reached = {
        STATUS_SUBMITTED: 1,
        STATUS_IN_REVIEW: 2,
        STATUS_NEEDS_INFO: 2,
        STATUS_APPROVED: 3,
        STATUS_REJECTED: 3,
    }[status]
    steps = [{"key": key, "label": labels[key], "done": index < reached} for index, key in enumerate(order)]
    if status in FINAL_STATUSES:
        steps[-1]["label"] = REQUEST_STATUS_LABELS[status]
    if status == STATUS_NEEDS_INFO:
        steps[1]["label"] = REQUEST_STATUS_LABELS[status]
    return steps
