"""Заявки: создание, проверка формы, сохранение в Postgres, история и статусы."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.extensions import db
from app.models import Notification, RequestEvent, ServiceRequest, User
from app.services import requests as request_service
from tests.conftest import VALID_CERTIFICATE, Api


def _count_requests(app) -> int:
    with app.app_context():
        return db.session.execute(select(func.count()).select_from(ServiceRequest)).scalar_one()


def test_request_types_describe_forms(mira):
    items = mira.get("/api/meta/request-types").get_json()["items"]
    assert {i["type"] for i in items} == {"study_certificate", "transcript", "absence", "retake", "free_form"}
    certificate = next(i for i in items if i["type"] == "study_certificate")
    assert certificate["title"] == "Справка об обучении"
    assert [f["key"] for f in certificate["fields"]] == ["purpose", "copies", "delivery"]


def test_student_creates_certificate_request(app, mira):
    before = _count_requests(app)
    response = mira.post("/api/me/requests", json=VALID_CERTIFICATE)
    assert response.status_code == 201
    body = response.get_json()
    created = body["request"]
    assert body["created"] is True
    assert created["status"] == "submitted" and created["statusLabel"] == "Создана"
    assert created["title"] == "Справка об обучении"
    assert created["number"] == f"MC-2026-{created['id']:05d}"
    assert created["comment"] == "Нужна для открытия счёта."
    assert {"label": "Количество экземпляров", "value": "2", "key": "copies"} in created["details"]
    assert {"label": "Куда предоставляется", "value": "В банк", "key": "purpose"} in created["details"]
    assert [e["kind"] for e in created["events"]] == ["created"]
    assert created["events"][0]["actor"]["isMe"] is True
    assert [s["done"] for s in created["steps"]] == [True, False, False]
    assert _count_requests(app) == before + 1

    listed = mira.get("/api/me/requests").get_json()["items"]
    assert listed[0]["id"] == created["id"]  # новая заявка — первая в списке
    assert mira.get("/api/me/dashboard").get_json()["activeRequest"]["id"] == created["id"]


def test_request_survives_refresh_and_relogin(app, mira):
    """Заявка лежит в Postgres, а не в памяти браузера: видна после выхода, входа и с другого устройства."""
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]

    # «Обновление страницы» — повторные запросы той же сессии.
    assert mira.get(f"/api/me/requests/{created['id']}").get_json()["request"]["number"] == created["number"]

    assert mira.logout().status_code == 200
    assert mira.get(f"/api/me/requests/{created['id']}").status_code == 401
    assert mira.login("student1").status_code == 200
    again = mira.get(f"/api/me/requests/{created['id']}").get_json()["request"]
    assert again["status"] == "submitted" and again["details"] == created["details"]

    other_device = Api(app)
    assert other_device.login("student1").status_code == 200
    assert created["id"] in [i["id"] for i in other_device.get("/api/me/requests").get_json()["items"]]

    with app.app_context():
        row = db.session.get(ServiceRequest, created["id"])
        owner = db.session.execute(select(User).where(User.username == "student1")).scalar_one()
        assert row.owner_user_id == owner.id
        assert row.fields == {"purpose": "bank", "copies": 2, "delivery": "office"}
        assert row.faculty_id == owner.student.group.program.faculty_id


@pytest.mark.parametrize(
    ("payload", "bad_fields"),
    [
        ({}, {"type"}),
        ({"type": "make_me_dean"}, {"type"}),
        ({"type": "study_certificate", "fields": {}}, {"purpose"}),
        ({"type": "study_certificate", "fields": {"purpose": "moon", "copies": 99, "delivery": "pigeon"}},
         {"purpose", "copies", "delivery"}),
        ({"type": "study_certificate", "fields": {"purpose": "bank", "copies": "много"}}, {"copies"}),
        ({"type": "study_certificate", "fields": {"purpose": "bank", "copies": True}}, {"copies"}),
        ({"type": "study_certificate", "fields": "not-an-object"}, {"purpose"}),
        ({"type": "absence", "fields": {"date_from": "2026-11-12", "date_to": "2026-11-10", "reason": "illness"}},
         {"date_to"}),
        ({"type": "absence", "fields": {"date_from": "вчера", "date_to": "2026-11-10", "reason": "illness"}},
         {"date_from"}),
        ({"type": "free_form", "fields": {"subject": "Вопрос"}}, {"comment"}),
        ({"type": "free_form", "fields": {"subject": "x" * 121}, "comment": "Достаточно длинный текст"}, {"subject"}),
        ({"type": "study_certificate", "fields": {"purpose": "bank"}, "comment": "я" * 1001}, {"comment"}),
    ],
)  # fmt: skip
def test_invalid_forms_are_rejected_with_field_messages(app, mira, payload, bad_fields):
    before = _count_requests(app)
    response = mira.post("/api/me/requests", json=payload)
    assert response.status_code == 422
    error = response.get_json()["error"]
    assert error["code"] == "validation_error"
    assert set(error["fields"]) == bad_fields
    assert all(isinstance(message, str) and message for message in error["fields"].values())
    assert _count_requests(app) == before, "некорректная форма не должна создавать заявку"


def test_non_json_body_is_rejected(mira):
    token = mira.token
    response = mira.client.post(
        "/api/me/requests", data="type=study_certificate", headers={"X-CSRF-Token": token}
    )
    assert response.status_code == 415
    array = mira.client.post("/api/me/requests", json=["study_certificate"], headers={"X-CSRF-Token": token})
    assert array.status_code == 400


def test_repeated_submit_with_same_key_creates_one_request(app, mira):
    before = _count_requests(app)
    headers = {"Idempotency-Key": "a3f1c2d4-5b6e-4f70-8a91-b2c3d4e5f607"}
    first = mira.post("/api/me/requests", json=VALID_CERTIFICATE, headers=headers)
    second = mira.post("/api/me/requests", json=VALID_CERTIFICATE, headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.get_json()["created"] is False
    assert first.get_json()["request"]["id"] == second.get_json()["request"]["id"]
    assert _count_requests(app) == before + 1


def test_same_key_from_another_student_is_independent(app, mira, timur):
    headers = {"Idempotency-Key": "shared-key-0001"}
    first = mira.post("/api/me/requests", json=VALID_CERTIFICATE, headers=headers).get_json()["request"]
    second = timur.post("/api/me/requests", json=VALID_CERTIFICATE, headers=headers)
    assert second.status_code == 201
    assert second.get_json()["request"]["id"] != first["id"]


def test_user_text_is_stored_and_returned_as_plain_text(mira):
    payload = {
        "type": "free_form",
        "fields": {"subject": "<img src=x onerror=alert(1)>"},
        "comment": "<script>alert('xss')</script> Прошу ответить\x00 на вопрос.",
    }
    response = mira.post("/api/me/requests", json=payload)
    assert response.status_code == 201
    assert response.content_type == "application/json"
    created = response.get_json()["request"]
    # Текст хранится как есть (без управляющих символов) и отдаётся только как JSON-строка.
    assert created["comment"] == "<script>alert('xss')</script> Прошу ответить на вопрос."
    assert created["title"] == "Обращение в деканат: <img src=x onerror=alert(1)>"


def test_staff_transition_writes_history_and_notifies_owner(app, mira):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]
    with app.app_context():
        dean = db.session.execute(select(User).where(User.username == "dean")).scalar_one()
        item = db.session.get(ServiceRequest, created["id"])
        request_service.transition(item, actor=dean, to_status="in_review", comment=None)
        request_service.transition(
            item, actor=dean, to_status="approved", comment="Готово, заберите в деканате."
        )
        db.session.commit()

    detail = mira.get(f"/api/me/requests/{created['id']}").get_json()["request"]
    assert detail["status"] == "approved" and detail["isFinal"] is True and detail["canComment"] is False
    assert [(e["fromStatus"], e["toStatus"]) for e in detail["events"]] == [
        (None, "submitted"), ("submitted", "in_review"), ("in_review", "approved")]  # fmt: skip
    last = detail["events"][-1]
    assert last["comment"] == "Готово, заберите в деканате."
    assert last["actor"]["role"] == "dean_staff" and "dean" not in last["actor"]["label"]  # логин не раскрыт
    assert [s["done"] for s in detail["steps"]] == [True, True, True]

    notes = [
        n
        for n in mira.get("/api/me/notifications").get_json()["items"]
        if n["link"] == {"type": "request", "id": created["id"]}
    ]
    assert [n["title"] for n in notes] == [
        f"Заявка {created['number']}: одобрена", f"Заявка {created['number']}: на рассмотрении"]  # fmt: skip
    assert notes[0]["body"] == "Готово, заберите в деканате." and notes[0]["read"] is False


def test_impossible_transitions_are_rejected(app, mira):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]
    with app.app_context():
        dean = db.session.execute(select(User).where(User.username == "dean")).scalar_one()
        item = db.session.get(ServiceRequest, created["id"])
        with pytest.raises(Exception) as skipped:
            request_service.transition(item, actor=dean, to_status="approved", comment=None)
        assert skipped.value.status == 409 and skipped.value.code == "invalid_transition"

        request_service.transition(item, actor=dean, to_status="in_review", comment=None)
        with pytest.raises(Exception) as no_reason:
            request_service.transition(item, actor=dean, to_status="rejected", comment="  ")
        assert no_reason.value.status == 422

        request_service.transition(item, actor=dean, to_status="rejected", comment="Не хватает основания.")
        with pytest.raises(Exception) as closed:
            request_service.transition(item, actor=dean, to_status="in_review", comment=None)
        assert closed.value.code == "invalid_transition"
        db.session.rollback()


def test_student_reply_returns_request_to_review(app, timur):
    listed = timur.get("/api/me/requests").get_json()["items"]
    waiting = next(i for i in listed if i["status"] == "needs_info")

    empty = timur.post(f"/api/me/requests/{waiting['id']}/comments", json={"comment": "   "})
    assert empty.status_code == 422

    response = timur.post(
        f"/api/me/requests/{waiting['id']}/comments", json={"comment": "Справку приложу сегодня."}
    )
    assert response.status_code == 201
    detail = response.get_json()["request"]
    assert detail["status"] == "in_review"
    assert (detail["events"][-1]["fromStatus"], detail["events"][-1]["toStatus"]) == (
        "needs_info",
        "in_review",
    )
    assert detail["events"][-1]["comment"] == "Справку приложу сегодня."
    with app.app_context():
        assert db.session.execute(
            select(func.count()).select_from(RequestEvent).where(RequestEvent.request_id == waiting["id"])
        ).scalar_one() == len(detail["events"])


def test_closed_request_does_not_accept_comments(mira):
    closed = next(i for i in mira.get("/api/me/requests").get_json()["items"] if i["status"] == "approved")
    response = mira.post(f"/api/me/requests/{closed['id']}/comments", json={"comment": "Спасибо!"})
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "request_closed"


def test_seeded_requests_differ_between_students(mira, timur):
    first = mira.get("/api/me/requests").get_json()["items"]
    second = timur.get("/api/me/requests").get_json()["items"]
    assert [i["status"] for i in first] == ["in_review", "approved"]
    assert [i["status"] for i in second] == ["needs_info", "approved"]
    assert {i["id"] for i in first}.isdisjoint({i["id"] for i in second})


def test_open_request_limit_protects_the_stand(app, mira):
    with app.app_context():
        owner = db.session.execute(select(User).where(User.username == "student1")).scalar_one()
        already_open = db.session.execute(
            select(func.count())
            .select_from(ServiceRequest)
            .where(
                ServiceRequest.owner_user_id == owner.id,
                ServiceRequest.status.notin_(["approved", "rejected"]),
            )
        ).scalar_one()
        for _ in range(request_service.MAX_OPEN_REQUESTS - already_open):
            request_service.create_request(owner, VALID_CERTIFICATE)
        db.session.commit()
    response = mira.post("/api/me/requests", json=VALID_CERTIFICATE)
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "too_many_open_requests"


def test_status_notifications_reach_only_the_owner(app, mira, timur):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]
    with app.app_context():
        dean = db.session.execute(select(User).where(User.username == "dean")).scalar_one()
        request_service.transition(
            db.session.get(ServiceRequest, created["id"]), actor=dean, to_status="in_review", comment=None
        )
        db.session.commit()
        recipients = (
            db.session.execute(
                select(Notification.recipient_user_id).where(
                    Notification.source_type == "request", Notification.source_id == created["id"]
                )
            )
            .scalars()
            .all()
        )
        owner = db.session.execute(select(User).where(User.username == "student1")).scalar_one()
        assert recipients == [owner.id]
    links = [n["link"] for n in timur.get("/api/me/notifications").get_json()["items"]]
    assert {"type": "request", "id": created["id"]} not in links
