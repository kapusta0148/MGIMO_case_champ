"""Профиль, «Сегодня», расписание с переносом, успеваемость — на данных двух студентов."""

from __future__ import annotations

from datetime import time, timedelta

import pytest
from sqlalchemy import select

from app import clock
from app.extensions import db
from app.models import Course, Lesson, Notification
from app.services import demo, schedule
from app.services.grades import grade_for, result_payload
from tests.conftest import FROZEN_NOW


def _moved_lesson_id(api) -> int:
    changes = api.get("/api/me/dashboard").get_json()["changes"]
    assert changes, "в демо-данных должен быть свежий перенос"
    return changes[0]["id"]


# ── Профиль ───────────────────────────────────────────────────────────────────


def test_profiles_show_own_fictional_data(mira, timur):
    first = mira.get("/api/me/profile").get_json()["user"]
    second = timur.get("/api/me/profile").get_json()["user"]

    assert first["fullName"] == "Северцева Мира Олеговна"
    assert first["student"]["faculty"]["code"] == "МО"
    assert first["student"]["program"]["name"] == "Международные отношения"
    assert (first["student"]["year"], first["student"]["group"]) == (2, "МО-2-03")

    assert second["fullName"] == "Ладожский Тимур Русланович"
    assert second["student"]["faculty"]["code"] == "МЭО"
    assert (second["student"]["year"], second["student"]["group"]) == (3, "МЭО-3-07")

    for key in ("fullName", "id", "username"):
        assert first[key] != second[key]
    assert first["isDemo"] and second["isDemo"]
    assert "passwordHash" not in first and "password_hash" not in first


# ── «Сегодня» ─────────────────────────────────────────────────────────────────


def test_today_screen_for_first_student(mira):
    data = mira.get("/api/me/dashboard").get_json()
    assert data["today"] == "2026-11-16" and data["weekday"] == "понедельник"
    assert data["firstName"] == "Мира"

    assert data["currentLesson"]["subject"]["name"] == "История международных отношений"
    nxt = data["nextLesson"]
    assert nxt["subject"]["name"] == "Теория международных отношений"
    assert nxt["startsAt"] == "2026-11-16T10:30:00+03:00"
    assert nxt["minutesUntil"] == 42 and nxt["isToday"] is True
    assert nxt["room"] == "3041" and nxt["teacher"]["shortName"] == "Корнилова Е. А."
    assert nxt["pairNumber"] == 2 and nxt["kindLabel"] == "Семинар"

    assert data["summary"]["lessonsToday"] == 3
    assert data["summary"]["changesToday"] == 1
    assert data["summary"]["deadlinesSoon"] == 1

    nearest = data["deadlines"][0]
    assert nearest["title"] == "Эссе «Типы политических режимов»"
    assert nearest["dueAt"] == "2026-11-17T23:59:00+03:00" and nearest["isSoon"] is True

    assert data["activeRequest"]["title"] == "Справка об обучении"
    assert data["activeRequest"]["status"] == "in_review"


def test_today_screens_differ_between_students(mira, timur):
    first = mira.get("/api/me/dashboard").get_json()
    second = timur.get("/api/me/dashboard").get_json()
    assert first["nextLesson"]["subject"]["name"] != second["nextLesson"]["subject"]["name"]
    assert first["activeRequest"]["id"] != second["activeRequest"]["id"]
    assert second["activeRequest"]["status"] == "needs_info"
    assert {d["id"] for d in first["deadlines"]}.isdisjoint({d["id"] for d in second["deadlines"]})


# ── Расписание и перенос ──────────────────────────────────────────────────────


def test_week_schedule_has_time_subject_room_teacher(mira):
    data = mira.get("/api/me/schedule").get_json()
    assert (data["from"], data["to"]) == ("2026-11-16", "2026-11-22")
    assert [d["weekdayShort"] for d in data["days"]] == ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
    assert data["days"][0]["isToday"] is True

    lessons = [lesson for day in data["days"] for lesson in day["lessons"]]
    assert len(lessons) == 16
    for lesson in lessons:
        assert lesson["startsAt"] < lesson["endsAt"]
        assert lesson["subject"]["name"] and lesson["room"] and lesson["teacher"]["name"]
        assert lesson["kindLabel"]
    assert data["days"][6]["lessons"] == []  # воскресенье — пустой день


def test_schedule_for_today_only(mira):
    data = mira.get("/api/me/schedule?from=2026-11-16&to=2026-11-16").get_json()
    assert len(data["days"]) == 1
    assert [lesson["pairNumber"] for lesson in data["days"][0]["lessons"]] == [1, 2, 4]


def test_sunday_defaults_to_next_week(mira):
    clock.freeze(FROZEN_NOW - timedelta(days=1))  # воскресенье, 15 ноября
    data = mira.get("/api/me/schedule").get_json()
    assert (data["from"], data["to"]) == ("2026-11-16", "2026-11-22")


def test_moved_lesson_is_visible_and_consistent_everywhere(mira):
    """Главный сценарий: «Сегодня», уведомление, занятие по ссылке и расписание показывают одно состояние."""
    dashboard = mira.get("/api/me/dashboard").get_json()
    change = dashboard["changes"][0]
    assert change["subject"]["name"] == "Английский язык"
    assert change["status"] == "moved"
    assert change["change"]["originalStartsAt"] == "2026-11-16T12:00:00+03:00"
    assert change["startsAt"] == "2026-11-16T14:00:00+03:00"
    assert change["change"]["originalRoom"] == "2112" and change["room"] != "2112"
    assert change["change"]["timeChanged"] and change["change"]["roomChanged"]
    assert change["change"]["reason"]

    notifications = mira.get("/api/me/notifications").get_json()["items"]
    note = next(n for n in notifications if n["kind"] == "lesson_change")
    assert note["read"] is False
    assert note["title"] == "Перенос занятия: Английский язык"
    assert note["link"] == {"type": "lesson", "id": change["id"], "date": "2026-11-16"}

    by_link = mira.get(f"/api/me/lessons/{note['link']['id']}").get_json()["lesson"]
    day = mira.get("/api/me/schedule?from=2026-11-16&to=2026-11-16").get_json()["days"][0]
    in_schedule = next(lesson for lesson in day["lessons"] if lesson["id"] == change["id"])

    # Одна и та же запись во всех четырёх местах.
    assert change == note["lesson"] == by_link == in_schedule
    assert change["change"]["summary"] in note["body"]
    # На старом месте в расписании виден след переноса.
    assert [lesson["id"] for lesson in day["movedAway"]] == [change["id"]]


def test_second_change_updates_same_notification(app, mira):
    lesson_id = _moved_lesson_id(mira)
    note_id = next(
        n["id"] for n in mira.get("/api/me/notifications").get_json()["items"] if n["kind"] == "lesson_change"
    )
    assert mira.patch(f"/api/me/notifications/{note_id}/read").status_code == 200

    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        day = clock.to_local(lesson.starts_at).date()
        schedule.reschedule_lesson(
            lesson,
            starts_at=clock.local_dt(day, time(15, 30)),
            ends_at=clock.local_dt(day, time(16, 50)),
            room="1126",
            reason="Аудитория освободилась позже.",
            actor=None,
        )
        db.session.commit()
        count = len(
            db.session.execute(
                select(Notification).where(
                    Notification.source_type == "lesson", Notification.source_id == lesson_id
                )
            ).all()
        )
        assert count == 1, "у единственного студента группы должно остаться одно уведомление о занятии"

    note = next(n for n in mira.get("/api/me/notifications").get_json()["items"] if n["id"] == note_id)
    assert note["read"] is False  # повторное изменение снова помечает уведомление непрочитанным
    assert note["lesson"]["startsAt"] == "2026-11-16T15:30:00+03:00" and note["lesson"]["room"] == "1126"
    # Исходное время не теряется при повторном переносе.
    assert note["lesson"]["change"]["originalStartsAt"] == "2026-11-16T12:00:00+03:00"
    assert "15:30–16:50, ауд. 1126" in note["body"]
    in_schedule = mira.get(f"/api/me/lessons/{lesson_id}").get_json()["lesson"]
    assert in_schedule == note["lesson"]


def test_move_to_another_day_leaves_trace_on_original_day(app, mira):
    lesson_id = _moved_lesson_id(mira)
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        tuesday = clock.to_local(lesson.starts_at).date() + timedelta(days=1)
        schedule.reschedule_lesson(
            lesson,
            starts_at=clock.local_dt(tuesday, time(9, 0)),
            ends_at=clock.local_dt(tuesday, time(10, 20)),
            room="2112",
            reason=None,
            actor=None,
        )
        db.session.commit()
    week = mira.get("/api/me/schedule").get_json()
    monday, tuesday_payload = week["days"][0], week["days"][1]
    assert lesson_id not in [lesson["id"] for lesson in monday["lessons"]]
    assert [lesson["id"] for lesson in monday["movedAway"]] == [lesson_id]
    moved = next(lesson for lesson in tuesday_payload["lessons"] if lesson["id"] == lesson_id)
    assert moved["change"]["dateChanged"] is True and moved["change"]["originalDate"] == "2026-11-16"
    assert lesson_id in [lesson["id"] for lesson in week["changes"]]


def test_reschedule_rejects_busy_slot_and_bad_input(app, mira):
    lesson_id = _moved_lesson_id(mira)
    with app.app_context():
        lesson = db.session.get(Lesson, lesson_id)
        day = clock.to_local(lesson.starts_at).date()
        with pytest.raises(Exception) as busy:
            schedule.reschedule_lesson(
                lesson,
                starts_at=clock.local_dt(day, time(10, 30)),  # в это время стоит ТМО
                ends_at=clock.local_dt(day, time(11, 50)),
                room="2112",
                reason=None,
                actor=None,
            )
        assert busy.value.fields == {"startsAt": "В это время у группы уже стоит другое занятие."}
        with pytest.raises(Exception) as bad:
            schedule.reschedule_lesson(
                lesson,
                starts_at=clock.local_dt(day, time(17, 0)),
                ends_at=clock.local_dt(day, time(16, 0)),
                room=" ",
                reason=None,
                actor=None,
            )
        assert set(bad.value.fields) == {"room", "endsAt"}
        db.session.rollback()


def test_cancelled_lesson_is_skipped_as_next(app, mira):
    with app.app_context():
        lesson = db.session.execute(
            select(Lesson)
            .join(Course)
            .where(Lesson.starts_at == clock.local_dt(FROZEN_NOW.date(), time(10, 30)), Course.group_id == 1)
        ).scalar_one()
        schedule.cancel_lesson(lesson, reason="Болезнь преподавателя.", actor=None)
        db.session.commit()
        cancelled_id = lesson.id
    data = mira.get("/api/me/dashboard").get_json()
    assert data["nextLesson"]["id"] != cancelled_id
    assert data["summary"]["lessonsToday"] == 2
    cancelled = next(c for c in data["changes"] if c["id"] == cancelled_id)
    assert cancelled["status"] == "cancelled" and cancelled["change"]["type"] == "cancelled"
    note = next(
        n
        for n in mira.get("/api/me/notifications").get_json()["items"]
        if n["link"] and n["link"].get("id") == cancelled_id and n["kind"] == "lesson_change"
    )
    assert note["title"].startswith("Занятие отменено")


@pytest.mark.parametrize(
    "query",
    ["from=16.11.2026", "from=2026-11-20&to=2026-11-16", "from=2026-09-01&to=2026-12-31"],
)
def test_schedule_rejects_bad_ranges(mira, query):
    response = mira.get(f"/api/me/schedule?{query}")
    assert response.status_code == 422
    assert response.get_json()["error"]["code"] == "validation_error"


def test_students_have_different_schedules(mira, timur):
    first = mira.get("/api/me/schedule").get_json()
    second = timur.get("/api/me/schedule").get_json()
    ids_first = {lesson["id"] for day in first["days"] for lesson in day["lessons"]}
    ids_second = {lesson["id"] for day in second["days"] for lesson in day["lessons"]}
    assert ids_first and ids_second and ids_first.isdisjoint(ids_second)


def test_demo_refresh_is_idempotent(app):
    with app.app_context():
        first = demo.refresh_demo_state()
        db.session.commit()
        assert first["movedLessons"] == [] and first["deadlineReminders"] == 0
        moved = db.session.execute(select(Lesson).where(Lesson.status == "moved")).scalars().all()
        assert len(moved) == 2  # по одному свежему переносу на группу


def test_demo_refresh_creates_new_move_on_later_day(app, mira):
    clock.freeze(FROZEN_NOW + timedelta(days=3))  # четверг
    with app.app_context():
        result = demo.refresh_demo_state()
        db.session.commit()
        assert len(result["movedLessons"]) == 2
    changes = mira.get("/api/me/dashboard").get_json()["changes"]
    assert any(c["date"] >= "2026-11-19" for c in changes)


# ── Успеваемость ──────────────────────────────────────────────────────────────


def test_grade_scale_boundaries():
    assert grade_for(100)[:2] == ("A", 5) and grade_for(90)[:2] == ("A", 5)
    assert grade_for(89)[:2] == ("B", 4) and grade_for(75)[:2] == ("C", 4)
    assert grade_for(74)[:2] == ("D", 3) and grade_for(60)[:2] == ("E", 3)
    assert grade_for(59)[:2] == ("F", 2) and grade_for(0)[:2] == ("F", 2)
    assert result_payload(60, "credit") == {
        "type": "credit", "score": 60, "letter": "E", "passed": True, "label": "зачтено"}  # fmt: skip
    assert result_payload(59, "credit")["label"] == "не зачтено"
    assert result_payload(91, "exam")["mark"] == 5
    assert result_payload(None, "exam") is None


def test_grades_distinguish_mark_credit_and_expected(mira):
    data = mira.get("/api/me/grades").get_json()
    current = data["currentTerm"]
    assert current["title"] == "Осенний семестр 2026/27" and current["session"]["state"] == "upcoming"
    assert len(current["courses"]) == 8

    forms = {c["subject"]["name"]: c["controlFormLabel"] for c in current["courses"]}
    assert forms["Политология"] == "Экзамен"
    assert forms["Философия"] == "Зачёт"
    assert forms["Английский язык"] == "Зачёт с оценкой"

    for course in current["courses"]:
        # Итог семестра ещё впереди: дата известна, результата нет.
        assert course["final"]["status"] == "expected" and course["final"]["result"] is None
        assert course["final"]["startsAt"] and course["final"]["room"]
        statuses = {c["status"] for c in course["controls"]}
        assert statuses == {"graded", "expected"}
        for control in course["controls"]:
            assert (control["score"] is not None) == (control["status"] == "graded")
        graded = [c["score"] for c in course["controls"] if c["status"] == "graded"]
        assert course["currentScore"] == round(sum(graded) / len(graded))

    past = data["pastTerms"][0]
    assert past["session"]["state"] == "closed"
    types = {c["subject"]["name"]: c["final"]["result"]["type"] for c in past["courses"]}
    assert types["Всемирная история"] == "mark" and types["Французский язык"] == "credit"
    assert past["summary"]["debts"] == [] and past["summary"]["retaken"] == []


def test_grades_differ_between_students(mira, timur):
    first = mira.get("/api/me/grades").get_json()
    second = timur.get("/api/me/grades").get_json()

    subjects_first = {c["subject"]["name"] for c in first["currentTerm"]["courses"]}
    subjects_second = {c["subject"]["name"] for c in second["currentTerm"]["courses"]}
    assert subjects_first != subjects_second

    assert (
        first["currentTerm"]["summary"]["averageCurrentScore"]
        > second["currentTerm"]["summary"]["averageCurrentScore"]
    )
    assert first["currentTerm"]["summary"]["atRisk"] == []
    assert second["currentTerm"]["summary"]["atRisk"] == ["Эконометрика"]
    assert second["pastTerms"][0]["summary"]["retaken"] == ["Статистика"]
    statistics = next(c for c in second["pastTerms"][0]["courses"] if c["subject"]["name"] == "Статистика")
    assert statistics["final"]["retakes"] == 1 and statistics["final"]["result"]["mark"] == 3


def test_demo_refresh_finds_move_on_saturday_evening(app, timur):
    """Жюри может открыть кабинет в выходные: перенос должен найтись на ближайший учебный день."""
    clock.freeze(clock.local_dt(FROZEN_NOW.date() + timedelta(days=5), time(18, 0)))  # суббота, 21 ноября
    with app.app_context():
        result = demo.refresh_demo_state()
        db.session.commit()
        assert len(result["movedLessons"]) == 2
    changes = timur.get("/api/me/dashboard").get_json()["changes"]
    assert changes and all(c["date"] == "2026-11-23" for c in changes)  # понедельник
