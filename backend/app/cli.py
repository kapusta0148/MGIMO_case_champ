"""Команды обслуживания: `flask seed`, `flask demo refresh`."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import click
from flask import Flask, current_app
from flask.cli import AppGroup
from sqlalchemy import func, select, text

from .extensions import db
from .models import User

DEMO_KEYS = {
    "student1": "DEMO_PASSWORD_STUDENT1",
    "student2": "DEMO_PASSWORD_STUDENT2",
    "dean": "DEMO_PASSWORD_DEAN",
    "dean_mp": "DEMO_PASSWORD_DEAN_MP",
    "teacher": "DEMO_PASSWORD_TEACHER",
    "admin": "DEMO_PASSWORD_ADMIN",
}
USERNAMES = {"student1": "student1", "student2": "student2", "dean": "dean", "dean_mp": "dean.mp",
             "teacher": "teacher", "admin": "admin"}  # fmt: skip


def _generate_password() -> str:
    """Случайный пароль, который удобно продиктовать: campus-xxxx-xxxx-xxxx."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    parts = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "campus-" + "-".join(parts)


def resolve_demo_passwords(previous: dict[str, str] | None = None) -> tuple[dict[str, str], list[str]]:
    """Пароли из окружения, затем из прежнего файла; недостающие генерируются.

    Возвращает (пароли, какие сгенерированы).
    """
    previous = previous or {}
    passwords, generated = {}, []
    for key, env_name in DEMO_KEYS.items():
        value = os.environ.get(env_name, "").strip() or previous.get(USERNAMES[key], "")
        if not value:
            value = _generate_password()
            generated.append(key)
        passwords[key] = value
    return passwords, generated


def _credentials_path() -> Path:
    return Path(current_app.instance_path) / "demo_credentials.json"


def register_cli(app: Flask) -> None:
    @app.cli.command("seed")
    @click.option("--reset", is_flag=True, help="Удалить ВСЕ данные и создать демо-набор заново.")
    @click.option("--yes", is_flag=True, help="Не спрашивать подтверждение при --reset.")
    @click.option(
        "--keep-passwords",
        is_flag=True,
        help="Взять пароли из прежнего instance/demo_credentials.json: выданные жюри логины не сменятся.",
    )
    def seed(reset: bool, yes: bool, keep_passwords: bool) -> None:
        """Наполнить пустую базу вымышленными демо-данными."""
        from .seeds.builder import seed_demo

        existing = db.session.execute(select(func.count()).select_from(User)).scalar_one()
        if existing and not reset:
            raise click.ClickException("В базе уже есть данные. Для пересоздания: flask seed --reset")
        if existing and reset:
            if not yes:
                click.confirm("Будут удалены все пользователи, заявки и вложения. Продолжить?", abort=True)
            tables = ", ".join(f'"{t.name}"' for t in db.metadata.sorted_tables)
            db.session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))  # noqa: S608
            db.session.commit()

        previous = {}
        if keep_passwords and _credentials_path().is_file():
            previous = json.loads(_credentials_path().read_text(encoding="utf-8"))
        passwords, generated = resolve_demo_passwords(previous)
        summary = seed_demo(passwords)
        db.session.commit()

        # Пароли не печатаются в консоль и не попадают в Git: файл лежит в instance/ с правами 600.
        path = _credentials_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {USERNAMES[key]: value for key, value in passwords.items()}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        path.chmod(0o600)

        click.echo(f"Готово: пользователей {summary['users']}, занятий {summary['lessons']}.")
        click.echo(f"Логины и пароли демо-аккаунтов: {path}")
        if generated:
            click.echo("Пароли сгенерированы случайно (в окружении не заданы): " + ", ".join(generated))

    demo_group = AppGroup("demo", help="Обслуживание демо-стенда.")

    @demo_group.command("refresh")
    def demo_refresh() -> None:
        """Обновить «живые» события: свежий перенос занятия и напоминания о дедлайнах."""
        from .seeds.builder import load_course_plans
        from .services.demo import refresh_demo_state

        load_course_plans()
        result = refresh_demo_state()
        db.session.commit()
        click.echo(json.dumps(result, ensure_ascii=False))

    app.cli.add_command(demo_group)
