"""Конфигурация приложения. Секреты читаются только из окружения сервера."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    APP_ENV = os.environ.get("APP_ENV", "development")
    TESTING = False

    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL")
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Сессионная cookie: недоступна из JS, не уходит на чужие сайты, в production только по HTTPS.
    SESSION_COOKIE_NAME = "mc_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _flag("SESSION_COOKIE_SECURE", default=False)
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_REFRESH_EACH_REQUEST = False

    # CSRF: токен привязан к сессии и живёт столько же, сколько она.
    WTF_CSRF_TIME_LIMIT = None
    WTF_CSRF_HEADERS = ["X-CSRF-Token", "X-CSRFToken"]
    WTF_CSRF_SSL_STRICT = True

    # Вложения и размер запросов.
    MAX_CONTENT_LENGTH = 6 * 1024 * 1024
    UPLOAD_DIR = os.environ.get("UPLOAD_DIR", str(BACKEND_DIR / "uploads"))

    # Доверять X-Forwarded-* можно только за собственным обратным прокси.
    TRUST_PROXY = _flag("TRUST_PROXY", default=False)

    # Собранный фронтенд (один origin для страниц и /api).
    FRONTEND_DIST = os.environ.get("FRONTEND_DIST", str(REPO_DIR / "frontend" / "dist"))

    # Argon2id: параметры по рекомендациям OWASP (19 МиБ, 2 прохода) с запасом.
    ARGON2_TIME_COST = 3
    ARGON2_MEMORY_KIB = 32 * 1024
    ARGON2_PARALLELISM = 1

    # Ограничение попыток входа.
    LOGIN_MAX_FAILURES_PER_ACCOUNT = 5
    LOGIN_MAX_FAILURES_PER_IP = 30
    LOGIN_FAILURE_WINDOW = timedelta(minutes=10)

    # Демо-данные обновляются лениво раз в сутки, чтобы перенос занятия всегда был «свежим».
    DEMO_AUTO_REFRESH = True

    JSON_AS_ASCII = False


class DevelopmentConfig(Config):
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-not-a-secret")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://campus:campus_local_only@127.0.0.1:5433/campus"
    )


class TestingConfig(Config):
    TESTING = True
    APP_ENV = "testing"
    SECRET_KEY = "test-only-not-a-secret"  # noqa: S105 (только для автотестов)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "TEST_DATABASE_URL", "postgresql+psycopg://campus:campus_local_only@127.0.0.1:5433/campus_test"
    )
    # Быстрое хеширование только в тестах, чтобы пересоздание данных не занимало секунды.
    ARGON2_TIME_COST = 1
    ARGON2_MEMORY_KIB = 8
    DEMO_AUTO_REFRESH = False
    UPLOAD_DIR = str(BACKEND_DIR / "instance" / "test_uploads")


class ProductionConfig(Config):
    SESSION_COOKIE_SECURE = True
    TRUST_PROXY = _flag("TRUST_PROXY", default=True)


def select_config() -> type[Config]:
    env = os.environ.get("APP_ENV", "development").lower()
    if env == "production":
        return ProductionConfig
    if env == "testing":
        return TestingConfig
    return DevelopmentConfig


def validate_production(config: dict) -> None:
    """Не даём запустить production с заглушками вместо секретов."""
    if config.get("APP_ENV") != "production":
        return
    secret = config.get("SECRET_KEY") or ""
    if len(secret) < 32 or secret.startswith(("change-me", "dev-only")):
        raise RuntimeError("SECRET_KEY не задан или слишком короткий для production")
    if not config.get("SQLALCHEMY_DATABASE_URI"):
        raise RuntimeError("DATABASE_URL не задан")
