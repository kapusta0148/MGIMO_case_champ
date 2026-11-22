"""Вход, выход, сессии, CSRF, хранение паролей, ограничение попыток."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app import clock, create_app
from app.config import TestingConfig
from app.extensions import db
from app.models import AuthSession, User
from tests.conftest import FROZEN_NOW, PASSWORDS, Api

PROTECTED_GET = [
    "/api/auth/me",
    "/api/me/profile",
    "/api/me/dashboard",
    "/api/me/schedule",
    "/api/me/lessons/1",
    "/api/me/grades",
    "/api/me/deadlines",
    "/api/me/deadlines/1",
    "/api/me/requests",
    "/api/me/requests/1",
    "/api/me/notifications",
    "/api/me/announcements/1",
    "/api/meta/request-types",
]


def test_login_returns_user_and_sets_protected_cookie(anon):
    response = anon.login("student1")
    assert response.status_code == 200
    body = response.get_json()
    assert body["user"]["username"] == "student1"
    assert body["user"]["role"] == "student"
    assert "password" not in str(body).lower()

    set_cookie = [v for k, v in response.headers if k == "Set-Cookie" and v.startswith("mc_session=")]
    assert set_cookie, "сессионная cookie должна быть установлена"
    assert "HttpOnly" in set_cookie[0]
    assert "SameSite=Lax" in set_cookie[0]


def test_cookie_is_secure_in_production_like_config(app):
    class SecureConfig(TestingConfig):
        SESSION_COOKIE_SECURE = True

    secure_app = create_app(SecureConfig)
    api = Api(secure_app)
    # Secure-cookie браузер отправляет только по HTTPS — повторяем это в тестовом клиенте.
    https = {"base_url": "https://localhost"}
    token = api.client.get("/api/auth/csrf", **https).get_json()["csrfToken"]
    response = api.client.post(
        "/api/auth/login",
        json={"username": "student1", "password": PASSWORDS["student1"]},
        headers={"X-CSRF-Token": token, "Referer": "https://localhost/login"},
        **https,
    )
    assert response.status_code == 200, response.get_json()
    cookie = next(v for k, v in response.headers if k == "Set-Cookie" and v.startswith("mc_session="))
    assert "Secure" in cookie and "HttpOnly" in cookie
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")


@pytest.mark.parametrize(
    ("username", "password"),
    [("student1", "wrong-password"), ("no-such-user", "whatever-123")],
)
def test_wrong_credentials_get_identical_answer(anon, username, password):
    response = anon.login(username, password)
    assert response.status_code == 401
    error = response.get_json()["error"]
    assert error["code"] == "invalid_credentials"
    assert error["message"] == "Неверный логин или пароль."
    assert anon.get("/api/auth/me").status_code == 401


def test_login_requires_csrf_token(anon):
    response = anon.client.post(
        "/api/auth/login", json={"username": "student1", "password": PASSWORDS["student1"]}
    )
    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "csrf_failed"


def test_login_validates_input(anon):
    response = anon.post("/api/auth/login", json={"username": "", "password": ""})
    assert response.status_code == 422
    assert set(response.get_json()["error"]["fields"]) == {"username", "password"}

    token = anon.csrf()
    not_json = anon.client.post("/api/auth/login", data="username=student1", headers={"X-CSRF-Token": token})
    assert not_json.status_code == 415


def test_username_is_case_insensitive(anon):
    assert anon.login("STUDENT1", PASSWORDS["student1"]).status_code == 200


@pytest.mark.parametrize("url", PROTECTED_GET)
def test_private_pages_need_login(anon, url):
    response = anon.get(url)
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "unauthorized"


def test_logout_closes_private_pages(mira):
    assert mira.get("/api/me/dashboard").status_code == 200
    assert mira.logout().status_code == 200
    for url in PROTECTED_GET:
        assert mira.get(url).status_code == 401, url


def test_logout_revokes_session_on_server(app, mira):
    """Сохранённая до выхода cookie после выхода не должна работать (например, на чужом компьютере)."""
    stolen = mira.cookie().value
    assert mira.logout().status_code == 200

    thief = Api(app)
    thief.client.set_cookie("mc_session", stolen)
    assert thief.get("/api/auth/me").status_code == 401
    assert thief.get("/api/me/requests").status_code == 401

    with app.app_context():
        sessions = db.session.execute(select(AuthSession)).scalars().all()
        assert sessions and all(s.revoked_at is not None for s in sessions)


def test_login_rotates_session_and_csrf_token(anon):
    before_token = anon.csrf()
    before_cookie = anon.cookie().value
    assert anon.login("student1").status_code == 200
    assert anon.cookie().value != before_cookie
    # Токен, выданный до входа, после входа не подходит.
    stale = anon.client.post(
        "/api/me/notifications/read-all", json={}, headers={"X-CSRF-Token": before_token}
    )
    assert stale.status_code == 403
    assert anon.post("/api/me/notifications/read-all").status_code == 200


def test_mutations_need_csrf_token_when_logged_in(mira):
    without = mira.client.post("/api/me/requests", json={"type": "study_certificate"})
    assert without.status_code == 403
    assert without.get_json()["error"]["code"] == "csrf_failed"
    wrong = mira.client.post("/api/me/requests", json={}, headers={"X-CSRF-Token": "forged"})
    assert wrong.status_code == 403


def test_session_expires(app, mira):
    assert mira.get("/api/auth/me").status_code == 200
    clock.freeze(FROZEN_NOW + app.config["PERMANENT_SESSION_LIFETIME"] + timedelta(minutes=1))
    assert mira.get("/api/auth/me").status_code == 401


def test_deactivated_user_loses_access(app, mira):
    with app.app_context():
        user = db.session.execute(select(User).where(User.username == "student1")).scalar_one()
        user.is_active = False
        db.session.commit()
    assert mira.get("/api/auth/me").status_code == 401
    assert Api(app).login("student1").status_code == 401


def test_passwords_are_stored_as_argon2id_hashes(app):
    with app.app_context():
        users = db.session.execute(select(User)).scalars().all()
        assert len(users) == 6
        for user in users:
            assert user.password_hash.startswith("$argon2id$")
            for plain in PASSWORDS.values():
                assert plain not in user.password_hash
        # У одинаковых по смыслу записей разные соли -> разные хеши.
        assert len({u.password_hash for u in users}) == len(users)


def test_login_is_throttled_after_repeated_failures(app, anon):
    limit = app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]
    for _ in range(limit):
        assert anon.login("student1", "bad-password").status_code == 401
    blocked = anon.login("student1")  # даже с верным паролем
    assert blocked.status_code == 429
    assert blocked.get_json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) > 0
    # Другой аккаунт с того же адреса не заблокирован.
    assert Api(app).login("student2").status_code == 200
    # После окна ожидания вход снова возможен.
    clock.freeze(FROZEN_NOW + app.config["LOGIN_FAILURE_WINDOW"] + timedelta(seconds=5))
    assert Api(app).login("student1").status_code == 200


def test_roles_are_reported_for_staff_accounts(dean, teacher, admin):
    assert dean.get("/api/auth/me").get_json()["user"]["role"] == "dean_staff"
    assert teacher.get("/api/auth/me").get_json()["user"]["role"] == "teacher"
    assert admin.get("/api/auth/me").get_json()["user"]["role"] == "admin"
    faculties = {f["code"] for f in dean.get("/api/auth/me").get_json()["user"]["staff"]["faculties"]}
    assert faculties == {"МО", "МЭО"}
