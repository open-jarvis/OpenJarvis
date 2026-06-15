"""ApprovalStore — SQLite-backed store for proactive agent action approvals.

Two tables:
- ``pending_actions``: actions proposed by the proactive agent awaiting user decision
- ``permission_memory``: remembered user decisions keyed by action pattern

Permission key format: ``"{action_type}:{fingerprint}"``
e.g. ``"email_delete:domain:noreply.github.com"``
     ``"sms_draft_reply:contact:+15551234567"``
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.paths import get_config_dir

# ---------------------------------------------------------------------------
# Decision constants
# ---------------------------------------------------------------------------

DECISION_ALWAYS_APPROVE = "always_approve"
DECISION_ALWAYS_DENY = "always_deny"
DECISION_ASK = "ask"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_DENIED = "denied"
STATUS_EXPIRED = "expired"
STATUS_EXECUTED = "executed"

# Tiers govern default ask behavior
TIER_TRIVIAL = "trivial"  # Execute immediately, no ask
TIER_LOW = "low"  # Ask once, then remember
TIER_MEDIUM = "medium"  # Ask each time unless remembered
TIER_HIGH = "high"  # Always ask, never auto-remember


@dataclass
class PendingAction:
    """An action proposed by the proactive agent."""

    id: str
    action_type: str
    description: str
    payload: Dict[str, Any]
    permission_key: str
    tier: str
    status: str = STATUS_PENDING
    created_at: str = ""
    expires_at: str = ""
    notification_sent: bool = False
    decision_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action_type": self.action_type,
            "description": self.description,
            "payload": json.dumps(self.payload),
            "permission_key": self.permission_key,
            "tier": self.tier,
            "status": self.status,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "notification_sent": int(self.notification_sent),
            "decision_at": self.decision_at,
        }

    @classmethod
    def from_row(cls, row: tuple) -> PendingAction:
        (
            id_,
            action_type,
            description,
            payload_json,
            permission_key,
            tier,
            status,
            created_at,
            expires_at,
            notification_sent,
            decision_at,
        ) = row
        return cls(
            id=id_,
            action_type=action_type,
            description=description,
            payload=json.loads(payload_json) if payload_json else {},
            permission_key=permission_key,
            tier=tier,
            status=status,
            created_at=created_at or "",
            expires_at=expires_at or "",
            notification_sent=bool(notification_sent),
            decision_at=decision_at,
        )


@dataclass
class PermissionRule:
    """A remembered user decision for a permission pattern."""

    permission_key: str
    decision: str  # always_approve | always_deny
    times_approved: int = 0
    times_denied: int = 0
    last_updated: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "permission_key": self.permission_key,
            "decision": self.decision,
            "times_approved": self.times_approved,
            "times_denied": self.times_denied,
            "last_updated": self.last_updated,
            "notes": self.notes,
        }

    @classmethod
    def from_row(cls, row: tuple) -> PermissionRule:
        (
            permission_key,
            decision,
            times_approved,
            times_denied,
            last_updated,
            notes,
        ) = row
        return cls(
            permission_key=permission_key,
            decision=decision,
            times_approved=times_approved,
            times_denied=times_denied,
            last_updated=last_updated or "",
            notes=notes or "",
        )


class ApprovalStore:
    """SQLite store for proactive agent action approvals and permission memory."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            db_path = str(get_config_dir() / "approvals.db")
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._conn.commit()

    def _create_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS pending_actions (
                id TEXT PRIMARY KEY,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                payload TEXT NOT NULL,
                permission_key TEXT NOT NULL,
                tier TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                notification_sent INTEGER NOT NULL DEFAULT 0,
                decision_at TEXT
            );

            CREATE TABLE IF NOT EXISTS permission_memory (
                permission_key TEXT PRIMARY KEY,
                decision TEXT NOT NULL,
                times_approved INTEGER NOT NULL DEFAULT 0,
                times_denied INTEGER NOT NULL DEFAULT 0,
                last_updated TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT ''
            );
        """)

    # -- Pending actions -------------------------------------------------------

    def queue_action(
        self,
        action_type: str,
        description: str,
        payload: Dict[str, Any],
        permission_key: str,
        tier: str,
        ttl_hours: int = 24,
    ) -> PendingAction:
        """Create and persist a new pending action."""
        now = datetime.now(timezone.utc)
        action = PendingAction(
            id=uuid.uuid4().hex[:12],
            action_type=action_type,
            description=description,
            payload=payload,
            permission_key=permission_key,
            tier=tier,
            status=STATUS_PENDING,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=ttl_hours)).isoformat(),
        )
        self._conn.execute(
            """
            INSERT OR REPLACE INTO pending_actions
                (id, action_type, description, payload, permission_key,
                 tier, status, created_at, expires_at, notification_sent, decision_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.id,
                action.action_type,
                action.description,
                json.dumps(action.payload),
                action.permission_key,
                action.tier,
                action.status,
                action.created_at,
                action.expires_at,
                int(action.notification_sent),
                action.decision_at,
            ),
        )
        self._conn.commit()
        return action

    def get_action(self, action_id: str) -> Optional[PendingAction]:
        row = self._conn.execute(
            "SELECT id, action_type, description, payload, permission_key, "
            "tier, status, created_at, expires_at, notification_sent, decision_at "
            "FROM pending_actions WHERE id = ?",
            (action_id,),
        ).fetchone()
        return PendingAction.from_row(row) if row else None

    def list_pending(self) -> List[PendingAction]:
        """Return all non-expired pending actions."""
        now = datetime.now(timezone.utc).isoformat()
        rows = self._conn.execute(
            "SELECT id, action_type, description, payload, permission_key, "
            "tier, status, created_at, expires_at, notification_sent, decision_at "
            "FROM pending_actions WHERE status = ? AND expires_at > ? "
            "ORDER BY created_at",
            (STATUS_PENDING, now),
        ).fetchall()
        return [PendingAction.from_row(r) for r in rows]

    def list_approved(self) -> List[PendingAction]:
        """Return approved-but-not-yet-executed actions."""
        rows = self._conn.execute(
            "SELECT id, action_type, description, payload, permission_key, "
            "tier, status, created_at, expires_at, notification_sent, decision_at "
            "FROM pending_actions WHERE status = ? ORDER BY created_at",
            (STATUS_APPROVED,),
        ).fetchall()
        return [PendingAction.from_row(r) for r in rows]

    def update_status(
        self,
        action_id: str,
        status: str,
        *,
        notification_sent: Optional[bool] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if notification_sent is not None:
            self._conn.execute(
                "UPDATE pending_actions SET status = ?, decision_at = ?, "
                "notification_sent = ? WHERE id = ?",
                (status, now, int(notification_sent), action_id),
            )
        else:
            self._conn.execute(
                "UPDATE pending_actions SET status = ?, decision_at = ? WHERE id = ?",
                (status, now, action_id),
            )
        self._conn.commit()

    def expire_stale(self) -> int:
        """Mark past-TTL pending actions as expired. Returns count."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "UPDATE pending_actions SET status = ? "
            "WHERE status = ? AND expires_at <= ?",
            (STATUS_EXPIRED, STATUS_PENDING, now),
        )
        self._conn.commit()
        return cur.rowcount

    # -- Permission memory -----------------------------------------------------

    def get_permission(self, permission_key: str) -> Optional[PermissionRule]:
        row = self._conn.execute(
            "SELECT permission_key, decision, times_approved, times_denied, "
            "last_updated, notes FROM permission_memory WHERE permission_key = ?",
            (permission_key,),
        ).fetchone()
        return PermissionRule.from_row(row) if row else None

    def set_permission(
        self,
        permission_key: str,
        decision: str,
        *,
        approved: bool = False,
        notes: str = "",
    ) -> None:
        """Upsert a permission rule, incrementing the relevant counter."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_permission(permission_key)
        if existing:
            times_approved = existing.times_approved + (1 if approved else 0)
            times_denied = existing.times_denied + (0 if approved else 1)
            self._conn.execute(
                "UPDATE permission_memory SET decision = ?, times_approved = ?, "
                "times_denied = ?, last_updated = ?, notes = ? "
                "WHERE permission_key = ?",
                (
                    decision,
                    times_approved,
                    times_denied,
                    now,
                    notes or existing.notes,
                    permission_key,
                ),
            )
        else:
            self._conn.execute(
                "INSERT INTO permission_memory "
                "(permission_key, decision, times_approved, times_denied, "
                "last_updated, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    permission_key,
                    decision,
                    1 if approved else 0,
                    0 if approved else 1,
                    now,
                    notes,
                ),
            )
        self._conn.commit()

    def clear_permission(self, permission_key: str) -> None:
        self._conn.execute(
            "DELETE FROM permission_memory WHERE permission_key = ?",
            (permission_key,),
        )
        self._conn.commit()

    def list_permissions(self) -> List[PermissionRule]:
        rows = self._conn.execute(
            "SELECT permission_key, decision, times_approved, times_denied, "
            "last_updated, notes FROM permission_memory ORDER BY last_updated DESC"
        ).fetchall()
        return [PermissionRule.from_row(r) for r in rows]

    def get_seen_ids(self) -> set:
        """Return all doc_ids and message_ids previously queued (any status).

        Used by ``ProactiveAgent`` to skip items it has already proposed so
        they don't resurface on every run while still unread/unanswered.
        """
        seen: set = set()
        rows = self._conn.execute("SELECT payload FROM pending_actions").fetchall()
        for (payload_json,) in rows:
            try:
                payload = json.loads(payload_json) if payload_json else {}
            except json.JSONDecodeError:
                continue
            doc_id = payload.get("doc_id", "")
            if doc_id:
                seen.add(doc_id)
            msg_id = payload.get("message_id", "")
            if msg_id:
                seen.add(f"gmail:{msg_id}")
        return seen

    def close(self) -> None:
        self._conn.close()


__all__ = [
    "ApprovalStore",
    "PendingAction",
    "PermissionRule",
    "DECISION_ALWAYS_APPROVE",
    "DECISION_ALWAYS_DENY",
    "DECISION_ASK",
    "STATUS_PENDING",
    "STATUS_APPROVED",
    "STATUS_DENIED",
    "STATUS_EXPIRED",
    "STATUS_EXECUTED",
    "TIER_TRIVIAL",
    "TIER_LOW",
    "TIER_MEDIUM",
    "TIER_HIGH",
]
