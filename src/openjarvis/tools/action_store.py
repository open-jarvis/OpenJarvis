"""SQLite persistence for Phase-5 tool proposals, actions, and artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

from openjarvis.tools.actions import (
    ActionStatus,
    ToolAction,
    ToolArtifact,
    ToolEvent,
    ToolProposal,
    VerificationStatus,
    utc_now,
)


class ActionStoreError(RuntimeError):
    pass


class ActionIdempotencyConflict(ActionStoreError):
    pass


_ACTION_TRANSITIONS: dict[ActionStatus, frozenset[ActionStatus]] = {
    ActionStatus.PROPOSED: frozenset(
        {ActionStatus.VALIDATED, ActionStatus.DENIED, ActionStatus.CANCELED}
    ),
    ActionStatus.VALIDATED: frozenset(
        {
            ActionStatus.WAITING_APPROVAL,
            ActionStatus.RUNNING,
            ActionStatus.DENIED,
            ActionStatus.CANCELED,
        }
    ),
    ActionStatus.WAITING_APPROVAL: frozenset(
        {ActionStatus.RUNNING, ActionStatus.DENIED, ActionStatus.CANCELED}
    ),
    ActionStatus.RUNNING: frozenset(
        {ActionStatus.VERIFYING, ActionStatus.FAILED, ActionStatus.CANCELED}
    ),
    ActionStatus.VERIFYING: frozenset(
        {ActionStatus.VERIFIED, ActionStatus.FAILED, ActionStatus.CANCELED}
    ),
    ActionStatus.VERIFIED: frozenset({ActionStatus.COMPLETED}),
    ActionStatus.DENIED: frozenset(),
    ActionStatus.COMPLETED: frozenset(),
    ActionStatus.FAILED: frozenset({ActionStatus.RUNNING}),
    ActionStatus.CANCELED: frozenset(),
}


class ActionStore:
    """Thread-safe local persistence with payload-bound idempotency."""

    def __init__(self, db_path: str | Path) -> None:
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS tool_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    UNIQUE(task_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS tool_actions (
                    action_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    proposal_id TEXT NOT NULL REFERENCES tool_proposals(proposal_id),
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tool_actions_task
                    ON tool_actions(task_id);
                CREATE TABLE IF NOT EXISTS tool_artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    action_id TEXT NOT NULL REFERENCES tool_actions(action_id),
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tool_artifacts_action
                    ON tool_artifacts(action_id);
                CREATE TABLE IF NOT EXISTS tool_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    action_id TEXT NOT NULL REFERENCES tool_actions(action_id),
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tool_events_action
                    ON tool_events(action_id, sequence);
                """
            )

    @staticmethod
    def _json(model) -> str:
        return model.model_dump_json()

    @staticmethod
    def _hash_json(payload_json: str) -> str:
        value = json.loads(payload_json)
        # Generated identifiers and timestamps do not change operation identity.
        value.pop("proposal_id", None)
        value.pop("created_at", None)
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def put_proposal(self, proposal: ToolProposal) -> ToolProposal:
        payload = self._json(proposal)
        payload_hash = self._hash_json(payload)
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT payload_hash, payload_json FROM tool_proposals "
                "WHERE task_id = ? AND idempotency_key = ?",
                (proposal.task_id, proposal.idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["payload_hash"] != payload_hash:
                    raise ActionIdempotencyConflict(
                        "idempotency key was reused with a different proposal"
                    )
                return ToolProposal.model_validate_json(existing["payload_json"])
            self._conn.execute(
                "INSERT INTO tool_proposals "
                "(proposal_id, task_id, idempotency_key, payload_hash, payload_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    proposal.proposal_id,
                    proposal.task_id,
                    proposal.idempotency_key,
                    payload_hash,
                    payload,
                ),
            )
        return proposal

    def get_proposal(self, proposal_id: str) -> ToolProposal | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM tool_proposals WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        return ToolProposal.model_validate_json(row[0]) if row else None

    def put_action(self, action: ToolAction) -> ToolAction:
        with self._lock, self._conn:
            try:
                self._conn.execute(
                    "INSERT INTO tool_actions "
                    "(action_id, task_id, proposal_id, payload_json) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        action.action_id,
                        action.task_id,
                        action.proposal_id,
                        self._json(action),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ActionStoreError(str(exc)) from exc
        return action

    def get_action(self, action_id: str) -> ToolAction | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM tool_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return ToolAction.model_validate_json(row[0]) if row else None

    def list_actions(self, task_id: str) -> tuple[ToolAction, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM tool_actions WHERE task_id = ? "
                "ORDER BY rowid",
                (task_id,),
            ).fetchall()
        return tuple(ToolAction.model_validate_json(row[0]) for row in rows)

    def transition(
        self,
        action_id: str,
        status: ActionStatus,
        *,
        verification_status: VerificationStatus | None = None,
        approval_id: str | None = None,
        tool_run_id: str | None = None,
        output_summary: str | None = None,
        error: str | None = None,
        effect_known: bool | None = None,
        retry_count: int | None = None,
    ) -> ToolAction:
        with self._lock, self._conn:
            current = self.get_action(action_id)
            if current is None:
                raise ActionStoreError(f"unknown action: {action_id}")
            if (
                status is not current.status
                and status not in _ACTION_TRANSITIONS[current.status]
            ):
                raise ActionStoreError(
                    "invalid action transition "
                    f"{current.status.value} -> {status.value}"
                )
            changes = {"status": status, "updated_at": utc_now()}
            optional = {
                "verification_status": verification_status,
                "approval_id": approval_id,
                "tool_run_id": tool_run_id,
                "output_summary": output_summary,
                "error": error,
                "effect_known": effect_known,
                "retry_count": retry_count,
            }
            changes.update(
                {key: value for key, value in optional.items() if value is not None}
            )
            updated = current.model_copy(update=changes)
            self._conn.execute(
                "UPDATE tool_actions SET payload_json = ? WHERE action_id = ?",
                (self._json(updated), action_id),
            )
        return updated

    def put_artifact(self, artifact: ToolArtifact) -> ToolArtifact:
        with self._lock, self._conn:
            if self.get_action(artifact.action_id) is None:
                raise ActionStoreError(f"unknown action: {artifact.action_id}")
            self._conn.execute(
                "INSERT INTO tool_artifacts "
                "(artifact_id, action_id, payload_json) VALUES (?, ?, ?)",
                (artifact.artifact_id, artifact.action_id, self._json(artifact)),
            )
        return artifact

    def list_artifacts(self, action_id: str) -> tuple[ToolArtifact, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM tool_artifacts WHERE action_id = ? "
                "ORDER BY rowid",
                (action_id,),
            ).fetchall()
        return tuple(ToolArtifact.model_validate_json(row[0]) for row in rows)

    def append_event(self, event: ToolEvent) -> ToolEvent:
        with self._lock, self._conn:
            if self.get_action(event.action_id) is None:
                raise ActionStoreError(f"unknown action: {event.action_id}")
            self._conn.execute(
                "INSERT INTO tool_events "
                "(event_id, action_id, event_type, payload_json) VALUES (?, ?, ?, ?)",
                (
                    event.event_id,
                    event.action_id,
                    event.event_type,
                    self._json(event),
                ),
            )
        return event

    def list_events(self, action_id: str) -> tuple[ToolEvent, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM tool_events WHERE action_id = ? "
                "ORDER BY sequence",
                (action_id,),
            ).fetchall()
        return tuple(ToolEvent.model_validate_json(row[0]) for row in rows)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = [
    "ActionIdempotencyConflict",
    "ActionStore",
    "ActionStoreError",
]
