"""Общие фикстуры.

Тесты идут на настоящем PostgreSQL (отдельная база *_test). Схема один раз создаётся
миграциями с нуля, перед каждым тестом данные пересоздаются сидами при «замороженном» времени.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path

os.environ["APP_ENV"] = "testing"

import pytest
from flask_migrate import upgrade
from sqlalchemy import text

from app import clock, create_app
from app.config import TestingConfig
from app.extensions import db
from app.seeds.builder import seed_demo

# Понедельник, 09:48 по Москве: идёт первая пара, до второй 42 минуты.
FROZEN_NOW = datetime(2026, 11, 16, 9, 48, tzinfo=clock.MSK)
PASSWORDS = {
    "student1": "test-student1-pass",
    "student2": "test-student2-pass",
    "dean": "test-dean-pass",
    "dean_mp": "test-dean-mp-pass",
    "teacher": "test-teacher-pass",
    "admin": "test-admin-pass",
}
USERNAMES = {"student1": "student1", "student2": "student2", "dean": "dean", "dean_mp": "dean.mp",
             "teacher": "teacher", "admin": "admin"}  # fmt: skip
MIGRATIONS_DIR = str(Path(__file__).resolve().parent.parent / "migrations")


def _truncate_all() -> None:
    tables = ", ".join(f'"{table.name}"' for table in db.metadata.sorted_tables)
    db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def app():
    application = create_app(TestingConfig)
    url = application.config["SQLALCHEMY_DATABASE_URI"]
    # Предохранитель: схему пересоздаём только в базе, имя которой заканчивается на _test.
    assert url.rsplit("/", 1)[-1].split("?")[0].endswith("_test"), (
        "тесты можно запускать только на *_test базе"
    )
    with application.app_context():
        db.session.execute(text("DROP SCHEMA public CASCADE"))
        db.session.execute(text("CREATE SCHEMA public"))
        db.session.commit()
        db.session.remove()
        db.engine.dispose()
        upgrade(directory=MIGRATIONS_DIR)  # миграции применяются с нуля
        db.session.remove()
    return application


@pytest.fixture(autouse=True)
def fresh_data(app):
    clock.freeze(FROZEN_NOW)
    with app.app_context():
        _truncate_all()
        seed_demo(PASSWORDS, lessons_from=date(2026, 11, 2), lessons_to=date(2026, 12, 5))
        db.session.commit()
        db.session.remove()
    yield
    clock.freeze(None)


class Api:
    """Тестовый «браузер»: своя cookie-банка и CSRF-токен, как у отдельного устройства."""

    def __init__(self, app):
        self.app = app
        self.client = app.test_client()
        self.token: str | None = None

    def csrf(self) -> str:
        self.token = self.client.get("/api/auth/csrf").get_json()["csrfToken"]
        return self.token

    def _headers(self, headers: dict | None) -> dict:
        merged = {"X-CSRF-Token": self.token or self.csrf()}
        merged.update(headers or {})
        return merged

    def login(self, key: str, password: str | None = None):
        response = self.client.post(
            "/api/auth/login",
            json={"username": USERNAMES.get(key, key), "password": password or PASSWORDS.get(key, "")},
            headers=self._headers(None),
        )
        if response.status_code == 200:
            self.token = response.get_json()["csrfToken"]
        return response

    def logout(self):
        response = self.client.post("/api/auth/logout", headers=self._headers(None))
        if response.status_code == 200:
            self.token = response.get_json()["csrfToken"]
        return response

    def get(self, url: str, **kwargs):
        return self.client.get(url, **kwargs)

    def post(self, url: str, json=None, headers: dict | None = None):
        return self.client.post(url, json=json if json is not None else {}, headers=self._headers(headers))

    def patch(self, url: str, json=None, headers: dict | None = None):
        return self.client.patch(url, json=json if json is not None else {}, headers=self._headers(headers))

    def cookie(self, name: str = "mc_session"):
        return self.client.get_cookie(name)


@pytest.fixture()
def anon(app) -> Api:
    return Api(app)


def _logged_in(app, key: str) -> Api:
    api = Api(app)
    response = api.login(key)
    assert response.status_code == 200, response.get_json()
    return api


@pytest.fixture()
def mira(app) -> Api:
    """Первый демо-студент (МО, 2 курс)."""
    return _logged_in(app, "student1")


@pytest.fixture()
def timur(app) -> Api:
    """Второй демо-студент (МЭО, 3 курс)."""
    return _logged_in(app, "student2")


@pytest.fixture()
def dean(app) -> Api:
    return _logged_in(app, "dean")


@pytest.fixture()
def teacher(app) -> Api:
    return _logged_in(app, "teacher")


@pytest.fixture()
def admin(app) -> Api:
    return _logged_in(app, "admin")


VALID_CERTIFICATE = {
    "type": "study_certificate",
    "fields": {"purpose": "bank", "copies": 2, "delivery": "office"},
    "comment": "Нужна для открытия счёта.",
}
