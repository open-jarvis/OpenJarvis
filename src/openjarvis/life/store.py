"""Personal progress: habits, journal, focus sessions, a mission roadmap.

Backs the Jarvis home screen and the habit/journal tools. Everything lives in
one SQLite file (``~/.openjarvis/life.db``) on the user's PC. Days are local
``YYYY-MM-DD`` strings so a check-in belongs to the day the user saw.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_WEEK_DAYS = 7
_FOCUS_GOAL_MINUTES = 30  # per day, for the focus progress bar
_XP_PER_CHECKIN = 10
_XP_PER_JOURNAL = 15
_XP_PER_FOCUS_MINUTE = 0.4
_XP_PER_LEVEL = 100
_DEFAULT_PROFILE = {"name": "Commander", "motto": "Focus • Discipline • Freedom"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS habits (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, time TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS checkins (
    habit_id TEXT NOT NULL, day TEXT NOT NULL, PRIMARY KEY (habit_id, day));
CREATE TABLE IF NOT EXISTS journal (
    id TEXT PRIMARY KEY, day TEXT NOT NULL, created_at REAL NOT NULL,
    text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS focus (
    id TEXT PRIMARY KEY, day TEXT NOT NULL, minutes INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS bookmarks (quote TEXT PRIMARY KEY);
"""


def _today() -> str:
    return date.today().isoformat()


def _day(value: Optional[str]) -> str:
    day = value or _today()
    date.fromisoformat(day)  # raises ValueError on a bad date
    return day


def _pct(part: float, whole: float) -> int:
    return 0 if whole <= 0 else max(0, min(100, round(part / whole * 100)))


class LifeStore:
    def __init__(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(_SCHEMA)
            self._db.commit()

    def close(self) -> None:
        self._db.close()

    def _rows(self, sql: str, args: tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _write(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur.rowcount

    # ---- habits -----------------------------------------------------------------

    def add_habit(self, name: str, time: str = "") -> Dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("A habit needs a name.")
        time = (time or "").strip()
        if time and not _TIME.match(time):
            raise ValueError("Time must look like 06:30 (24-hour).")
        habit_id = uuid.uuid4().hex[:12]
        self._write(
            "INSERT INTO habits (id, name, time, created_at) VALUES (?, ?, ?, ?)",
            (habit_id, name[:80], time, _now()),
        )
        return {"id": habit_id, "name": name[:80], "time": time, "done": False}

    def list_habits(self, day: Optional[str] = None) -> List[Dict[str, Any]]:
        day = _day(day)
        rows = self._rows(
            "SELECT h.id, h.name, h.time, c.day IS NOT NULL AS done FROM habits h "
            "LEFT JOIN checkins c ON c.habit_id = h.id AND c.day = ? "
            "WHERE h.archived = 0 ORDER BY h.time = '', h.time, h.created_at",
            (day,),
        )
        return [
            {
                "id": r["id"],
                "name": r["name"],
                "time": r["time"],
                "done": bool(r["done"]),
            }
            for r in rows
        ]

    def find_habit(self, query: str) -> Optional[Dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return None
        habits = self.list_habits()
        exact = [h for h in habits if h["name"].lower() == q]
        partial = [h for h in habits if q in h["name"].lower()]
        return (exact or partial or [None])[0]

    def set_done(self, habit_id: str, day: Optional[str], done: bool) -> None:
        day = _day(day)
        if not self._rows("SELECT 1 FROM habits WHERE id = ?", (habit_id,)):
            raise KeyError(habit_id)
        if done:
            self._write(
                "INSERT OR IGNORE INTO checkins (habit_id, day) VALUES (?, ?)",
                (habit_id, day),
            )
        else:
            self._write(
                "DELETE FROM checkins WHERE habit_id = ? AND day = ?", (habit_id, day)
            )

    def archive_habit(self, habit_id: str) -> None:
        if not self._write("UPDATE habits SET archived = 1 WHERE id = ?", (habit_id,)):
            raise KeyError(habit_id)

    # ---- journal and focus --------------------------------------------------------

    def add_journal(self, text: str, day: Optional[str] = None) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("A journal entry needs some text.")
        entry = {"id": uuid.uuid4().hex[:12], "day": _day(day), "created_at": _now()}
        self._write(
            "INSERT INTO journal (id, day, created_at, text) VALUES (?, ?, ?, ?)",
            (entry["id"], entry["day"], entry["created_at"], text[:5000]),
        )
        return {**entry, "text": text[:5000]}

    def list_journal(self, start: str, end: str) -> List[Dict[str, Any]]:
        rows = self._rows(
            "SELECT id, day, created_at, text FROM journal WHERE day BETWEEN ? AND ? "
            "ORDER BY day DESC, created_at DESC",
            (_day(start), _day(end)),
        )
        return [dict(r) for r in rows]

    def delete_journal(self, entry_id: str) -> None:
        if not self._write("DELETE FROM journal WHERE id = ?", (entry_id,)):
            raise KeyError(entry_id)

    def add_focus(
        self, minutes: int, label: str = "", day: Optional[str] = None
    ) -> Dict[str, Any]:
        minutes = int(minutes)
        if minutes <= 0 or minutes > 24 * 60:
            raise ValueError("Focus minutes must be between 1 and 1440.")
        entry = {"id": uuid.uuid4().hex[:12], "day": _day(day), "minutes": minutes}
        self._write(
            "INSERT INTO focus (id, day, minutes, label, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (entry["id"], entry["day"], minutes, (label or "")[:80], _now()),
        )
        return entry

    # ---- profile, mission, bookmarks ----------------------------------------------

    def _setting(self, key: str) -> Optional[str]:
        rows = self._rows("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def _set_setting(self, key: str, value: str) -> None:
        self._write(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def profile(self) -> Dict[str, str]:
        saved = json.loads(self._setting("profile") or "{}")
        return {**_DEFAULT_PROFILE, **saved}

    def update_profile(
        self, *, name: Optional[str] = None, motto: Optional[str] = None
    ):
        current = self.profile()
        if name is not None and name.strip():
            current["name"] = name.strip()[:40]
        if motto is not None:
            current["motto"] = motto.strip()[:80]
        self._set_setting("profile", json.dumps(current))
        return current

    def mission(self) -> Optional[Dict[str, Any]]:
        raw = self._setting("mission")
        if not raw:
            return None
        m = json.loads(raw)
        return {**m, "percent": _pct(m["stage"], len(m["stages"]))}

    def set_mission(self, title: str, stages: List[str]) -> Dict[str, Any]:
        stages = [s.strip()[:40] for s in stages if s and s.strip()][:8]
        if not (title or "").strip() or not stages:
            raise ValueError("A mission needs a title and at least one stage.")
        self._set_setting(
            "mission",
            json.dumps({"title": title.strip()[:80], "stages": stages, "stage": 0}),
        )
        return self.mission()  # type: ignore[return-value]

    def advance_mission(self) -> Dict[str, Any]:
        m = self.mission()
        if m is None:
            raise KeyError("mission")
        stage = min(m["stage"] + 1, len(m["stages"]))
        self._set_setting(
            "mission",
            json.dumps({"title": m["title"], "stages": m["stages"], "stage": stage}),
        )
        return self.mission()  # type: ignore[return-value]

    def bookmark(self, quote: str, saved: bool) -> None:
        quote = (quote or "").strip()[:300]
        if not quote:
            raise ValueError("Nothing to bookmark.")
        if saved:
            self._write("INSERT OR IGNORE INTO bookmarks (quote) VALUES (?)", (quote,))
        else:
            self._write("DELETE FROM bookmarks WHERE quote = ?", (quote,))

    def bookmarks(self) -> List[str]:
        return [r["quote"] for r in self._rows("SELECT quote FROM bookmarks")]

    # ---- summary ----------------------------------------------------------------

    def _active_days(self) -> set:
        rows = self._rows(
            "SELECT day FROM checkins UNION SELECT day FROM focus "
            "UNION SELECT day FROM journal"
        )
        return {r["day"] for r in rows}

    def summary(self, today: Optional[str] = None) -> Dict[str, Any]:
        """Everything the home screen shows, computed for *today*."""
        today_d = date.fromisoformat(_day(today))
        week = [(today_d - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        habits = self.list_habits(day=today_d.isoformat())
        n_habits = len(habits)
        active = self._active_days()

        done_by_day = {
            r["day"]: r["n"]
            for r in self._rows(
                "SELECT c.day, COUNT(*) AS n FROM checkins c JOIN habits h "
                "ON h.id = c.habit_id WHERE h.archived = 0 AND c.day BETWEEN ? AND ? "
                "GROUP BY c.day",
                (week[0], week[-1]),
            )
        }
        week_focus = self._rows(
            "SELECT COALESCE(SUM(minutes), 0) AS m FROM focus "
            "WHERE day BETWEEN ? AND ?",
            (week[0], week[-1]),
        )[0]["m"]
        journal_days = self._rows(
            "SELECT COUNT(DISTINCT day) AS n FROM journal WHERE day BETWEEN ? AND ?",
            (week[0], week[-1]),
        )[0]["n"]

        progress = {
            "habits": _pct(sum(done_by_day.values()), n_habits * _WEEK_DAYS),
            "focus": _pct(week_focus, _FOCUS_GOAL_MINUTES * _WEEK_DAYS),
            "mindset": _pct(journal_days, _WEEK_DAYS),
            "discipline": _pct(sum(1 for d in week if d in active), _WEEK_DAYS),
        }
        progress["overall"] = round(sum(progress.values()) / len(progress))

        totals = self._rows(
            "SELECT (SELECT COUNT(*) FROM checkins) AS c, "
            "(SELECT COUNT(*) FROM journal) AS j, "
            "(SELECT COALESCE(SUM(minutes), 0) FROM focus) AS f"
        )[0]
        xp = (
            totals["c"] * _XP_PER_CHECKIN
            + totals["j"] * _XP_PER_JOURNAL
            + totals["f"] * _XP_PER_FOCUS_MINUTE
        )
        first = min(active) if active else None
        return {
            "profile": self.profile(),
            "level": 1 + int(xp // _XP_PER_LEVEL),
            "level_progress": int(xp % _XP_PER_LEVEL),
            "stats": {
                "days": (today_d - date.fromisoformat(first)).days + 1 if first else 0,
                "habits": n_habits,
                "focus_hours": round(totals["f"] / 60, 2),
            },
            "streak": _streak(active, today_d),
            "progress": progress,
            "week": [
                {"day": d, "percent": _pct(done_by_day.get(d, 0), n_habits)}
                for d in week
            ],
            "today": {
                "day": today_d.isoformat(),
                "habits": habits,
                "habits_total": n_habits,
                "habits_done": sum(1 for h in habits if h["done"]),
            },
            "mission": self.mission(),
        }


def _streak(active: set, today: date) -> int:
    """Consecutive active days ending today (or yesterday, if today is still open)."""
    day = today if today.isoformat() in active else today - timedelta(days=1)
    count = 0
    while day.isoformat() in active:
        count += 1
        day -= timedelta(days=1)
    return count


def _now() -> float:
    return time.time()


_STORE: Optional[LifeStore] = None
_STORE_LOCK = threading.Lock()


def get_life_store() -> LifeStore:
    """The shared store at ``~/.openjarvis/life.db``."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            from openjarvis.core.paths import get_config_dir

            _STORE = LifeStore(get_config_dir() / "life.db")
        return _STORE


__all__ = ["LifeStore", "get_life_store"]
