"""Кабинет сотрудников: деканат, преподаватель, администратор. Права проверяются на сервере."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import Assessment, AuditEvent, Course, ServiceRequest, Subject, Teacher, User
from tests.conftest import VALID_CERTIFICATE, Api, _logged_in

STAFF_GET = [
    "/api/staff/summary",
    "/api/staff/requests",
    "/api/staff/requests/1",
    "/api/staff/groups",
    "/api/staff/schedule?group=1",
    "/api/staff/announcements",
]
TEACHER_GET = ["/api/teacher/courses", "/api/teacher/courses/1"]
ADMIN_GET = ["/api/admin/users", "/api/admin/audit"]


@pytest.fixture()
def dean_mp(app) -> Api:
    """Сотрудник деканата другого факультета (МП) — у него нет студентов из демо-набора."""
    return _logged_in(app, "dean_mp")


def _audit(app, action: str) -> list[AuditEvent]:
    with app.app_context():
        return list(db.session.execute(select(AuditEvent).where(AuditEvent.action == action)).scalars())


# ── Доступ по ролям ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("url", STAFF_GET + TEACHER_GET + ADMIN_GET)
def test_anonymous_gets_401(anon, url):
    assert anon.get(url).status_code == 401


@pytest.mark.parametrize("url", STAFF_GET + TEACHER_GET + ADMIN_GET)
def test_student_gets_403(mira, url):
    response = mira.get(url)
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "forbidden"


def test_roles_are_separated(dean, teacher, admin):
    for url in TEACHER_GET + ADMIN_GET:
        assert dean.get(url).status_code == 403, url
    for url in STAFF_GET + ADMIN_GET:
        assert teacher.get(url).status_code == 403, url
    for url in TEACHER_GET:
        assert admin.get(url).status_code == 403, url
    assert admin.get("/api/staff/requests").status_code == 200  # служебный режим


def test_student_cannot_change_anything_through_staff_api(mira):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]
    for method, url, body in [
        ("post", f"/api/staff/requests/{created['id']}/transition", {"toStatus": "approved"}),
        ("post", f"/api/staff/requests/{created['id']}/comments", {"comment": "Сам себе одобрил"}),
        ("patch", "/api/staff/lessons/1", {"action": "cancel", "reason": "Хочу выходной"}),
        (
            "post",
            "/api/staff/announcements",
            {"title": "Отмена занятий", "body": "Всё отменяется", "audience": "all"},
        ),
        ("patch", "/api/teacher/assessments/1", {"score": 100}),
        ("patch", "/api/admin/users/1", {"isActive": False}),
    ]:
        assert getattr(mira, method)(url, json=body).status_code == 403, url
    assert mira.get(f"/api/me/requests/{created['id']}").get_json()["request"]["status"] == "submitted"


# ── Деканат: заявки ───────────────────────────────────────────────────────────


def test_dean_processes_request_and_student_sees_result(app, mira, dean):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]

    queue = dean.get("/api/staff/requests?status=submitted").get_json()["items"]
    row = next(i for i in queue if i["id"] == created["id"])
    assert row["owner"]["name"] == "Северцева Мира Олеговна" and row["owner"]["group"] == "МО-2-03"

    detail = dean.get(f"/api/staff/requests/{created['id']}").get_json()["request"]
    assert [t["status"] for t in detail["allowedTransitions"]] == ["in_review"]
    assert detail["comment"] == "Нужна для открытия счёта."

    step = dean.post(f"/api/staff/requests/{created['id']}/transition", json={"toStatus": "in_review"})
    assert step.status_code == 200
    assert {t["status"] for t in step.get_json()["request"]["allowedTransitions"]} == {
        "approved",
        "rejected",
        "needs_info",
    }

    done = dean.post(
        f"/api/staff/requests/{created['id']}/transition",
        json={"toStatus": "approved", "comment": "Справка готова, кабинет 2010."},
    ).get_json()["request"]
    assert done["status"] == "approved" and done["allowedTransitions"] == [] and done["canComment"] is False

    seen = mira.get(f"/api/me/requests/{created['id']}").get_json()["request"]
    assert seen["status"] == "approved"
    assert seen["events"][-1]["comment"] == "Справка готова, кабинет 2010."
    assert seen["events"][-1]["actor"]["label"].startswith("Сотрудник деканата · ")
    titles = [n["title"] for n in mira.get("/api/me/notifications").get_json()["items"]]
    assert f"Заявка {created['number']}: одобрена" in titles

    events = _audit(app, "request.transition")
    assert [(e.before["status"], e.after["status"]) for e in events if e.entity_id == created["id"]] == [
        ("submitted", "in_review"),
        ("in_review", "approved"),
    ]


def test_dean_transition_rules(mira, dean):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]
    url = f"/api/staff/requests/{created['id']}/transition"
    assert dean.post(url, json={"toStatus": "approved"}).status_code == 409  # без рассмотрения нельзя
    assert dean.post(url, json={"toStatus": "magic"}).status_code == 422
    assert dean.post(url, json={"toStatus": "in_review"}).status_code == 200
    rejected = dean.post(url, json={"toStatus": "rejected", "comment": " "})
    assert rejected.status_code == 422 and "comment" in rejected.get_json()["error"]["fields"]


def test_dean_comment_reaches_student(mira, dean):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]
    response = dean.post(
        f"/api/staff/requests/{created['id']}/comments", json={"comment": "Будет готова в четверг."}
    )
    assert response.status_code == 201
    seen = mira.get(f"/api/me/requests/{created['id']}").get_json()["request"]
    assert seen["status"] == "submitted"
    assert (
        seen["events"][-1]["kind"] == "comment" and seen["events"][-1]["comment"] == "Будет готова в четверг."
    )
    note = mira.get("/api/me/notifications").get_json()["items"][0]
    assert note["title"] == f"Заявка {created['number']}: комментарий деканата"
    assert dean.post(f"/api/staff/requests/{created['id']}/comments", json={"comment": ""}).status_code == 422


def test_dean_of_other_faculty_sees_nothing(app, mira, dean_mp):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]
    assert dean_mp.get("/api/staff/requests?status=all").get_json()["items"] == []
    assert dean_mp.get(f"/api/staff/requests/{created['id']}").status_code == 404
    url = f"/api/staff/requests/{created['id']}"
    assert dean_mp.post(f"{url}/transition", json={"toStatus": "in_review"}).status_code == 404
    assert dean_mp.post(f"{url}/comments", json={"comment": "Чужой факультет"}).status_code == 404
    summary = dean_mp.get("/api/staff/summary").get_json()
    assert summary["open"] == 0 and [f["code"] for f in summary["faculties"]] == ["МП"]
    assert dean_mp.get("/api/staff/groups").get_json()["items"] == []
    with app.app_context():
        assert db.session.get(ServiceRequest, created["id"]).status == "submitted"


def test_queue_filters_and_search(mira, timur, dean):
    created = mira.post("/api/me/requests", json=VALID_CERTIFICATE).get_json()["request"]
    by_number = dean.get(f"/api/staff/requests?status=all&q={created['number']}").get_json()["items"]
    assert [i["id"] for i in by_number] == [created["id"]]
    by_name = dean.get("/api/staff/requests?status=all&q=Ладожский").get_json()["items"]
    assert by_name and {i["owner"]["name"] for i in by_name} == {"Ладожский Тимур Русланович"}
    assert dean.get("/api/staff/requests?status=all&q=%25").get_json()["items"] == []  # «%» ищется буквально
    needs_info = dean.get("/api/staff/requests?status=needs_info").get_json()["items"]
    assert [i["status"] for i in needs_info] == ["needs_info"]
    absence = dean.get("/api/staff/requests?status=all&type=absence").get_json()["items"]
    assert {i["type"] for i in absence} == {"absence"}
    assert dean.get("/api/staff/requests?status=bogus").status_code == 422
    assert dean.get("/api/staff/requests?type=bogus").status_code == 422

    summary = dean.get("/api/staff/summary").get_json()
    assert summary["counts"]["submitted"] == 1 and summary["counts"]["needs_info"] == 1
    assert summary["open"] == 3 and summary["decidedLast30Days"] == 2
    assert summary["averageDecisionHours"] is not None


# ── Деканат: расписание ───────────────────────────────────────────────────────


def _lesson_on(api, date: str, pair: int) -> dict:
    day = api.get(f"/api/me/schedule?from={date}&to={date}").get_json()["days"][0]
    return next(lesson for lesson in day["lessons"] if lesson["pairNumber"] == pair)


def test_dean_moves_lesson_and_student_sees_same_state(mira, dean):
    lesson = _lesson_on(mira, "2026-11-17", 2)  # вторник, Политология 10:30
    assert lesson["subject"]["name"] == "Политология"
    response = dean.patch(
        f"/api/staff/lessons/{lesson['id']}",
        json={"action": "move", "date": "2026-11-17", "startTime": "15:30", "endTime": "16:50", "room": "4102",
              "reason": "Лекционная аудитория занята."},
    )  # fmt: skip
    assert response.status_code == 200
    body = response.get_json()
    assert body["notified"] == 1 and body["lesson"]["room"] == "4102"

    seen = mira.get(f"/api/me/lessons/{lesson['id']}").get_json()["lesson"]
    assert seen == body["lesson"]
    assert seen["change"]["originalStartsAt"] == "2026-11-17T10:30:00+03:00"
    note = next(
        n for n in mira.get("/api/me/notifications").get_json()["items"] if n["link"]["id"] == lesson["id"]
    )
    assert note["title"] == "Перенос занятия: Политология" and note["lesson"] == seen

    group = dean.get("/api/staff/schedule?group=1&from=2026-11-16").get_json()
    assert lesson["id"] in [c["id"] for c in group["changes"]]
    events = _audit(dean.app, "lesson.move")
    assert events[-1].before["room"] == "1025" and events[-1].after["room"] == "4102"

    restored = dean.patch(f"/api/staff/lessons/{lesson['id']}", json={"action": "restore"})
    assert restored.status_code == 200 and restored.get_json()["lesson"]["status"] == "scheduled"
    note = next(
        n for n in mira.get("/api/me/notifications").get_json()["items"] if n["link"]["id"] == lesson["id"]
    )
    assert note["title"] == "Занятие пройдёт по расписанию: Политология"


def test_dean_lesson_validation(mira, dean):
    lesson = _lesson_on(mira, "2026-11-17", 2)
    url = f"/api/staff/lessons/{lesson['id']}"
    busy = dean.patch(url, json={"action": "move", "date": "2026-11-17", "startTime": "12:00", "endTime": "13:20",
                                 "room": "2208"})  # fmt: skip
    assert busy.status_code == 422 and "startsAt" in busy.get_json()["error"]["fields"]
    sunday = dean.patch(url, json={"action": "move", "date": "2026-11-22", "startTime": "10:30", "endTime": "11:50",
                                   "room": "1"})  # fmt: skip
    assert sunday.status_code == 422
    night = dean.patch(url, json={"action": "move", "date": "2026-11-18", "startTime": "23:00", "endTime": "23:50",
                                  "room": "1"})  # fmt: skip
    assert night.status_code == 422
    past = dean.patch(url, json={"action": "move", "date": "2026-11-10", "startTime": "10:30", "endTime": "11:50",
                                 "room": "1"})  # fmt: skip
    assert past.status_code == 422
    assert dean.patch(url, json={"action": "cancel", "reason": ""}).status_code == 422
    assert dean.patch(url, json={"action": "restore"}).status_code == 422  # не менялось
    assert dean.patch(url, json={"action": "explode"}).status_code == 422
    cancelled = dean.patch(url, json={"action": "cancel", "reason": "Преподаватель болен."})
    assert cancelled.status_code == 200 and cancelled.get_json()["lesson"]["status"] == "cancelled"


def test_dean_of_other_faculty_cannot_touch_lessons(mira, dean_mp):
    lesson = _lesson_on(mira, "2026-11-17", 2)
    response = dean_mp.patch(
        f"/api/staff/lessons/{lesson['id']}", json={"action": "cancel", "reason": "Чужая группа"}
    )
    assert response.status_code == 404
    assert dean_mp.get("/api/staff/schedule?group=1").status_code == 404
    assert mira.get(f"/api/me/lessons/{lesson['id']}").get_json()["lesson"]["status"] == "scheduled"


# ── Деканат: объявления ───────────────────────────────────────────────────────


def test_announcement_reaches_only_its_audience(mira, timur, dean, admin):
    response = dean.post(
        "/api/staff/announcements",
        json={"title": "Собрание первокурсников", "body": "В пятницу в 15:00 в аудитории 1011.", "audience": "faculty",
              "faculty": "МО"},
    )  # fmt: skip
    assert response.status_code == 201 and response.get_json()["notified"] == 1
    created = response.get_json()["announcement"]
    assert mira.get(f"/api/me/announcements/{created['id']}").status_code == 200
    assert timur.get(f"/api/me/announcements/{created['id']}").status_code == 404
    assert created["id"] not in [
        n["link"]["id"]
        for n in timur.get("/api/me/notifications").get_json()["items"]
        if n["link"]["type"] == "announcement"
    ]

    to_all = {"title": "Для всех студентов", "body": "Тестовое объявление для всех.", "audience": "all"}
    assert dean.post("/api/staff/announcements", json=to_all).status_code == 403
    assert admin.post("/api/staff/announcements", json=to_all).get_json()["notified"] == 2

    bad = dean.post("/api/staff/announcements", json={"title": "Ой", "body": "коротко", "audience": "faculty",
                                                       "faculty": "МП"})  # fmt: skip
    assert bad.status_code == 422 and set(bad.get_json()["error"]["fields"]) == {"title", "body", "faculty"}
    group = dean.post("/api/staff/announcements", json={"title": "Только группе", "body": "Сообщение для группы МЭО.",
                                                         "audience": "group", "groupId": 2})  # fmt: skip
    assert group.status_code == 201 and group.get_json()["announcement"]["audience"] == "Группа МЭО-3-07"


def test_dean_of_other_faculty_cannot_announce_to_it(dean_mp):
    response = dean_mp.post(
        "/api/staff/announcements",
        json={"title": "Чужому факультету", "body": "Не должно дойти до студентов.", "audience": "faculty",
              "faculty": "МО"},
    )  # fmt: skip
    assert response.status_code == 422


# ── Преподаватель ─────────────────────────────────────────────────────────────


def _assessment_id(app, subject: str, username: str, position: int = 3) -> int:
    with app.app_context():
        return db.session.execute(
            select(Assessment.id)
            .join(Course, Course.id == Assessment.course_id)
            .join(Subject, Subject.id == Course.subject_id)
            .join(User, User.id == Assessment.student_user_id)
            .where(Subject.name == subject, User.username == username, Assessment.position == position)
        ).scalar_one()


def test_teacher_sees_only_assigned_courses(teacher):
    items = teacher.get("/api/teacher/courses").get_json()["items"]
    assert {(i["subject"], i["group"]) for i in items} == {
        ("Теория международных отношений", "МО-2-03"),
        ("Мировая политика", "МЭО-3-07"),
        ("Введение в специальность", "МО-2-03"),
    }
    assert items[0]["isCurrent"] is True and all(i["students"] == 1 for i in items)


def test_teacher_updates_grade_with_audit_and_notification(app, mira, teacher):
    course = next(
        i
        for i in teacher.get("/api/teacher/courses").get_json()["items"]
        if i["subject"].startswith("Теория")
    )
    sheet = teacher.get(f"/api/teacher/courses/{course['id']}").get_json()
    assert sheet["editable"] is True and [s["name"] for s in sheet["students"]] == ["Северцева Мира Олеговна"]
    expected = next(c for c in sheet["students"][0]["controls"] if c["status"] == "expected")

    response = teacher.patch(f"/api/teacher/assessments/{expected['id']}", json={"score": 77})
    assert response.status_code == 200 and response.get_json()["assessment"]["status"] == "graded"

    grades = mira.get("/api/me/grades").get_json()["currentTerm"]["courses"]
    tmo = next(c for c in grades if c["courseId"] == course["id"])
    assert next(c for c in tmo["controls"] if c["id"] == expected["id"])["score"] == 77
    assert tmo["currentScore"] == response.get_json()["currentScore"]
    note = mira.get("/api/me/notifications").get_json()["items"][0]
    assert note["title"] == "Новая оценка: Теория международных отношений" and "77 из 100" in note["body"]

    event = _audit(app, "assessment.update")[-1]
    assert event.before == {"score": None, "status": "expected"}
    assert event.after["score"] == 77 and event.actor_user_id == _user_id(app, "teacher")

    cleared = teacher.patch(f"/api/teacher/assessments/{expected['id']}", json={"score": None})
    assert cleared.get_json()["assessment"]["status"] == "expected"


def _user_id(app, username: str) -> int:
    with app.app_context():
        return db.session.execute(select(User.id).where(User.username == username)).scalar_one()


@pytest.mark.parametrize("score", [-1, 101, "много", True, 3.5, {}])
def test_teacher_score_validation(app, teacher, score):
    assessment_id = _assessment_id(app, "Теория международных отношений", "student1")
    assert (
        teacher.patch(f"/api/teacher/assessments/{assessment_id}", json={"score": score}).status_code == 422
    )


def test_teacher_cannot_touch_other_courses(app, teacher, timur):
    foreign = _assessment_id(app, "Политология", "student1")  # ведёт другой преподаватель
    assert teacher.patch(f"/api/teacher/assessments/{foreign}", json={"score": 100}).status_code == 404
    with app.app_context():
        course_id = db.session.execute(
            select(Course.id).join(Subject).join(Teacher).where(Subject.name == "Политология")
        ).scalar_one()
        assert db.session.get(Assessment, foreign).score != 100
    assert teacher.get(f"/api/teacher/courses/{course_id}").status_code == 404

    past = next(i for i in teacher.get("/api/teacher/courses").get_json()["items"] if not i["isCurrent"])
    final = teacher.get(f"/api/teacher/courses/{past['id']}").get_json()["students"][0]["final"]
    closed = teacher.patch(f"/api/teacher/assessments/{final['id']}", json={"score": 100})
    assert closed.status_code == 409 and closed.get_json()["error"]["code"] == "term_closed"


# ── Администратор ─────────────────────────────────────────────────────────────


def test_admin_deactivates_demo_account(app, admin, timur):
    users = admin.get("/api/admin/users").get_json()["items"]
    assert len(users) == 6 and all("password" not in str(u).lower() for u in users)
    target = next(u for u in users if u["username"] == "student2")

    response = admin.patch(f"/api/admin/users/{target['id']}", json={"isActive": False})
    assert response.status_code == 200 and response.get_json()["user"]["isActive"] is False
    assert timur.get("/api/me/dashboard").status_code == 401  # сессия отозвана сразу
    assert Api(app).login("student2").status_code == 401

    assert admin.patch(f"/api/admin/users/{target['id']}", json={"isActive": True}).status_code == 200
    assert Api(app).login("student2").status_code == 200

    me = next(u for u in users if u["username"] == "admin")
    assert admin.patch(f"/api/admin/users/{me['id']}", json={"isActive": False}).status_code == 409
    assert admin.patch(f"/api/admin/users/{target['id']}", json={"isActive": "no"}).status_code == 422

    log = admin.get("/api/admin/audit").get_json()["items"]
    assert [e["action"] for e in log[:2]] == ["user.activate", "user.deactivate"]
    assert log[0]["actor"]["name"] == "Администратор демо-стенда"
