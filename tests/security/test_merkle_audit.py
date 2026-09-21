"""Tests for Merkle audit trail (Phase 14.6)."""

from __future__ import annotations

import threading
import time

from openjarvis.security.audit import AuditLogger
from openjarvis.security.types import (
    ScanFinding,
    SecurityEvent,
    SecurityEventType,
    ThreatLevel,
)


def _make_event(
    event_type=SecurityEventType.SECRET_DETECTED,
    content="test content",
    action="warn",
) -> SecurityEvent:
    return SecurityEvent(
        event_type=event_type,
        timestamp=time.time(),
        findings=[
            ScanFinding(
                pattern_name="test_pattern",
                matched_text="xxx",
                threat_level=ThreatLevel.HIGH,
                start=0,
                end=3,
                description="Test finding",
            )
        ],
        content_preview=content,
        action_taken=action,
    )


class TestMerkleAudit:
    def test_log_creates_hash(self, tmp_path):
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(db_path=db_path)
        event = _make_event()
        logger.log(event)
        assert logger.tail_hash() != ""
        logger.close()

    def test_hash_chain_integrity(self, tmp_path):
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(db_path=db_path)
        for i in range(5):
            logger.log(_make_event(content=f"event {i}"))
        valid, broken_at = logger.verify_chain()
        assert valid
        assert broken_at is None
        logger.close()

    def test_prev_hash_links(self, tmp_path):
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(db_path=db_path)

        logger.log(_make_event(content="first"))
        first_hash = logger.tail_hash()
        assert first_hash != ""

        logger.log(_make_event(content="second"))
        second_hash = logger.tail_hash()
        assert second_hash != first_hash

        # Second event's prev_hash should be first_hash
        valid, _ = logger.verify_chain()
        assert valid
        logger.close()

    def test_empty_chain_verifies(self, tmp_path):
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(db_path=db_path)
        valid, broken_at = logger.verify_chain()
        assert valid
        assert broken_at is None
        logger.close()

    def test_tail_hash_empty_on_new_db(self, tmp_path):
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(db_path=db_path)
        assert logger.tail_hash() == ""
        logger.close()

    def test_count_includes_hashed_events(self, tmp_path):
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(db_path=db_path)
        logger.log(_make_event())
        logger.log(_make_event())
        assert logger.count() == 2
        logger.close()

    def test_concurrent_loggers_preserve_chain(self, tmp_path):
        """Concurrent writers must link each event to the committed predecessor."""
        db_path = tmp_path / "audit.db"
        first_tail_read = threading.Event()
        release_first_tail_read = threading.Event()

        class ControlledAuditLogger(AuditLogger):
            def tail_hash(self):
                if not first_tail_read.is_set():
                    first_tail_read.set()
                    assert release_first_tail_read.wait(timeout=5)
                return super().tail_hash()

        loggers = [
            ControlledAuditLogger(db_path=db_path),
            ControlledAuditLogger(db_path=db_path),
        ]
        errors = []

        def write(logger, content):
            try:
                logger.log(_make_event(content=content))
            except Exception as exc:  # noqa: BLE001 - capture race symptoms
                errors.append(exc)

        first = threading.Thread(target=write, args=(loggers[0], "first"))
        second = threading.Thread(target=write, args=(loggers[1], "second"))
        first.start()
        assert first_tail_read.wait(timeout=5)
        second.start()
        release_first_tail_read.set()
        first.join(timeout=5)
        second.join(timeout=5)

        assert errors == []
        assert not first.is_alive()
        assert not second.is_alive()
        for logger in loggers:
            logger.close()

        verifier = AuditLogger(db_path=db_path)
        assert verifier.count() == 2
        assert verifier.verify_chain() == (True, None)
        verifier.close()

    def test_query_returns_events(self, tmp_path):
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(db_path=db_path)
        logger.log(_make_event(content="test query"))
        events = logger.query(limit=10)
        assert len(events) == 1
        assert events[0].content_preview == "test query"
        logger.close()

    def test_schema_migration_idempotent(self, tmp_path):
        db_path = tmp_path / "audit.db"
        logger1 = AuditLogger(db_path=db_path)
        logger1.log(_make_event())
        logger1.close()

        # Re-open — migration should not fail
        logger2 = AuditLogger(db_path=db_path)
        logger2.log(_make_event())
        valid, _ = logger2.verify_chain()
        assert valid
        logger2.close()
