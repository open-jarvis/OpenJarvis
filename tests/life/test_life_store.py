"""Tests for the personal-progress store (habits, journal, focus, missions)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from openjarvis.life.store import LifeStore

TODAY = date(2026, 11, 15)


def d(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


@pytest.fixture
def store(tmp_path):
    s = LifeStore(tmp_path / "life.db")
    yield s
    s.close()


# ---- habits -----------------------------------------------------------------


def test_add_and_list_habits(store):
    a = store.add_habit("Morning routine", time="06:00")
    store.add_habit("Read 20 pages", time="20:30")
    habits = store.list_habits()
    assert [h["name"] for h in habits] == ["Morning routine", "Read 20 pages"]
    assert habits[0]["time"] == "06:00"
    assert a["id"]


def test_habit_name_is_required(store):
    with pytest.raises(ValueError):
        store.add_habit("   ")


def test_bad_time_is_rejected(store):
    with pytest.raises(ValueError):
        store.add_habit("Workout", time="25:99")


def test_check_and_uncheck_a_habit(store):
    h = store.add_habit("Workout")
    store.set_done(h["id"], TODAY.isoformat(), True)
    assert store.list_habits(day=TODAY.isoformat())[0]["done"] is True
    store.set_done(h["id"], TODAY.isoformat(), False)
    assert store.list_habits(day=TODAY.isoformat())[0]["done"] is False


def test_find_habit_by_partial_name(store):
    store.add_habit("Read 20 pages")
    assert store.find_habit("read")["name"] == "Read 20 pages"
    assert store.find_habit("swim") is None


def test_archived_habits_are_hidden(store):
    h = store.add_habit("Old habit")
    store.archive_habit(h["id"])
    assert store.list_habits() == []


def test_unknown_habit_raises(store):
    with pytest.raises(KeyError):
        store.set_done("nope", TODAY.isoformat(), True)


# ---- journal and focus --------------------------------------------------------


def test_journal_entries_by_day(store):
    store.add_journal("Discipline is showing up anyway.", day=d(0))
    store.add_journal("Yesterday's note", day=d(-1))
    entries = store.list_journal(start=d(0), end=d(0))
    assert [e["text"] for e in entries] == ["Discipline is showing up anyway."]


def test_empty_journal_entry_rejected(store):
    with pytest.raises(ValueError):
        store.add_journal("  ")


def test_focus_sessions_add_up(store):
    store.add_focus(25, label="Deep work", day=d(0))
    store.add_focus(50, day=d(0))
    assert store.summary(today=d(0))["stats"]["focus_hours"] == pytest.approx(1.25)


def test_focus_minutes_must_be_positive(store):
    with pytest.raises(ValueError):
        store.add_focus(0)


# ---- summary ----------------------------------------------------------------


def test_streak_counts_consecutive_active_days(store):
    h = store.add_habit("Meditate")
    for offset in (0, -1, -2, -4):  # gap at -3
        store.set_done(h["id"], d(offset), True)
    assert store.summary(today=d(0))["streak"] == 3


def test_streak_survives_until_today_is_done(store):
    """Yesterday's streak still counts while today has no activity yet."""
    h = store.add_habit("Meditate")
    store.set_done(h["id"], d(-1), True)
    store.set_done(h["id"], d(-2), True)
    assert store.summary(today=d(0))["streak"] == 2


def test_progress_and_weekly_completion(store):
    a = store.add_habit("A")
    store.add_habit("B")
    store.set_done(a["id"], d(0), True)
    s = store.summary(today=d(0))
    week = s["week"]
    assert len(week) == 7
    assert week[-1] == {"day": d(0), "percent": 50}
    assert set(s["progress"]) == {"overall", "discipline", "habits", "mindset", "focus"}
    assert 0 <= s["progress"]["overall"] <= 100
    assert s["today"]["habits_total"] == 2
    assert s["today"]["habits_done"] == 1


def test_level_grows_with_activity(store):
    before = store.summary(today=d(0))["level"]
    h = store.add_habit("A")
    for offset in range(0, -20, -1):
        store.set_done(h["id"], d(offset), True)
    store.add_focus(300, day=d(0))
    after = store.summary(today=d(0))
    assert after["level"] > before
    assert 0 <= after["level_progress"] <= 100


def test_empty_store_summary(store):
    s = store.summary(today=d(0))
    assert s["streak"] == 0
    assert s["stats"] == {"days": 0, "habits": 0, "focus_hours": 0.0}
    assert s["progress"]["overall"] == 0


# ---- profile, mission, bookmarks -----------------------------------------------


def test_profile_defaults_and_update(store):
    assert store.profile()["name"]
    store.update_profile(name="Noufal", motto="Focus. Discipline. Freedom.")
    assert store.profile() == {"name": "Noufal", "motto": "Focus. Discipline. Freedom."}


def test_mission_roadmap(store):
    m = store.set_mission(
        "Become unstoppable", ["Foundation", "Consistency", "Mindset"]
    )
    assert m["stage"] == 0 and m["percent"] == 0
    m = store.advance_mission()
    assert m["stage"] == 1
    assert m["percent"] == 33
    store.advance_mission()
    m = store.advance_mission()
    assert m["stage"] == 3 and m["percent"] == 100
    assert store.advance_mission()["stage"] == 3  # no overflow


def test_mission_needs_stages(store):
    with pytest.raises(ValueError):
        store.set_mission("x", [])


def test_quote_bookmarks(store):
    store.bookmark("Sacrifice today, freedom tomorrow.", True)
    assert store.bookmarks() == ["Sacrifice today, freedom tomorrow."]
    store.bookmark("Sacrifice today, freedom tomorrow.", False)
    assert store.bookmarks() == []
