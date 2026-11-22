"""Уведомления, служебные заголовки, формат ошибок, соответствие миграций моделям."""

from __future__ import annotations

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select

from app.extensions import db
from app.models import Notification
from app.services import dashboard as dashboard_service
from app.services import demo


def test_notification_feed_is_sorted_and_counts_unread(mira):
    data = mira.get("/api/me/notifications").get_json()
    items = data["items"]
    assert len(items) >= 8
    assert [i["createdAt"] for i in items] == sorted((i["createdAt"] for i in items), reverse=True)
    assert data["unreadCount"] == len([i for i in items if not i["read"]]) > 0
    assert {"lesson_change", "announcement", "deadline", "request_status", "grade"} <= {
        i["kind"] for i in items
    }
    only_unread = mira.get("/api/me/notifications?unread=1").get_json()["items"]
    assert only_unread and all(not i["read"] for i in only_unread)


def test_every_notification_link_opens_its_object(mira, timur):
    for api in (mira, timur):
        for item in api.get("/api/me/notifications").get_json()["items"]:
            link = item["link"]
            assert link is not None, item
            if link["type"] == "lesson":
                response = api.get(f"/api/me/lessons/{link['id']}")
            elif link["type"] == "request":
                response = api.get(f"/api/me/requests/{link['id']}")
            elif link["type"] == "announcement":
                response = api.get(f"/api/me/announcements/{link['id']}")
                assert response.get_json()["announcement"]["title"] == item["title"]
            elif link["type"] == "deadline":
                response = api.get(f"/api/me/deadlines/{link['id']}")
            else:
                assert link["type"] == "grades"
                courses = api.get("/api/me/grades").get_json()["currentTerm"]["courses"]
                assert link["courseId"] in {c["courseId"] for c in courses}
                continue
            assert response.status_code == 200, (item["title"], link)


def test_read_state_is_saved(app, mira):
    before = mira.get("/api/me/notifications").get_json()
    target = next(i for i in before["items"] if not i["read"])

    response = mira.patch(f"/api/me/notifications/{target['id']}/read")
    assert response.status_code == 200
    assert response.get_json()["notification"]["read"] is True
    assert response.get_json()["unreadCount"] == before["unreadCount"] - 1

    mira.logout()
    mira.login("student1")
    after = mira.get("/api/me/notifications").get_json()
    assert next(i for i in after["items"] if i["id"] == target["id"])["read"] is True
    assert after["unreadCount"] == before["unreadCount"] - 1
    assert mira.get("/api/me/dashboard").get_json()["summary"]["unreadNotifications"] == after["unreadCount"]

    assert mira.post("/api/me/notifications/read-all").get_json()["unreadCount"] == 0
    assert mira.get("/api/me/notifications").get_json()["unreadCount"] == 0
    assert mira.patch("/api/me/notifications/999999/read").status_code == 404


def test_deadline_reminder_matches_deadline_and_is_not_duplicated(app, mira):
    items = mira.get("/api/me/notifications").get_json()["items"]
    reminder = next(i for i in items if i["kind"] == "deadline")
    assert reminder["title"] == "Дедлайн завтра: Эссе «Типы политических режимов»"
    deadline = mira.get(f"/api/me/deadlines/{reminder['link']['id']}").get_json()["deadline"]
    assert deadline["title"] in reminder["title"] and deadline["isSoon"] is True
    assert deadline["subject"]["name"] == "Политология"

    with app.app_context():
        count = lambda: db.session.execute(  # noqa: E731
            select(func.count()).select_from(Notification).where(Notification.kind == "deadline")
        ).scalar_one()
        before = count()
        demo.create_deadline_reminders(dashboard_service.clock.now())
        db.session.commit()
        assert count() == before


def test_deadline_list_is_sorted_and_scoped(mira, timur):
    first = mira.get("/api/me/deadlines").get_json()["items"]
    second = timur.get("/api/me/deadlines").get_json()["items"]
    assert [d["dueAt"] for d in first] == sorted(d["dueAt"] for d in first)
    assert {d["id"] for d in first}.isdisjoint({d["id"] for d in second})
    assert all(not d["isOverdue"] for d in first)


def test_api_responses_are_not_cached_and_have_security_headers(mira):
    response = mira.get("/api/me/grades")
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Request-ID"]


def test_errors_use_one_json_format(mira, anon):
    missing = mira.get("/api/no-such-endpoint")
    assert missing.status_code == 404
    assert set(missing.get_json()) == {"error", "requestId"}
    assert missing.get_json()["error"]["code"] == "not_found"

    wrong_method = mira.client.delete("/api/me/requests", headers={"X-CSRF-Token": mira.token})
    assert wrong_method.status_code == 405
    assert wrong_method.get_json()["error"]["code"] == "method_not_allowed"

    assert anon.get("/api/health").get_json() == {"status": "ok"}


def test_unexpected_error_does_not_leak_details(app, mira, monkeypatch):
    def boom(_student):
        raise RuntimeError("secret internal detail: postgresql://campus:password@db")

    monkeypatch.setattr(dashboard_service, "dashboard", boom)
    response = mira.get("/api/me/dashboard")
    assert response.status_code == 500
    body = response.get_data(as_text=True)
    assert response.get_json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in body and "Traceback" not in body and "postgresql" not in body


def test_migrations_match_models(app):
    """Схема, созданная миграциями с нуля, совпадает с моделями: забытых миграций нет."""
    with app.app_context(), db.engine.connect() as connection:
        diff = compare_metadata(MigrationContext.configure(connection), db.metadata)
    assert diff == []
