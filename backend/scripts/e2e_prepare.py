"""Готовит отдельную базу для сквозных тестов Playwright.

Создаёт базу (имя обязано оканчиваться на _e2e), применяет миграции с нуля и заново засевает
демо-данные с тестовыми паролями из окружения. Рабочая база и файл с паролями разработчика
(instance/demo_credentials.json) не затрагиваются.

Запускается из playwright.config.ts перед стартом сервера.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from flask_migrate import upgrade  # noqa: E402
from sqlalchemy import text  # noqa: E402

E2E_KEYS = {
    "student1": "E2E_PASSWORD_STUDENT1",
    "student2": "E2E_PASSWORD_STUDENT2",
    "dean": "E2E_PASSWORD_STAFF",
    "dean_mp": "E2E_PASSWORD_STAFF",
    "teacher": "E2E_PASSWORD_STAFF",
    "admin": "E2E_PASSWORD_STAFF",
}


def ensure_database(url: str) -> None:
    name = url.rsplit("/", 1)[1].split("?")[0]
    if not name.endswith("_e2e"):
        raise SystemExit(f"Отказ: e2e-база должна оканчиваться на _e2e, получено {name!r}")
    maintenance = url.replace("postgresql+psycopg://", "postgresql://").rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(maintenance, autocommit=True) as conn:
        if conn.execute("select 1 from pg_database where datname = %s", (name,)).fetchone() is None:
            conn.execute(f'create database "{name}"')


def main() -> None:
    url = os.environ["DATABASE_URL"]
    ensure_database(url)

    from app import create_app
    from app.extensions import db
    from app.seeds.builder import seed_demo

    app = create_app()
    with app.app_context():
        upgrade(directory=str(Path(__file__).resolve().parent.parent / "migrations"))
        tables = ", ".join(f'"{t.name}"' for t in db.metadata.sorted_tables)
        db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))  # noqa: S608
        passwords = {key: os.environ[env] for key, env in E2E_KEYS.items()}
        summary = seed_demo(passwords)
        db.session.commit()
    print(f"e2e база готова: пользователей {summary['users']}, переносов {len(summary['movedLessons'])}")


if __name__ == "__main__":
    main()
