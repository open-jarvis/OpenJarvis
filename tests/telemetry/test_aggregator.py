"""Tests for TelemetryAggregator."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from openjarvis.core.types import TelemetryRecord
from openjarvis.telemetry.aggregator import (
    AggregatedStats,
    EngineStats,
    ModelStats,
    TelemetryAggregator,
)
from openjarvis.telemetry.store import TelemetryStore


def _make_record(
    model_id: str = "test-model",
    engine: str = "ollama",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    latency: float = 1.0,
    cost: float = 0.001,
    ts: float | None = None,
) -> TelemetryRecord:
    return TelemetryRecord(
        timestamp=ts or time.time(),
        model_id=model_id,
        engine=engine,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        latency_seconds=latency,
        cost_usd=cost,
    )


def _setup(tmp_path: Path, records: list[TelemetryRecord] | None = None):
    db = tmp_path / "telemetry.db"
    store = TelemetryStore(db)
    for rec in records or []:
        store.record(rec)
    store.close()
    agg = TelemetryAggregator(db)
    return agg


class TestTelemetryAggregator:
    def test_empty_db_summary(self, tmp_path: Path) -> None:
        agg = _setup(tmp_path)
        s = agg.summary()
        assert s.total_calls == 0
        assert s.total_tokens == 0
        assert s.total_cost == 0.0
        agg.close()

    def test_record_count(self, tmp_path: Path) -> None:
        agg = _setup(tmp_path, [_make_record(), _make_record()])
        assert agg.record_count() == 2
        agg.close()

    def test_single_model_stats(self, tmp_path: Path) -> None:
        agg = _setup(tmp_path, [_make_record(model_id="m1")])
        stats = agg.per_model_stats()
        assert len(stats) == 1
        assert stats[0].model_id == "m1"
        assert stats[0].call_count == 1
        agg.close()

    def test_multiple_models_grouped(self, tmp_path: Path) -> None:
        agg = _setup(
            tmp_path,
            [
                _make_record(model_id="m1"),
                _make_record(model_id="m1"),
                _make_record(model_id="m2"),
            ],
        )
        stats = agg.per_model_stats()
        assert len(stats) == 2
        # Ordered by call_count DESC
        assert stats[0].model_id == "m1"
        assert stats[0].call_count == 2
        assert stats[1].model_id == "m2"
        assert stats[1].call_count == 1
        agg.close()

    def test_per_engine_stats(self, tmp_path: Path) -> None:
        agg = _setup(
            tmp_path,
            [
                _make_record(engine="ollama"),
                _make_record(engine="vllm"),
                _make_record(engine="vllm"),
            ],
        )
        stats = agg.per_engine_stats()
        assert len(stats) == 2
        assert stats[0].engine == "vllm"
        assert stats[0].call_count == 2
        agg.close()

    def test_top_models_limit(self, tmp_path: Path) -> None:
        records = [_make_record(model_id=f"m{i}") for i in range(10)]
        agg = _setup(tmp_path, records)
        top = agg.top_models(n=3)
        assert len(top) == 3
        agg.close()

    def test_top_models_ordering(self, tmp_path: Path) -> None:
        agg = _setup(
            tmp_path,
            [
                _make_record(model_id="rare"),
                _make_record(model_id="popular"),
                _make_record(model_id="popular"),
                _make_record(model_id="popular"),
            ],
        )
        top = agg.top_models(n=2)
        assert top[0].model_id == "popular"
        assert top[0].call_count == 3
        agg.close()

    def test_summary_totals(self, tmp_path: Path) -> None:
        agg = _setup(
            tmp_path,
            [
                _make_record(prompt_tokens=10, completion_tokens=5, cost=0.001),
                _make_record(prompt_tokens=20, completion_tokens=10, cost=0.002),
            ],
        )
        s = agg.summary()
        assert s.total_calls == 2
        assert s.total_tokens == 45  # (10+5) + (20+10)
        assert s.total_cost == pytest.approx(0.003)
        agg.close()

    def test_summary_includes_sub_stats(self, tmp_path: Path) -> None:
        agg = _setup(tmp_path, [_make_record()])
        s = agg.summary()
        assert len(s.per_model) >= 1
        assert len(s.per_engine) >= 1
        agg.close()

    def test_time_range_since(self, tmp_path: Path) -> None:
        now = time.time()
        agg = _setup(
            tmp_path,
            [
                _make_record(ts=now - 100),
                _make_record(ts=now - 10),
                _make_record(ts=now),
            ],
        )
        stats = agg.per_model_stats(since=now - 50)
        total = sum(s.call_count for s in stats)
        assert total == 2
        agg.close()

    def test_time_range_until(self, tmp_path: Path) -> None:
        now = time.time()
        agg = _setup(
            tmp_path,
            [
                _make_record(ts=now - 100),
                _make_record(ts=now),
            ],
        )
        stats = agg.per_model_stats(until=now - 50)
        total = sum(s.call_count for s in stats)
        assert total == 1
        agg.close()

    def test_time_range_since_and_until(self, tmp_path: Path) -> None:
        now = time.time()
        agg = _setup(
            tmp_path,
            [
                _make_record(ts=now - 200),
                _make_record(ts=now - 100),
                _make_record(ts=now),
            ],
        )
        stats = agg.per_model_stats(since=now - 150, until=now - 50)
        total = sum(s.call_count for s in stats)
        assert total == 1
        agg.close()

    def test_export_records_all(self, tmp_path: Path) -> None:
        agg = _setup(tmp_path, [_make_record(), _make_record()])
        records = agg.export_records()
        assert len(records) == 2
        assert "model_id" in records[0]
        agg.close()

    def test_export_records_filtered(self, tmp_path: Path) -> None:
        now = time.time()
        agg = _setup(
            tmp_path,
            [
                _make_record(ts=now - 100),
                _make_record(ts=now),
            ],
        )
        records = agg.export_records(since=now - 50)
        assert len(records) == 1
        agg.close()

    def test_clear_removes_all(self, tmp_path: Path) -> None:
        agg = _setup(tmp_path, [_make_record(), _make_record(), _make_record()])
        deleted = agg.clear()
        assert deleted == 3
        assert agg.record_count() == 0
        agg.close()

    def test_clear_empty_db(self, tmp_path: Path) -> None:
        agg = _setup(tmp_path)
        deleted = agg.clear()
        assert deleted == 0
        agg.close()

    def test_close(self, tmp_path: Path) -> None:
        agg = _setup(tmp_path)
        agg.close()
        # After close, operations should raise
        with pytest.raises(Exception):
            agg.record_count()


class TestDataclassDefaults:
    def test_model_stats_defaults(self) -> None:
        ms = ModelStats()
        assert ms.model_id == ""
        assert ms.call_count == 0
        assert ms.total_tokens == 0

    def test_engine_stats_defaults(self) -> None:
        es = EngineStats()
        assert es.engine == ""
        assert es.call_count == 0

    def test_aggregated_stats_defaults(self) -> None:
        a = AggregatedStats()
        assert a.total_calls == 0
        assert a.per_model == []
        assert a.per_engine == []
