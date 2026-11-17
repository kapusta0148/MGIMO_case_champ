"""Чужие данные: прямые адреса, перебор идентификаторов, подмена владельца, роли (IDOR/BOLA)."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Announcement, Assessment, Course, Deadline, Lesson, Notification, ServiceRequest, User
from tests.conftest import VALID_CERTIFICATE


def _user_id(app, username: str) -> int:
    with app.app_context():
        return db.session.execute(select(User.id).where(User.username == username)).scalar_one()


def _ids(app, model, *conditions) -> list[int]:
    with app.app_context():
        return list(db.session.execute(select(model.id).where(*conditions)).scalars())


def test_other_student_cannot_open_request_by_direct_id(app, mira, timur):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]

    response = timur.get(f"/api/me/requests/{created['id']}")
    assert response.status_code == 404
    body = response.get_data(as_text=True)
    for secret in (created["number"], "Нужна для открытия счёта", "Северцева"):
        assert secret not in body

    assert created["id"] not in [i["id"] for i in timur.get("/api/me/requests").get_json()["items"]]
    # Ответ неотличим от несуществующей заявки.
    missing = timur.get("/api/me/requests/999999")
    assert missing.status_code == 404
    assert missing.get_json()["error"] == response.get_json()["error"]


def test_enumerating_ids_never_reveals_foreign_requests(app, mira, timur):
    mira_id = _user_id(app, "student1")
    foreign = _ids(app, ServiceRequest, ServiceRequest.owner_user_id == mira_id)
    assert len(foreign) >= 2
    for request_id in foreign:
        assert timur.get(f"/api/me/requests/{request_id}").status_code == 404
    own = {i["id"] for i in timur.get("/api/me/requests").get_json()["items"]}
    assert own.isdisjoint(foreign)


def test_other_student_cannot_comment_on_foreign_request(app, mira, timur):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]
    response = timur.post(f"/api/me/requests/{created['id']}/comments", json={"comment": "Чужой комментарий"})
    assert response.status_code == 404
    events = mira.get(f"/api/me/requests/{created['id']}").get_json()["request"]["events"]
    assert [e["kind"] for e in events] == ["created"]


@pytest.mark.parametrize("field", ["ownerUserId", "owner_user_id", "userId", "user_id", "owner"])
def test_owner_cannot_be_spoofed_through_request_body(app, mira, field):
    victim = _user_id(app, "student2")
    payload = {
        **VALID_CERTIFICATE,
        field: victim,
        "status": "approved",
        "number": "MC-0000-00001",
        "facultyId": 3,
    }
    response = mira.post("/api/me/requests", json=payload)
    assert response.status_code == 201
    created = response.get_json()["request"]
    assert created["status"] == "submitted" and created["number"] != "MC-0000-00001"
    with app.app_context():
        row = db.session.get(ServiceRequest, created["id"])
        assert row.owner_user_id == _user_id(app, "student1")
        assert row.faculty_id == db.session.get(User, row.owner_user_id).student.group.program.faculty_id
        assert set(row.fields) == {"purpose", "copies", "delivery"}  # лишние поля отброшены


def test_notifications_are_private(app, mira, timur):
    mira_id = _user_id(app, "student1")
    foreign = _ids(
        app, Notification, Notification.recipient_user_id == mira_id, Notification.read_at.is_(None)
    )
    assert foreign

    for notification_id in foreign:
        assert timur.patch(f"/api/me/notifications/{notification_id}/read").status_code == 404
    assert timur.post("/api/me/notifications/read-all").status_code == 200

    with app.app_context():
        still_unread = (
            db.session.execute(
                select(Notification.id).where(Notification.id.in_(foreign), Notification.read_at.is_(None))
            )
            .scalars()
            .all()
        )
        assert sorted(still_unread) == sorted(foreign), "чужие уведомления не должны помечаться прочитанными"

    own_ids = {n["id"] for n in timur.get("/api/me/notifications").get_json()["items"]}
    assert own_ids.isdisjoint(foreign)


def test_lessons_and_deadlines_of_other_group_are_hidden(app, mira, timur):
    with app.app_context():
        timur_group = (
            db.session.execute(select(User).where(User.username == "student2")).scalar_one().student.group_id
        )
        foreign_lesson = db.session.execute(
            select(Lesson.id).join(Course).where(Course.group_id == timur_group).limit(1)
        ).scalar_one()
        foreign_deadline = db.session.execute(
            select(Deadline.id).where(Deadline.group_id == timur_group).limit(1)
        ).scalar_one()

    assert timur.get(f"/api/me/lessons/{foreign_lesson}").status_code == 200
    assert mira.get(f"/api/me/lessons/{foreign_lesson}").status_code == 404
    assert timur.get(f"/api/me/deadlines/{foreign_deadline}").status_code == 200
    assert mira.get(f"/api/me/deadlines/{foreign_deadline}").status_code == 404


def test_announcements_respect_audience(app, mira, timur):
    with app.app_context():
        rows = db.session.execute(select(Announcement)).scalars().all()
        for_all = next(a.id for a in rows if a.faculty_id is None and a.group_id is None)
        for_meo_faculty = next(a.id for a in rows if a.faculty and a.faculty.code == "МЭО")
        for_meo_group = next(a.id for a in rows if a.group and a.group.name == "МЭО-3-07")
        for_mo_group = next(a.id for a in rows if a.group and a.group.name == "МО-2-03")

    assert mira.get(f"/api/me/announcements/{for_all}").status_code == 200
    assert timur.get(f"/api/me/announcements/{for_all}").status_code == 200

    for hidden in (for_meo_faculty, for_meo_group):
        response = mira.get(f"/api/me/announcements/{hidden}")
        assert response.status_code == 404
        assert timur.get(f"/api/me/announcements/{hidden}").status_code == 200
    assert timur.get(f"/api/me/announcements/{for_mo_group}").status_code == 404


def test_grades_contain_only_own_assessments(app, mira, timur):
    def control_ids(api) -> set[int]:
        data = api.get("/api/me/grades").get_json()
        terms = [data["currentTerm"], *data["pastTerms"]]
        return {c["id"] for term in terms for course in term["courses"] for c in course["controls"]}

    mira_id, timur_id = _user_id(app, "student1"), _user_id(app, "student2")
    with app.app_context():
        owners = dict(db.session.execute(select(Assessment.id, Assessment.student_user_id)).all())
    first, second = control_ids(mira), control_ids(timur)
    assert first and second and first.isdisjoint(second)
    assert {owners[i] for i in first} == {mira_id}
    assert {owners[i] for i in second} == {timur_id}


@pytest.mark.parametrize(
    "url",
    [
        "/api/me/grades?user_id=2",
        "/api/me/grades?userId=2&student_user_id=2",
        "/api/me/profile?username=student2",
        "/api/me/requests?owner_user_id=2",
        "/api/me/notifications?recipient_user_id=2",
        "/api/me/dashboard?user=student2",
    ],
)
def test_query_parameters_cannot_switch_user(mira, url):
    plain = mira.get(url.split("?")[0]).get_json()
    tampered = mira.get(url)
    assert tampered.status_code == 200
    assert tampered.get_json() == plain


@pytest.mark.parametrize("role", ["dean", "teacher", "admin"])
@pytest.mark.parametrize(
    "url",
    [
        "/api/me/profile",
        "/api/me/dashboard",
        "/api/me/schedule",
        "/api/me/grades",
        "/api/me/requests",
        "/api/me/requests/1",
        "/api/me/notifications",
        "/api/me/lessons/1",
    ],
)
def test_staff_roles_cannot_use_student_cabinet(request, role, url):
    api = request.getfixturevalue(role)
    response = api.get(url)
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"


def test_staff_cannot_create_student_request(dean):
    assert dean.post("/api/me/requests", json=VALID_CERTIFICATE).status_code == 403


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("post", "/api/me/requests"),
        ("post", "/api/me/requests/1/comments"),
        ("patch", "/api/me/notifications/1/read"),
        ("post", "/api/me/notifications/read-all"),
    ],
)
def test_mutations_need_login_even_with_valid_csrf(anon, method, url):
    response = getattr(anon, method)(url, json=VALID_CERTIFICATE)
    assert response.status_code == 401
