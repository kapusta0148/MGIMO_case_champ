"""Все модели в одном месте, чтобы Alembic видел полную схему."""

from .academics import Assessment, Course, Deadline, ExamEvent, Lesson, Subject, Teacher, Term
from .comms import Announcement, Notification
from .org import Faculty, Program, StudyGroup
from .requests import Attachment, RequestEvent, ServiceRequest
from .system import AppState, AuditEvent, RateLimitEvent
from .user import AuthSession, StaffProfile, StaffScope, StudentProfile, User

__all__ = [
    "Announcement",
    "AppState",
    "Assessment",
    "Attachment",
    "AuditEvent",
    "AuthSession",
    "Course",
    "Deadline",
    "ExamEvent",
    "Faculty",
    "Lesson",
    "Notification",
    "Program",
    "RateLimitEvent",
    "RequestEvent",
    "ServiceRequest",
    "StaffProfile",
    "StaffScope",
    "StudentProfile",
    "StudyGroup",
    "Subject",
    "Teacher",
    "Term",
    "User",
]
