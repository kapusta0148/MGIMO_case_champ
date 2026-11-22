"""MGIMO Campus — конкурсный прототип (неофициальный сервис). Фабрика приложения Flask."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from flask import Flask, g, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config, select_config, validate_production
from .errors import error_response, register_error_handlers
from .extensions import csrf, db, migrate


def create_app(config_object: type[Config] | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config_object or select_config())
    validate_production(app.config)
    app.json.ensure_ascii = False

    if app.config["TRUST_PROXY"]:
        # Ровно один доверенный прокси (Caddy/Nginx на том же сервере).
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from . import models  # noqa: F401  (регистрация моделей)
    from .security import auth

    @app.before_request
    def assign_request_id() -> None:
        g.request_id = uuid.uuid4().hex[:16]

    auth.init_app(app)
    register_error_handlers(app)

    from .api import register_blueprints

    register_blueprints(app)

    from .cli import register_cli

    register_cli(app)

    @app.after_request
    def apply_security_headers(response):
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if request.path.startswith("/api/"):
            # Личные данные не должны оседать в кешах браузера и прокси.
            response.headers["Cache-Control"] = "no-store"
        else:
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
                "form-action 'self'; object-src 'none'",
            )
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response

    _register_frontend(app)
    return app


def _register_frontend(app: Flask) -> None:
    """Раздаём собранный React с того же origin, что и /api (если сборка есть)."""
    dist = Path(app.config["FRONTEND_DIST"])

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def spa(path: str):
        if path.startswith("api/"):
            return error_response(404, "not_found", "Такого адреса API нет.")
        if not dist.is_dir():
            return error_response(
                404, "frontend_not_built", "Сборка интерфейса не найдена. Выполните npm run build."
            )
        candidate = dist / path
        if path and candidate.is_file():
            response = send_from_directory(dist, path)
            if path.startswith("assets/"):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return response
        # Любой другой адрес — это маршрут внутри SPA.
        response = send_from_directory(dist, "index.html")
        response.headers["Cache-Control"] = "no-cache"
        return response
