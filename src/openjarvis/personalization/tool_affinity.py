"""ToolAffinityTracker — learn which tools the user actually leans on.

Hooks into ``TOOL_CALL_END`` events from the runtime event bus and
records (tool_name, success) tuples to a small SQLite table. Exposes a
``top_tools()`` query consumed by :class:`ToolAffinityInjector`.

Local-only. No network. Safe to run with the rest of the daemon — the
writer is async-friendly (event-bus callback), and the reader opens a
read-only connection per query.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

from openjarvis.core.config import DEFAULT_CONFIG_DIR

logger = logging.getLogger(__name__)

DEFAULT_AFFINITY_DB = DEFAULT_CONFIG_DIR / "tool_affinity.db"


class ToolAffinityTracker:
    """Track per-tool invocation count + success rate.

    The schema is intentionally small — one row per tool — so the table
    stays cheap to scan. Recency is approximated by ``last_used`` and
    callers can pass ``decay_after_days`` to bias toward recent usage.
    """

    def __init__(
        self,
        db_path: Path | str = DEFAULT_AFFINITY_DB,
    ) -> None:
        self._db_path = Path(db_path).expanduser()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS tool_affinity ("
                "  tool_name TEXT PRIMARY KEY,"
                "  total_calls INTEGER NOT NULL DEFAULT 0,"
                "  successful_calls INTEGER NOT NULL DEFAULT 0,"
                "  last_used REAL NOT NULL DEFAULT 0"
                ")"
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path))

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, tool_name: str, *, success: bool) -> None:
        if not tool_name:
            return
        now = time.time()
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO tool_affinity (tool_name, total_calls,"
                " successful_calls, last_used)"
                " VALUES (?, 1, ?, ?)"
                " ON CONFLICT(tool_name) DO UPDATE SET"
                "  total_calls = total_calls + 1,"
                "  successful_calls = successful_calls"
                "    + CASE WHEN excluded.successful_calls = 1 THEN 1 ELSE 0 END,"
                "  last_used = excluded.last_used",
                (tool_name, 1 if success else 0, now),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def top_tools(
        self,
        limit: int = 5,
        *,
        recent_days: Optional[float] = None,
        min_calls: int = 1,
    ) -> List[Tuple[str, int, float]]:
        """Return ``[(tool_name, total_calls, success_rate), ...]``.

        Sorted by total_calls (descending). When ``recent_days`` is
        given, rows whose ``last_used`` is older than that window are
        excluded.
        """
        sql = (
            "SELECT tool_name, total_calls, successful_calls, last_used "
            "FROM tool_affinity WHERE total_calls >= ?"
        )
        params: List[object] = [min_calls]
        if recent_days is not None and recent_days > 0:
            cutoff = time.time() - recent_days * 86400
            sql += " AND last_used >= ?"
            params.append(cutoff)
        sql += " ORDER BY total_calls DESC LIMIT ?"
        params.append(limit)
        try:
            with self._connect() as conn:
                rows = list(conn.execute(sql, params))
        except sqlite3.OperationalError as exc:
            logger.debug("top_tools query failed: %s", exc)
            return []
        out: List[Tuple[str, int, float]] = []
        for tool_name, total, successful, _last in rows:
            rate = (successful / total) if total else 0.0
            out.append((tool_name, total, rate))
        return out

    # ------------------------------------------------------------------
    # Event bus integration
    # ------------------------------------------------------------------

    def subscribe(self, bus: object) -> None:
        """Subscribe to ``TOOL_CALL_END`` events from *bus*.

        Each event payload should contain ``tool_name`` and ``success``.
        """
        from openjarvis.core.events import EventType

        def _cb(event):  # type: ignore[no-untyped-def]
            data = getattr(event, "data", {}) or {}
            tool_name = data.get("tool_name") or data.get("tool") or ""
            success = bool(data.get("success", True))
            self.record(tool_name, success=success)

        subscribe = getattr(bus, "subscribe", None)
        if callable(subscribe):
            subscribe(EventType.TOOL_CALL_END, _cb)


_DEFAULT_TRACKER: Optional["ToolAffinityTracker"] = None


def get_default_tracker() -> "ToolAffinityTracker":
    """Process-wide singleton tracker (lazy)."""
    global _DEFAULT_TRACKER
    if _DEFAULT_TRACKER is None:
        _DEFAULT_TRACKER = ToolAffinityTracker()
    return _DEFAULT_TRACKER


def wire_tool_affinity(bus: object) -> "ToolAffinityTracker":
    """Subscribe the singleton tracker to *bus* and return it.

    Safe to call multiple times — duplicate subscriptions are idempotent
    on most bus implementations and at worst double-record (which we
    accept since precise affinity numbers don't need to be exact).
    """
    tracker = get_default_tracker()
    tracker.subscribe(bus)
    return tracker


__all__ = [
    "DEFAULT_AFFINITY_DB",
    "ToolAffinityTracker",
    "get_default_tracker",
    "wire_tool_affinity",
]
