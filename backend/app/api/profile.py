"""Представление пользователя для клиента. Пароли, хеши и служебные поля сюда не попадают."""

from __future__ import annotations

from ..models import User
from ..models.user import ROLE_LABELS


def initials(full_name: str) -> str:
    """«Северцева Мира Олеговна» -> «МС» (имя + фамилия)."""
    parts = full_name.split()
    if len(parts) >= 2:
        return (parts[1][0] + parts[0][0]).upper()
    return full_name[:2].upper()


def user_payload(user: User) -> dict:
    payload = {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "roleLabel": ROLE_LABELS[user.role],
        "fullName": user.full_name,
        "initials": initials(user.full_name),
        "isDemo": True,  # в прототипе все профили демонстрационные
        "isGenerated": user.is_generated,
        "student": None,
        "staff": None,
    }
    if user.student is not None:
        group = user.student.group
        program = group.program
        faculty = program.faculty
        payload["student"] = {
            "faculty": {"code": faculty.code, "name": faculty.name},
            "program": {"code": program.code, "name": program.name, "degree": program.degree},
            "year": group.year,
            "group": group.name,
            "admissionYear": group.admission_year,
            "recordBook": user.student.record_book,
        }
    if user.staff is not None:
        payload["staff"] = {
            "position": user.staff.position,
            "faculties": [
                {"code": scope.faculty.code, "name": scope.faculty.name} for scope in user.staff.scopes
            ],
        }
    return payload
