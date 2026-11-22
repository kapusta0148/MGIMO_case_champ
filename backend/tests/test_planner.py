"""Планировщик и личные задачи: блоки только в свободное время, объяснения, явное подтверждение, права."""

from __future__ import annotations

from datetime import datetime, time, timedelta

import pytest

from app import clock
from tests.conftest import FROZEN_NOW


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _busy(api, dates: list[str]) -> list[tuple[datetime, datetime]]:
    schedule = api.get(f"/api/me/schedule?from={dates[0]}&to={dates[-1]}").get_json()
    return [
        (_dt(lesson["startsAt"]), _dt(lesson["endsAt"]) + timedelta(minutes=10))
        for day in schedule["days"]
        for lesson in day["lessons"]
        if lesson["status"] != "cancelled"
    ]


def test_blocks_fit_free_time_and_deadlines(mira):
    plan = mira.get("/api/me/planner").get_json()
    assert plan["method"] == "rules" and len(plan["rules"]) >= 4
    blocks = plan["blocks"]
    assert blocks, "у студента есть дедлайны — должны быть предложения"
    busy = _busy(mira, [d["date"] for d in plan["days"]])
    for block in blocks:
        start, end, due = _dt(block["startsAt"]), _dt(block["endsAt"]), _dt(block["dueAt"])
        assert start >= FROZEN_NOW and end > start
        assert 15 <= block["minutes"] <= 120
        assert end <= due - timedelta(hours=1), block
        local = clock.to_local(start)
        assert time(9, 0) <= local.time() and clock.to_local(end).time() <= time(21, 0)
        assert local.minute % 15 == 0
        for b_start, b_end in busy:
            assert end <= b_start or start >= b_end, f"блок пересекается с парой: {block['title']}"
        assert block["reasons"] and block["reasons"][0].startswith("Срок — ")
    ordered = sorted((_dt(b["startsAt"]), _dt(b["endsAt"])) for b in blocks)
    for (_, prev_end), (next_start, _) in zip(ordered, ordered[1:], strict=False):
        assert next_start >= prev_end, "блоки не должны пересекаться"


def test_earliest_deadline_goes_first_and_plan_is_stable(mira):
    first = mira.get("/api/me/planner").get_json()
    assert first["blocks"][0]["title"].startswith("Эссе «Типы политических режимов»")
    # Окно 12:00–14:00 освободилось из-за переноса английского — алгоритм его использует.
    assert first["blocks"][0]["startsAt"] == "2026-11-16T12:00:00+03:00"
    assert "окно между парами" in " ".join(first["blocks"][0]["reasons"])
    assert mira.get("/api/me/planner").get_json() == first


def test_accepting_block_requires_explicit_action_and_is_idempotent(mira):
    plan = mira.get("/api/me/planner").get_json()
    assert mira.get("/api/me/tasks").get_json()["items"] == []  # сам по себе планировщик ничего не создаёт
    block = plan["blocks"][0]
    payload = {
        "title": block["title"],
        "plannedStart": block["startsAt"],
        "plannedEnd": block["endsAt"],
        "deadlineId": block["deadlineId"],
        "sourceKey": block["key"],
    }
    created = mira.post("/api/me/tasks", json=payload)
    assert created.status_code == 201 and created.get_json()["task"]["fromPlanner"] is True
    again = mira.post("/api/me/tasks", json=payload)
    assert again.status_code == 200 and again.get_json()["created"] is False
    assert len(mira.get("/api/me/tasks").get_json()["items"]) == 1

    after = mira.get("/api/me/planner").get_json()
    assert block["key"] not in [b["key"] for b in after["blocks"]]
    accepted = (_dt(block["startsAt"]), _dt(block["endsAt"]))
    for b in after["blocks"]:
        assert _dt(b["endsAt"]) <= accepted[0] or _dt(b["startsAt"]) >= accepted[1]
    same_deadline = lambda p: sum(b["minutes"] for b in p["blocks"] if b["deadlineId"] == block["deadlineId"])  # noqa: E731
    assert same_deadline(after) == same_deadline(plan) - block["minutes"]


def test_warns_when_deadline_cannot_fit(mira):
    clock.freeze(
        clock.local_dt(FROZEN_NOW.date() + timedelta(days=1), time(21, 30))
    )  # вт 21:30, эссе до 23:59
    plan = mira.get("/api/me/planner").get_json()
    texts = [w["text"] for w in plan["warnings"] if w["type"] == "not_enough_time"]
    assert any("Типы политических режимов" in t and "не хватает 3 ч" in t for t in texts), texts


def test_same_day_and_at_risk_warnings(mira, timur):
    task = {"title": "Подготовить презентацию для клуба", "dueAt": "2026-11-19T20:00", "estimatedMinutes": 60}
    assert mira.post("/api/me/tasks", json=task).status_code == 201
    plan = mira.get("/api/me/planner").get_json()
    same_day = [w["text"] for w in plan["warnings"] if w["type"] == "same_day"]
    assert (
        same_day
        and "Перевод аналитической статьи" in same_day[0]
        and "Подготовить презентацию" in same_day[0]
    )
    assert any(b["taskId"] is not None for b in plan["blocks"])  # личная задача тоже раскладывается
    assert not [w for w in plan["warnings"] if w["type"] == "at_risk"]

    risky = timur.get("/api/me/planner").get_json()
    assert [w["text"][:14] for w in risky["warnings"] if w["type"] == "at_risk"] == ["«Эконометрика»"]
    econ = [b for b in risky["blocks"] if b["subject"] == "Эконометрика"]
    assert econ and all(b["atRisk"] for b in econ)


def test_completed_task_counts_toward_deadline(mira):
    plan = mira.get("/api/me/planner").get_json()
    block = plan["blocks"][0]
    task = mira.post(
        "/api/me/tasks",
        json={"title": "Эссе готово", "deadlineId": block["deadlineId"], "estimatedMinutes": 180},
    ).get_json()["task"]
    assert (
        mira.patch(f"/api/me/tasks/{task['id']}", json={"completed": True}).get_json()["task"]["completed"]
        is True
    )
    after = mira.get("/api/me/planner").get_json()
    assert block["deadlineId"] not in [b["deadlineId"] for b in after["blocks"]]


# ── Личные задачи: проверки ввода и права ─────────────────────────────────────


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"title": ""}, "title"),
        ({"title": "x" * 161}, "title"),
        ({"title": "Задача", "estimatedMinutes": 0}, "estimatedMinutes"),
        ({"title": "Задача", "estimatedMinutes": "час"}, "estimatedMinutes"),
        ({"title": "Задача", "dueAt": "завтра"}, "dueAt"),
        ({"title": "Задача", "dueAt": "2030-01-01T10:00"}, "dueAt"),
        ({"title": "Задача", "plannedStart": "2026-11-17T12:00"}, "plannedEnd"),
        (
            {"title": "Задача", "plannedStart": "2026-11-17T12:00", "plannedEnd": "2026-11-17T11:00"},
            "plannedEnd",
        ),
        ({"title": "Задача", "deadlineId": 999999}, "deadlineId"),
        ({"title": "Задача", "sourceKey": ""}, "sourceKey"),
    ],
)
def test_task_validation(mira, payload, field):
    response = mira.post("/api/me/tasks", json=payload)
    assert response.status_code == 422 and field in response.get_json()["error"]["fields"]


def test_foreign_deadline_cannot_be_linked(mira, timur):
    foreign = timur.get("/api/me/deadlines").get_json()["items"][0]["id"]
    response = mira.post("/api/me/tasks", json={"title": "Чужой дедлайн", "deadlineId": foreign})
    assert response.status_code == 422


def test_tasks_are_private(mira, timur):
    task = mira.post("/api/me/tasks", json={"title": "Личное дело Миры"}).get_json()["task"]
    assert timur.get("/api/me/tasks").get_json()["items"] == []
    assert timur.patch(f"/api/me/tasks/{task['id']}", json={"completed": True}).status_code == 404
    assert (
        timur.client.delete(f"/api/me/tasks/{task['id']}", headers={"X-CSRF-Token": timur.token}).status_code
        == 404
    )
    assert mira.get("/api/me/tasks").get_json()["items"][0]["completed"] is False

    deleted = mira.client.delete(f"/api/me/tasks/{task['id']}", headers={"X-CSRF-Token": mira.token})
    assert deleted.status_code == 200 and mira.get("/api/me/tasks").get_json()["items"] == []
    assert mira.client.delete(f"/api/me/tasks/{task['id']}").status_code == 403  # без CSRF


@pytest.mark.parametrize("url", ["/api/me/planner", "/api/me/tasks"])
def test_planner_access(anon, dean, url):
    assert anon.get(url).status_code == 401
    assert dean.get(url).status_code == 403
