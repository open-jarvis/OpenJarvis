"""Tests for the /v1/life API used by the Jarvis home screen."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.life.store import LifeStore

DAY = "2026-11-15"


@pytest.fixture
def client(tmp_path, monkeypatch):
    import openjarvis.server.life_routes as lr

    store = LifeStore(tmp_path / "life.db")
    monkeypatch.setattr(lr, "get_life_store", lambda: store)
    app = FastAPI()
    app.include_router(lr.router)
    yield TestClient(app)
    store.close()


def test_habit_lifecycle(client):
    r = client.post("/v1/life/habits", json={"name": "Deep work", "time": "08:00"})
    assert r.status_code == 200
    habit = r.json()

    r = client.post(
        f"/v1/life/habits/{habit['id']}/check", json={"day": DAY, "done": True}
    )
    assert r.status_code == 200

    habits = client.get("/v1/life/habits", params={"day": DAY}).json()["habits"]
    assert habits == [{**habit, "done": True}]

    assert client.delete(f"/v1/life/habits/{habit['id']}").status_code == 200
    assert client.get("/v1/life/habits").json()["habits"] == []


def test_invalid_habit_is_a_400(client):
    assert client.post("/v1/life/habits", json={"name": " "}).status_code == 400
    r = client.post("/v1/life/habits", json={"name": "x", "time": "99:00"})
    assert r.status_code == 400


def test_unknown_habit_is_a_404(client):
    r = client.post("/v1/life/habits/nope/check", json={"day": DAY, "done": True})
    assert r.status_code == 404


def test_journal_and_summary(client):
    client.post("/v1/life/journal", json={"text": "Showed up anyway.", "day": DAY})
    entries = client.get("/v1/life/journal", params={"start": DAY, "end": DAY}).json()
    assert [e["text"] for e in entries["entries"]] == ["Showed up anyway."]

    client.post("/v1/life/focus", json={"minutes": 30, "day": DAY})
    s = client.get("/v1/life/summary", params={"today": DAY}).json()
    assert s["streak"] == 1
    assert s["stats"]["focus_hours"] == 0.5


def test_bad_date_is_a_400(client):
    assert client.get("/v1/life/summary", params={"today": "15/11"}).status_code == 400


def test_profile_mission_and_bookmarks(client):
    r = client.put("/v1/life/profile", json={"name": "Noufal"})
    assert r.json()["name"] == "Noufal"

    r = client.put(
        "/v1/life/mission",
        json={"title": "Become unstoppable", "stages": ["Foundation", "Builder"]},
    )
    assert r.json()["stage"] == 0
    assert client.post("/v1/life/mission/advance").json()["percent"] == 50

    client.post("/v1/life/bookmarks", json={"quote": "Keep building.", "saved": True})
    assert client.get("/v1/life/bookmarks").json()["quotes"] == ["Keep building."]


def test_advance_without_mission_is_a_404(client):
    assert client.post("/v1/life/mission/advance").status_code == 404
