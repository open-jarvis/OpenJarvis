"""Tests for AuditLogger."""

from __future__ import annotations

import time
from pathlib import Path

from openjarvis.core.events import EventBus, EventType
from openjarvis.security.audit import AuditLogger
from openjarvis.security.types import (
    ScanFinding,
    SecurityEvent,
    SecurityEventType,
    ThreatLevel,
)


class TestAuditLogger:
    def test_log_and_query(self, tmp_path: Path) -> None:
        logger = AuditLogger(db_path=tmp_path / "audit.db")
        event = SecurityEvent(
            event_type=SecurityEventType.SECRET_DETECTED,
            timestamp=time.time(),
            findings=[
                ScanFinding(
                    pattern_name="openai_key",
                    matched_text="sk-abc123...",
                    threat_level=ThreatLevel.CRITICAL,
                    start=0,
                    end=12,
                    description="OpenAI API key",
                )
            ],
            content_preview="sk-abc123...",
            action_taken="warn",
        )
        logger.log(event)

        results = logger.query()
        assert len(results) == 1
        assert results[0].event_type == SecurityEventType.SECRET_DETECTED
        assert len(results[0].findings) == 1
        assert results[0].findings[0].pattern_name == "openai_key"
        assert results[0].action_taken == "warn"
        logger.close()

    def test_count(self, tmp_path: Path) -> None:
        logger = AuditLogger(db_path=tmp_path / "audit.db")
        assert logger.count() == 0

        for i in range(3):
            event = SecurityEvent(
                event_type=SecurityEventType.PII_DETECTED,
                timestamp=time.time() + i,
            )
            logger.log(event)

        assert logger.count() == 3
        logger.close()

    def test_query_by_type(self, tmp_path: Path) -> None:
        logger = AuditLogger(db_path=tmp_path / "audit.db")

        logger.log(
            SecurityEvent(
                event_type=SecurityEventType.SECRET_DETECTED,
                timestamp=time.time(),
            )
        )
        logger.log(
            SecurityEvent(
                event_type=SecurityEventType.PII_DETECTED,
                timestamp=time.time(),
            )
        )
        logger.log(
            SecurityEvent(
                event_type=SecurityEventType.SECRET_DETECTED,
                timestamp=time.time(),
            )
        )

        secrets = logger.query(event_type="secret_detected")
        assert len(secrets) == 2

        pii = logger.query(event_type="pii_detected")
        assert len(pii) == 1
        logger.close()

    def test_query_since(self, tmp_path: Path) -> None:
        logger = AuditLogger(db_path=tmp_path / "audit.db")

        t1 = time.time() - 100
        t2 = time.time()

        logger.log(
            SecurityEvent(
                event_type=SecurityEventType.SECRET_DETECTED,
                timestamp=t1,
            )
        )
        logger.log(
            SecurityEvent(
                event_type=SecurityEventType.SECRET_DETECTED,
                timestamp=t2,
            )
        )

        recent = logger.query(since=t2 - 1)
        assert len(recent) == 1
        logger.close()

    def test_bus_subscription(self, tmp_path: Path) -> None:
        bus = EventBus()
        logger = AuditLogger(db_path=tmp_path / "audit.db", bus=bus)

        bus.publish(
            EventType.SECURITY_ALERT,
            {
                "direction": "output",
                "findings": [
                    {
                        "pattern": "openai_key",
                        "threat": "critical",
                        "description": "OpenAI API key",
                    }
                ],
                "mode": "warn",
            },
        )

        assert logger.count() == 1
        results = logger.query()
        assert len(results) == 1
        assert results[0].action_taken == "warn"
        assert len(results[0].findings) == 1
        assert results[0].findings[0].pattern_name == "openai_key"
        logger.close()

    def test_bus_subscription_block_event(self, tmp_path: Path) -> None:
        bus = EventBus()
        logger = AuditLogger(db_path=tmp_path / "audit.db", bus=bus)

        bus.publish(
            EventType.SECURITY_BLOCK,
            {
                "direction": "input",
                "findings": [],
                "mode": "block",
            },
        )

        assert logger.count() == 1
        logger.close()

    def test_close_and_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "audit.db"
        logger = AuditLogger(db_path=db_path)
        logger.log(
            SecurityEvent(
                event_type=SecurityEventType.SECRET_DETECTED,
                timestamp=time.time(),
            )
        )
        logger.close()

        logger2 = AuditLogger(db_path=db_path)
        assert logger2.count() == 1
        logger2.close()
