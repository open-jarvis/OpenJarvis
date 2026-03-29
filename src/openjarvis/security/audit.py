"""Audit logger — persist security events to SQLite with Merkle hash chain."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple, Union

from openjarvis.core.config import DEFAULT_CONFIG_DIR
from openjarvis.core.events import Event, EventBus, EventType
from openjarvis.security.types import (
    ScanFinding,
    SecurityEvent,
    SecurityEventType,
    ThreatLevel,
)


class AuditLogger:
    """Append-only SQLite audit log for security events.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.
    bus:
        Optional event bus — if provided, subscribes to security events
        (``SECURITY_SCAN``, ``SECURITY_ALERT``, ``SECURITY_BLOCK``).
    """

    def __init__(
        self,
        db_path: Union[str, Path] = DEFAULT_CONFIG_DIR / "audit.db",
        bus: Optional[EventBus] = None,
    ) -> None:
        self._db_path = Path(db_path)
        from openjarvis.security.file_utils import secure_create

        secure_create(self._db_path)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS security_events (
                id          INTEGER PRIMARY KEY,
                timestamp   REAL,
                event_type  TEXT,
                findings_json TEXT,
                content_preview TEXT,
                action_taken TEXT,
                row_hash    TEXT DEFAULT '',
                prev_hash   TEXT DEFAULT ''
            )
            """
        )
        self._conn.commit()
        self._migrate_schema()

        if bus is not None:
            bus.subscribe(EventType.SECURITY_SCAN, self._on_event)
            bus.subscribe(EventType.SECURITY_ALERT, self._on_event)
            bus.subscribe(EventType.SECURITY_BLOCK, self._on_event)

    def _migrate_schema(self) -> None:
        """Add row_hash/prev_hash columns if missing (schema migration)."""
        columns = {
            row[1]
            for row in self._conn.execute(
                "PRAGMA table_info(security_events)"
            ).fetchall()
        }
        if "row_hash" not in columns:
            self._conn.execute(
                "ALTER TABLE security_events ADD COLUMN row_hash TEXT DEFAULT ''"
            )
        if "prev_hash" not in columns:
            self._conn.execute(
                "ALTER TABLE security_events ADD COLUMN prev_hash TEXT DEFAULT ''"
            )
        self._conn.commit()

    # -- public API ----------------------------------------------------------

    def log(self, event: SecurityEvent) -> None:
        """Insert a security event into the audit log with Merkle hash chain."""
        findings_json = json.dumps(
            [
                {
                    "pattern_name": f.pattern_name,
                    "matched_text": f.matched_text,
                    "threat_level": f.threat_level.value,
                    "start": f.start,
                    "end": f.end,
                    "description": f.description,
                }
                for f in event.findings
            ]
        )

        # Compute hash chain
        prev_hash = self.tail_hash()
        hash_input = (
            f"{prev_hash}|{event.timestamp}|{event.event_type.value}"
            f"|{findings_json}|{event.content_preview}|{event.action_taken}"
        )
        row_hash = hashlib.sha256(hash_input.encode()).hexdigest()

        self._conn.execute(
            """
            INSERT INTO security_events
                (timestamp, event_type, findings_json, content_preview,
                 action_taken, row_hash, prev_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.timestamp,
                event.event_type.value,
                findings_json,
                event.content_preview,
                event.action_taken,
                row_hash,
                prev_hash,
            ),
        )
        self._conn.commit()

    def query(
        self,
        *,
        event_type: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> List[SecurityEvent]:
        """Query logged security events with optional filters."""
        sql = (
            "SELECT timestamp, event_type, findings_json,"
            " content_preview, action_taken"
            " FROM security_events WHERE 1=1"
        )
        params: list = []

        if event_type is not None:
            sql += " AND event_type = ?"
            params.append(event_type)
        if since is not None:
            sql += " AND timestamp >= ?"
            params.append(since)

        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        events: List[SecurityEvent] = []
        for row in rows:
            ts, etype, findings_json, preview, action = row
            findings_raw = json.loads(findings_json) if findings_json else []
            findings = [
                ScanFinding(
                    pattern_name=f["pattern_name"],
                    matched_text=f["matched_text"],
                    threat_level=ThreatLevel(f["threat_level"]),
                    start=f["start"],
                    end=f["end"],
                    description=f.get("description", ""),
                )
                for f in findings_raw
            ]
            events.append(
                SecurityEvent(
                    event_type=SecurityEventType(etype),
                    timestamp=ts,
                    findings=findings,
                    content_preview=preview or "",
                    action_taken=action or "",
                )
            )
        return events

    def tail_hash(self) -> str:
        """Return the hash of the last row in the chain, or empty string."""
        row = self._conn.execute(
            "SELECT row_hash FROM security_events ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row and row[0] else ""

    def verify_chain(self) -> Tuple[bool, Optional[int]]:
        """Verify the Merkle hash chain integrity.

        Returns
        -------
        tuple
            ``(True, None)`` if the chain is valid, or
            ``(False, row_id)`` where *row_id* is the first broken link.
        """
        rows = self._conn.execute(
            "SELECT id, timestamp, event_type, findings_json,"
            " content_preview, action_taken, row_hash, prev_hash"
            " FROM security_events ORDER BY id"
        ).fetchall()

        expected_prev = ""
        for row in rows:
            rid, ts, etype, fj, preview, action, stored_hash, stored_prev = row
            # Skip rows that predate the Merkle upgrade
            if not stored_hash:
                continue
            # Verify prev_hash link
            if stored_prev != expected_prev:
                return False, rid
            # Verify row_hash
            hash_input = f"{stored_prev}|{ts}|{etype}|{fj}|{preview}|{action}"
            computed = hashlib.sha256(hash_input.encode()).hexdigest()
            if computed != stored_hash:
                return False, rid
            expected_prev = stored_hash

        return True, None

    def count(self) -> int:
        """Return the total number of logged security events."""
        row = self._conn.execute("SELECT COUNT(*) FROM security_events").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()

    # -- EventBus handler ----------------------------------------------------

    def _on_event(self, event: Event) -> None:
        """Handle an event from the EventBus and log it."""
        data = event.data
        # Map EventType to SecurityEventType
        mapping = {
            EventType.SECURITY_SCAN: SecurityEventType.SECRET_DETECTED,
            EventType.SECURITY_ALERT: SecurityEventType.SECRET_DETECTED,
            EventType.SECURITY_BLOCK: SecurityEventType.SECRET_DETECTED,
        }
        event_type = mapping.get(event.event_type, SecurityEventType.SECRET_DETECTED)

        # Extract findings from event data if present
        findings: List[ScanFinding] = []
        for f in data.get("findings", []):
            findings.append(
                ScanFinding(
                    pattern_name=f.get("pattern", ""),
                    matched_text="",
                    threat_level=ThreatLevel(f.get("threat", "low")),
                    start=0,
                    end=0,
                    description=f.get("description", ""),
                )
            )

        sec_event = SecurityEvent(
            event_type=event_type,
            timestamp=event.timestamp,
            findings=findings,
            content_preview=data.get("content_preview", ""),
            action_taken=data.get("mode", ""),
        )
        self.log(sec_event)


__all__ = ["AuditLogger"]
