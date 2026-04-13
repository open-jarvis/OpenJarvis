"""Tests for the telemetry SQLite store."""

from __future__ import annotations

import time
from pathlib import Path

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import TelemetryRecord
from openjarvis.telemetry.store import TelemetryStore


class TestTelemetryStore:
    def test_creates_table(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "test.db")
        rows = store._fetchall()
        assert rows == []
        store.close()

    def test_record_values(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "test.db")
        rec = TelemetryRecord(
            timestamp=time.time(),
            model_id="qwen3:8b",
            engine="ollama",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_seconds=0.5,
            cost_usd=0.001,
        )
        store.record(rec)
        rows = store._fetchall()
        assert len(rows) == 1
        assert rows[0][2] == "qwen3:8b"  # model_id column
        store.close()

    def test_bus_subscription(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "test.db")
        bus = EventBus()
        store.subscribe_to_bus(bus)

        rec = TelemetryRecord(
            timestamp=time.time(),
            model_id="test-model",
            engine="vllm",
        )
        bus.publish(EventType.TELEMETRY_RECORD, {"record": rec})

        rows = store._fetchall()
        assert len(rows) == 1
        assert rows[0][2] == "test-model"
        store.close()

    def test_close_and_reopen(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        store = TelemetryStore(db_path)
        rec = TelemetryRecord(timestamp=time.time(), model_id="m1", engine="e1")
        store.record(rec)
        store.close()

        store2 = TelemetryStore(db_path)
        rows = store2._fetchall()
        assert len(rows) == 1
        store2.close()

    def test_metadata_json_roundtrip(self, tmp_path: Path) -> None:
        store = TelemetryStore(tmp_path / "test.db")
        rec = TelemetryRecord(
            timestamp=time.time(),
            model_id="m1",
            engine="e1",
            metadata={"key": "value", "nested": [1, 2, 3]},
        )
        store.record(rec)
        import json

        rows = store._fetchall()
        meta = json.loads(rows[0][-1])  # metadata is last column
        assert meta["key"] == "value"
        assert meta["nested"] == [1, 2, 3]
        store.close()


class TestTelemetryRecordFields:
    def test_tokens_per_joule_field_exists(self):
        rec = TelemetryRecord(timestamp=1.0, model_id="test")
        assert hasattr(rec, "tokens_per_joule")
        assert rec.tokens_per_joule == 0.0

    def test_tokens_per_joule_set(self):
        rec = TelemetryRecord(timestamp=1.0, model_id="test", tokens_per_joule=80.0)
        assert rec.tokens_per_joule == 80.0
