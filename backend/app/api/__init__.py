"""Регистрация маршрутов API."""

from __future__ import annotations

from flask import Blueprint, Flask, current_app, g, jsonify, request
from sqlalchemy import text

from ..extensions import db
from ..security.auth import login_required
from ..services import demo
from ..services import requests as request_service

meta = Blueprint("meta", __name__, url_prefix="/api")


@meta.get("/health")
def health():
    """Проверка живости для мониторинга: приложение отвечает и база доступна."""
    db.session.execute(text("select 1"))
    return jsonify({"status": "ok"})


@meta.get("/meta/request-types")
@login_required
def request_types():
    return jsonify({"items": request_service.types_payload()})


def register_blueprints(app: Flask) -> None:
    from . import auth, me

    app.register_blueprint(meta)
    app.register_blueprint(auth.bp)
    app.register_blueprint(me.bp)

    @app.before_request
    def keep_demo_fresh() -> None:
        # После определения пользователя: раз в сутки обновляем демо-события (перенос, напоминания).
        if (
            current_app.config["DEMO_AUTO_REFRESH"]
            and g.get("current_user") is not None
            and request.path.startswith("/api/")
        ):
            demo.refresh_if_stale()
