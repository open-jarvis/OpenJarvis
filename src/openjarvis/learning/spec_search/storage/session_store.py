"""SQLite-backed storage for spec-search LearningSession records.

Mirrors the style of ``openjarvis.learning.optimize.store.OptimizationStore``:

- stdlib ``sqlite3`` in WAL mode
- inline DDL as module-level constants
- persistent connection stored as ``self._conn``
- ``_migrate()`` runs additive ALTER TABLEs that swallow ``OperationalError``

The store does NOT share its database file with ``OptimizationStore`` (see
spec §8.1 / brainstorming Q8). The two SQLite files live side-by-side in
``~/.openjarvis/learning/`` but are independent.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

from openjarvis.learning.spec_search.models import (
    AutonomyMode,
    BenchmarkSnapshot,
    EditOutcome,
    LearningSession,
    SessionStatus,
    TriggerKind,
)

logger = logging.getLogger(__name__)


_CREATE_SESSIONS = """\
CREATE TABLE IF NOT EXISTS learning_sessions (
    id TEXT PRIMARY KEY,
    parent_session_id TEXT,
    trigger TEXT NOT NULL,
    trigger_metadata TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL,
    autonomy_mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    diagnosis_path TEXT NOT NULL,
    plan_path TEXT NOT NULL,
    benchmark_before TEXT NOT NULL,
    benchmark_after TEXT,
    git_checkpoint_pre TEXT NOT NULL,
    git_checkpoint_post TEXT,
    teacher_cost_usd REAL NOT NULL DEFAULT 0.0,
    error TEXT,
    FOREIGN KEY (parent_session_id) REFERENCES learning_sessions(id)
);
"""

_CREATE_OUTCOMES = """\
CREATE TABLE IF NOT EXISTS edit_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    edit_id TEXT NOT NULL,
    pillar TEXT NOT NULL,
    op TEXT NOT NULL,
    target TEXT NOT NULL,
    risk_tier TEXT NOT NULL,
    status TEXT NOT NULL,
    benchmark_delta REAL,
    cluster_deltas TEXT NOT NULL DEFAULT '{}',
    rationale TEXT NOT NULL DEFAULT '',
    error TEXT,
    applied_at TEXT,
    FOREIGN KEY (session_id) REFERENCES learning_sessions(id)
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_sessions_started_at "
    "ON learning_sessions(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_status ON learning_sessions(status)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_session ON edit_outcomes(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_outcomes_op ON edit_outcomes(op)",
]

_INSERT_SESSION = """\
INSERT OR REPLACE INTO learning_sessions (
    id, parent_session_id, trigger, trigger_metadata, status, autonomy_mode,
    started_at, ended_at, diagnosis_path, plan_path,
    benchmark_before, benchmark_after,
    git_checkpoint_pre, git_checkpoint_post, teacher_cost_usd, error
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_OUTCOME = """\
INSERT INTO edit_outcomes (
    session_id, edit_id, pillar, op, target, risk_tier, status,
    benchmark_delta, cluster_deltas, rationale, error, applied_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

# Future ALTER TABLE statements go here, swallowing OperationalError.
_MIGRATE: list[str] = []


def _dt_to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _iso_to_dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class SessionStore:
    """SQLite-backed storage for LearningSession and EditOutcome records.

    The full LearningSession is also serialized to disk as
    ``<session_dir>/session.json`` — that file is the authoritative source
    if SQLite is ever lost. This store is the index used for fast queries.
    """

    def __init__(self, db_path: Union[str, Path]) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(_CREATE_SESSIONS)
        self._conn.execute(_CREATE_OUTCOMES)
        for index in _CREATE_INDEXES:
            self._conn.execute(index)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Apply additive schema migrations, swallowing already-applied ones."""
        for stmt in _MIGRATE:
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def save_session(self, session: LearningSession) -> None:
        """Insert or update a LearningSession (idempotent on session.id)."""
        self._conn.execute(
            _INSERT_SESSION,
            (
                session.id,
                session.parent_session_id,
                session.trigger.value,
                json.dumps(session.trigger_metadata),
                session.status.value,
                session.autonomy_mode.value,
                session.started_at.isoformat(),
                _dt_to_iso(session.ended_at),
                str(session.diagnosis_path),
                str(session.plan_path),
                session.benchmark_before.model_dump_json(),
                (
                    session.benchmark_after.model_dump_json()
                    if session.benchmark_after is not None
                    else None
                ),
                session.git_checkpoint_pre,
                session.git_checkpoint_post,
                session.teacher_cost_usd,
                session.error,
            ),
        )
        self._conn.commit()

    def get_session(self, session_id: str) -> Optional[LearningSession]:
        """Return the LearningSession with the given id, or None if missing."""
        row = self._conn.execute(
            "SELECT id, parent_session_id, trigger, trigger_metadata, status, "
            "autonomy_mode, started_at, ended_at, diagnosis_path, plan_path, "
            "benchmark_before, benchmark_after, git_checkpoint_pre, "
            "git_checkpoint_post, teacher_cost_usd, error "
            "FROM learning_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_session(row, with_outcomes=True)

    def list_sessions(
        self,
        status: SessionStatus | None = None,
        limit: int | None = None,
    ) -> list[LearningSession]:
        """List sessions ordered by ``started_at DESC``."""
        sql = (
            "SELECT id, parent_session_id, trigger, trigger_metadata, status, "
            "autonomy_mode, started_at, ended_at, diagnosis_path, plan_path, "
            "benchmark_before, benchmark_after, git_checkpoint_pre, "
            "git_checkpoint_post, teacher_cost_usd, error "
            "FROM learning_sessions"
        )
        params: list[object] = []
        if status is not None:
            sql += " WHERE status = ?"
            params.append(status.value)
        sql += " ORDER BY started_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_session(r, with_outcomes=True) for r in rows]

    def _row_to_session(self, row: tuple, with_outcomes: bool) -> LearningSession:
        session = LearningSession(
            id=row[0],
            parent_session_id=row[1],
            trigger=TriggerKind(row[2]),
            trigger_metadata=json.loads(row[3]),
            status=SessionStatus(row[4]),
            autonomy_mode=AutonomyMode(row[5]),
            started_at=datetime.fromisoformat(row[6]),
            ended_at=_iso_to_dt(row[7]),
            diagnosis_path=Path(row[8]),
            plan_path=Path(row[9]),
            benchmark_before=BenchmarkSnapshot.model_validate_json(row[10]),
            benchmark_after=(
                BenchmarkSnapshot.model_validate_json(row[11])
                if row[11] is not None
                else None
            ),
            edit_outcomes=[],
            git_checkpoint_pre=row[12],
            git_checkpoint_post=row[13],
            teacher_cost_usd=row[14],
            error=row[15],
        )
        if with_outcomes:
            outcomes = self.list_outcomes(session.id)
            session = session.model_copy(update={"edit_outcomes": outcomes})
        return session

    # ------------------------------------------------------------------
    # Edit outcomes
    # ------------------------------------------------------------------

    def save_outcome(
        self,
        session_id: str,
        outcome: EditOutcome,
        *,
        pillar: str,
        op: str,
        target: str,
        risk_tier: str,
        rationale: str = "",
    ) -> None:
        """Insert an EditOutcome row.

        ``pillar``, ``op``, ``target``, ``risk_tier``, and ``rationale`` come
        from the parent ``Edit`` (which is not stored on the EditOutcome
        model). They are kept as columns to make ``WHERE op = ?`` queries
        possible without joining against the on-disk plan.json.
        """
        self._conn.execute(
            _INSERT_OUTCOME,
            (
                session_id,
                outcome.edit_id,
                pillar,
                op,
                target,
                risk_tier,
                outcome.status,
                outcome.benchmark_delta,
                json.dumps(outcome.cluster_deltas),
                rationale,
                outcome.error,
                _dt_to_iso(outcome.applied_at),
            ),
        )
        self._conn.commit()

    def list_outcomes(self, session_id: str) -> list[EditOutcome]:
        """Return all EditOutcomes for a session, ordered by insertion id."""
        rows = self._conn.execute(
            "SELECT edit_id, status, benchmark_delta, cluster_deltas, error, "
            "applied_at FROM edit_outcomes WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [
            EditOutcome(
                edit_id=row[0],
                status=row[1],
                benchmark_delta=row[2],
                cluster_deltas=json.loads(row[3]),
                error=row[4],
                applied_at=_iso_to_dt(row[5]),
            )
            for row in rows
        ]
