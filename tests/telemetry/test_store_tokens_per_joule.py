"""Tests for tokens_per_joule storage and aggregation."""

from __future__ import annotations

import time

import pytest

from friday_ai.core.types import TelemetryRecord
from friday_ai.telemetry.aggregator import TelemetryAggregator
from friday_ai.telemetry.store import TelemetryStore


class TestTokensPerJouleStorage:
    def test_store_and_retrieve(self, tmp_path):
        db = tmp_path / "tel.db"
        store = TelemetryStore(db_path=db)
        rec = TelemetryRecord(
            timestamp=time.time(),
            model_id="test-model",
            completion_tokens=50,
            energy_joules=2.5,
            tokens_per_joule=20.0,
        )
        store.record(rec)
        store.close()
        agg = TelemetryAggregator(db)
        stats = agg.per_model_stats()
        assert len(stats) == 1
        assert stats[0].avg_tokens_per_joule == pytest.approx(20.0, rel=0.1)
        agg.close()

    def test_aggregate_multiple(self, tmp_path):
        db = tmp_path / "tel.db"
        store = TelemetryStore(db_path=db)
        for tpj in [10.0, 20.0, 30.0]:
            rec = TelemetryRecord(
                timestamp=time.time(),
                model_id="m1",
                tokens_per_joule=tpj,
            )
            store.record(rec)
        store.close()
        agg = TelemetryAggregator(db)
        stats = agg.per_model_stats()
        assert stats[0].avg_tokens_per_joule == pytest.approx(20.0, rel=0.1)
        agg.close()

    def test_engine_stats_aggregate(self, tmp_path):
        db = tmp_path / "tel.db"
        store = TelemetryStore(db_path=db)
        for tpj in [15.0, 25.0]:
            rec = TelemetryRecord(
                timestamp=time.time(),
                model_id="m1",
                engine="ollama",
                tokens_per_joule=tpj,
            )
            store.record(rec)
        store.close()
        agg = TelemetryAggregator(db)
        stats = agg.per_engine_stats()
        assert len(stats) == 1
        assert stats[0].avg_tokens_per_joule == pytest.approx(20.0, rel=0.1)
        agg.close()
