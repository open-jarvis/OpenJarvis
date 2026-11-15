"""Tests for the habit / journal tools Jarvis uses from chat and voice."""

from __future__ import annotations

from datetime import date

import pytest

from openjarvis.life.store import LifeStore
from openjarvis.tools.life_tools import (
    AddHabitTool,
    CompleteHabitTool,
    ListHabitsTool,
    WriteJournalTool,
)


@pytest.fixture
def store(tmp_path, monkeypatch):
    import openjarvis.tools.life_tools as lt

    s = LifeStore(tmp_path / "life.db")
    monkeypatch.setattr(lt, "_store", lambda: s)
    yield s
    s.close()


def test_add_habit(store):
    r = AddHabitTool().execute(name="Workout", time="18:00")
    assert r.success
    assert "Workout" in r.content
    assert store.list_habits()[0]["time"] == "18:00"


def test_add_habit_rejects_bad_time(store):
    r = AddHabitTool().execute(name="Workout", time="6pm")
    assert not r.success
    assert "06:30" in r.content


def test_complete_habit_by_name(store):
    store.add_habit("Read 20 pages")
    r = CompleteHabitTool().execute(habit="read")
    assert r.success
    today = date.today().isoformat()
    assert store.list_habits(day=today)[0]["done"] is True


def test_complete_unknown_habit_lists_the_real_ones(store):
    store.add_habit("Meditate")
    r = CompleteHabitTool().execute(habit="swim")
    assert not r.success
    assert "Meditate" in r.content


def test_list_habits_shows_today(store):
    h = store.add_habit("Meditate", time="22:00")
    store.set_done(h["id"], None, True)
    r = ListHabitsTool().execute()
    assert "[x] Meditate" in r.content
    assert "22:00" in r.content


def test_list_habits_when_none(store):
    assert "No habits" in ListHabitsTool().execute().content


def test_write_journal(store):
    r = WriteJournalTool().execute(text="Hard day, showed up anyway.")
    assert r.success
    today = date.today().isoformat()
    assert store.list_journal(today, today)[0]["text"] == "Hard day, showed up anyway."


def test_write_journal_needs_text(store):
    assert not WriteJournalTool().execute(text=" ").success
