"""Единый формат ошибок API.

{"error": {"code": "not_found", "message": "…", "fields": {...}}, "requestId": "…"}

Сообщения безопасны для показа пользователю; подробности пишутся только в серверный лог.
"""

from __future__ import annotations

import logging

from flask import Flask, g, jsonify, request
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

log = logging.getLogger("campus")


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        *,
        fields: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields
        self.headers = headers or {}


def unauthorized() -> ApiError:
    return ApiError(401, "unauthorized", "Войдите в кабинет, чтобы продолжить.")


def forbidden() -> ApiError:
    return ApiError(403, "forbidden", "Недостаточно прав для этого действия.")


def not_found(message: str = "Запись не найдена.") -> ApiError:
    return ApiError(404, "not_found", message)


def validation_error(fields: dict[str, str], message: str = "Проверьте заполнение формы.") -> ApiError:
    return ApiError(422, "validation_error", message, fields=fields)


def error_response(status: int, code: str, message: str, fields=None, headers=None):
    payload = {"error": {"code": code, "message": message}, "requestId": g.get("request_id")}
    if fields:
        payload["error"]["fields"] = fields
    response = jsonify(payload)
    response.status_code = status
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


_HTTP_MESSAGES = {
    400: ("bad_request", "Некорректный запрос."),
    404: ("not_found", "Страница или запись не найдена."),
    405: ("method_not_allowed", "Метод не поддерживается."),
    413: ("payload_too_large", "Слишком большой запрос или файл."),
    415: ("unsupported_media_type", "Неподдерживаемый формат данных."),
    429: ("rate_limited", "Слишком много запросов. Попробуйте позже."),
}


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.status, err.code, err.message, err.fields, err.headers)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(err: CSRFError):
        return error_response(
            403, "csrf_failed", "Сессия формы устарела. Обновите страницу и повторите действие."
        )

    @app.errorhandler(HTTPException)
    def handle_http_error(err: HTTPException):
        status = err.code or 500
        code, message = _HTTP_MESSAGES.get(status, ("http_error", "Запрос не выполнен."))
        if not request.path.startswith("/api/") and status == 404:
            # Не-API адреса обслуживает SPA; сюда попадаем, только если сборки фронтенда нет.
            message = "Страница не найдена."
        return error_response(status, code, message)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        # Трассировка остаётся в логе с идентификатором запроса и не уходит клиенту.
        log.exception("unhandled error request_id=%s path=%s", g.get("request_id"), request.path)
        return error_response(500, "internal_error", "Внутренняя ошибка. Мы уже разбираемся.")
