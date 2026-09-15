"""SQLite-backed trace storage."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from functools import wraps
from pathlib import Path
from typing import Any, List, Optional

from openjarvis.core.events import Event, EventBus, EventType
from openjarvis.core.types import StepType, Trace, TraceStep

_CREATE_TRACES = """\
CREATE TABLE IF NOT EXISTS traces (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id             TEXT    NOT NULL UNIQUE,
    query                TEXT    NOT NULL DEFAULT '',
    agent                TEXT    NOT NULL DEFAULT '',
    model                TEXT    NOT NULL DEFAULT '',
    engine               TEXT    NOT NULL DEFAULT '',
    result               TEXT    NOT NULL DEFAULT '',
    outcome              TEXT,
    feedback             REAL,
    started_at           REAL    NOT NULL DEFAULT 0.0,
    ended_at             REAL    NOT NULL DEFAULT 0.0,
    total_tokens         INTEGER NOT NULL DEFAULT 0,
    total_latency_seconds REAL   NOT NULL DEFAULT 0.0,
    metadata             TEXT    NOT NULL DEFAULT '{}',
    messages             TEXT    NOT NULL DEFAULT '[]'
);
"""

_CREATE_STEPS = """\
CREATE TABLE IF NOT EXISTS trace_steps (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id         TEXT    NOT NULL,
    step_index       INTEGER NOT NULL,
    step_type        TEXT    NOT NULL,
    timestamp        REAL    NOT NULL DEFAULT 0.0,
    duration_seconds REAL    NOT NULL DEFAULT 0.0,
    input            TEXT    NOT NULL DEFAULT '{}',
    output           TEXT    NOT NULL DEFAULT '{}',
    metadata         TEXT    NOT NULL DEFAULT '{}',
    FOREIGN KEY (trace_id) REFERENCES traces(trace_id)
);
"""

_CREATE_FTS = """\
CREATE VIRTUAL TABLE IF NOT EXISTS traces_fts USING fts5(
    trace_id, query, result, agent,
    content='traces',
    content_rowid='rowid',
    tokenize='unicode61'
);
"""

_FTS_SYNC_INSERT = """\
CREATE TRIGGER IF NOT EXISTS traces_fts_ai AFTER INSERT ON traces BEGIN
    INSERT INTO traces_fts(rowid, trace_id, query, result, agent)
    VALUES (new.rowid, new.trace_id, new.query, new.result, new.agent);
END;
"""

_INSERT_TRACE = """\
INSERT INTO traces (
    trace_id, query, agent, model, engine, result,
    outcome, feedback, started_at, ended_at,
    total_tokens, total_latency_seconds, metadata, messages
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_STEP = """\
INSERT INTO trace_steps (
    trace_id, step_index, step_type, timestamp,
    duration_seconds, input, output, metadata
) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def _serialized(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        self.flush()
        with self._lock:
            return method(self, *args, **kwargs)

    return guarded


def _transaction(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock, self._conn:
            return method(self, *args, **kwargs)

    return guarded


def _json_default(value: Any) -> str:
    """Render a value ``json.dumps`` cannot serialize (e.g. raw ``bytes``
    a tool put into a step's input/output/metadata).

    Trace persistence must never fail because of what a tool happened to
    put in a dict -- losing the row would also lose whatever answer the
    agent already produced this turn. A repr keeps the row useful for
    debugging instead of silently dropping the field.
    """
    try:
        return repr(value)
    except Exception:
        return f"<unrepresentable {type(value).__name__}>"


class TraceStore:
    """Append-only SQLite store for interaction traces."""

    def __init__(self, db_path: str | Path) -> None:
        self._lock = threading.RLock()
        self._writer = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="trace-writer"
        )
        self._write_slots = threading.BoundedSemaphore(1024)
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            from openjarvis.security.file_utils import secure_create

            secure_create(Path(self._db_path))
        # WAL alone does not serialize use of this connection. Every access
        # is guarded, and writes own a short transaction (never network I/O).
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TRACES)
        self._conn.execute(_CREATE_STEPS)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS run_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL, "
            "event_type TEXT NOT NULL, timestamp REAL NOT NULL, "
            "monotonic_timestamp REAL NOT NULL, data TEXT NOT NULL)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS run_events_run ON run_events(run_id, id)"
        )
        self._conn.execute(_CREATE_FTS)
        self._conn.execute(_FTS_SYNC_INSERT)
        # Migrate: add messages column if missing (pre-existing databases)
        try:
            self._conn.execute(
                "ALTER TABLE traces ADD COLUMN messages TEXT NOT NULL DEFAULT '[]'"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        self._conn.commit()

    def submit_write(self, method, /, *args, **kwargs) -> Future:
        """Queue a bounded write without doing SQLite I/O on the voice loop."""
        if not self._write_slots.acquire(blocking=False):
            raise RuntimeError("trace_writer_capacity_exhausted")
        try:
            future = self._writer.submit(method, *args, **kwargs)
        except BaseException:
            self._write_slots.release()
            raise

        def finished(result):
            self._write_slots.release()
            if not result.cancelled() and result.exception() is not None:
                logging.getLogger(__name__).error(
                    "trace writer failed",
                    exc_info=result.exception(),
                )

        future.add_done_callback(finished)
        return future

    def flush(self) -> None:
        """Synchronous readers/shutdown observe all previously queued writes."""
        self._writer.submit(lambda: None).result()

    @_transaction
    def save(self, trace: Trace) -> None:
        """Persist a complete trace with all its steps.

        ``trace_id`` is a primary key: saving a second, different trace under
        an existing id raises ``sqlite3.IntegrityError`` (the external-corpus
        adapter relies on this to surface duplicate record ids). The server
        avoids re-saving the same trace by keeping the ``TraceCollector`` the
        single writer — see ``server/app.py`` — rather than swallowing
        collisions here.
        """
        self._conn.execute(
            _INSERT_TRACE,
            (
                trace.trace_id,
                trace.query,
                trace.agent,
                trace.model,
                trace.engine,
                trace.result,
                trace.outcome,
                trace.feedback,
                trace.started_at,
                trace.ended_at,
                trace.total_tokens,
                trace.total_latency_seconds,
                json.dumps(trace.metadata),
                json.dumps(trace.messages),
            ),
        )
        for idx, step in enumerate(trace.steps):
            self._conn.execute(
                _INSERT_STEP,
                (
                    trace.trace_id,
                    idx,
                    step.step_type.value
                    if isinstance(step.step_type, StepType)
                    else step.step_type,
                    step.timestamp,
                    step.duration_seconds,
                    json.dumps(step.input, default=_json_default),
                    json.dumps(step.output, default=_json_default),
                    json.dumps(step.metadata, default=_json_default),
                ),
            )
        self._conn.commit()

    @_transaction
    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        data: dict[str, Any],
        *,
        timestamp: float | None = None,
        monotonic_timestamp: float | None = None,
    ) -> None:
        """Persist lifecycle/late-worker evidence independently of an answer."""
        self._conn.execute(
            "INSERT INTO run_events "
            "(run_id, event_type, timestamp, monotonic_timestamp, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                event_type,
                timestamp if timestamp is not None else time.time(),
                monotonic_timestamp
                if monotonic_timestamp is not None
                else time.monotonic(),
                json.dumps(data, default=_json_default),
            ),
        )

    @_serialized
    def run_events(self, run_id: str | None = None, *, limit: int = 1000) -> list[dict]:
        """Read admission, partial steps, cancellation, and late settlement."""
        rows = self._conn.execute(
            "SELECT id, run_id, event_type, timestamp, monotonic_timestamp, data "
            "FROM run_events WHERE (? IS NULL OR run_id = ?) ORDER BY id LIMIT ?",
            (run_id, run_id, limit),
        ).fetchall()
        return [
            dict(
                zip(
                    (
                        "id",
                        "run_id",
                        "event_type",
                        "timestamp",
                        "monotonic_timestamp",
                        "data",
                    ),
                    (*row[:5], json.loads(row[5])),
                    strict=True,
                )
            )
            for row in rows
        ]

    @_serialized
    def get(self, trace_id: str) -> Optional[Trace]:
        """Retrieve a trace by id, or ``None`` if not found."""
        row = self._conn.execute(
            "SELECT * FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_trace(row)

    @_serialized
    def list_traces(
        self,
        *,
        agent: Optional[str] = None,
        model: Optional[str] = None,
        outcome: Optional[str] = None,
        since: Optional[float] = None,
        until: Optional[float] = None,
        limit: int = 100,
    ) -> List[Trace]:
        """Query traces with optional filters."""
        clauses: List[str] = []
        params: List[Any] = []
        if agent is not None:
            clauses.append("agent = ?")
            params.append(agent)
        if model is not None:
            clauses.append("model = ?")
            params.append(model)
        if outcome is not None:
            clauses.append("outcome = ?")
            params.append(outcome)
        if since is not None:
            clauses.append("started_at >= ?")
            params.append(since)
        if until is not None:
            clauses.append("started_at <= ?")
            params.append(until)
        where = " AND ".join(clauses) if clauses else "1=1"
        sql = f"SELECT * FROM traces WHERE {where} ORDER BY started_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_trace(r) for r in rows]

    @_serialized
    def count(self) -> int:
        """Return the total number of stored traces."""
        row = self._conn.execute("SELECT COUNT(*) FROM traces").fetchone()
        return row[0] if row else 0

    @_serialized
    def search(
        self,
        query: str,
        *,
        agent: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Full-text search across traces. Optionally filter by agent."""
        sql = (
            "SELECT t.trace_id, t.query, t.result, t.agent, t.model, t.outcome,"
            " t.started_at "
            "FROM traces_fts f JOIN traces t ON f.rowid = t.rowid "
            "WHERE traces_fts MATCH ?"
        )
        params: list[Any] = [query]
        if agent:
            sql += " AND t.agent = ?"
            params.append(agent)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "trace_id": r[0],
                "query": r[1],
                "result": r[2],
                "agent": r[3],
                "model": r[4],
                "outcome": r[5],
                "started_at": r[6],
            }
            for r in rows
        ]

    def subscribe_to_bus(self, bus: EventBus) -> None:
        """Subscribe to ``TRACE_COMPLETE`` events on *bus*."""
        bus.subscribe(EventType.TRACE_COMPLETE, self._on_event)

    def _on_event(self, event: Event) -> None:
        trace = event.data.get("trace")
        if isinstance(trace, Trace):
            self.save(trace)

    @_transaction
    def update_feedback(self, trace_id: str, score: float) -> bool:
        """Update the feedback score for a trace.

        Returns True if the trace was found and updated, False otherwise.
        """
        cursor = self._conn.execute(
            "UPDATE traces SET feedback = ? WHERE trace_id = ?",
            (score, trace_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        # Do not hold the connection lock while joining a writer that needs it.
        self._writer.shutdown(wait=True)
        with self._lock:
            self._conn.close()

    # -- internal helpers ------------------------------------------------------

    def _row_to_trace(self, row: tuple) -> Trace:
        """Convert a traces table row + its steps into a Trace object."""
        trace_id = row[1]
        step_rows = self._conn.execute(
            "SELECT * FROM trace_steps WHERE trace_id = ? ORDER BY step_index",
            (trace_id,),
        ).fetchall()
        steps = [
            TraceStep(
                step_type=StepType(sr[3]),
                timestamp=sr[4],
                duration_seconds=sr[5],
                input=json.loads(sr[6]),
                output=json.loads(sr[7]),
                metadata=json.loads(sr[8]),
            )
            for sr in step_rows
        ]
        # messages column (index 14) was added after metadata; handle
        # databases created before the column existed.
        messages_raw = row[14] if len(row) > 14 else "[]"
        return Trace(
            trace_id=trace_id,
            query=row[2],
            agent=row[3],
            model=row[4],
            engine=row[5],
            result=row[6],
            outcome=row[7],
            feedback=row[8],
            started_at=row[9],
            ended_at=row[10],
            total_tokens=row[11],
            total_latency_seconds=row[12],
            metadata=json.loads(row[13]),
            messages=json.loads(messages_raw),
            steps=steps,
        )

    @_serialized
    def _fetchall(self, sql: str = "SELECT * FROM traces") -> list:
        return self._conn.execute(sql).fetchall()


__all__ = ["TraceStore"]
