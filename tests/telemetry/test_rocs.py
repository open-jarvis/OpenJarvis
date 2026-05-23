"""Tests for compute_rocs() — energy-weighted RoCS aggregation.

These tests assert exact formula correctness, not just "looks reasonable",
because RoCS is the metric the system optimizes for: an off-by-one in the
join clause silently turns the whole framework into vibes.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from openjarvis.core.types import TelemetryRecord, Trace
from openjarvis.telemetry.aggregator import RoCSRow, TelemetryAggregator
from openjarvis.telemetry.store import TelemetryStore
from openjarvis.traces.store import TraceStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_telemetry(
    tel_path: Path,
    rows: list[dict],
) -> None:
    """Insert telemetry rows. Each dict: trace_id, agent (info-only, stored on
    trace), model, engine, energy_joules, cost_usd, completion_tokens, timestamp.
    """
    store = TelemetryStore(tel_path)
    for r in rows:
        store.record(
            TelemetryRecord(
                timestamp=r["timestamp"],
                model_id=r.get("model", "m1"),
                engine=r.get("engine", "e1"),
                energy_joules=r["energy_joules"],
                cost_usd=r.get("cost_usd", 0.0),
                completion_tokens=r.get("completion_tokens", 10),
                trace_id=r.get("trace_id", ""),
            )
        )
    store.close()


def _seed_traces(traces_path: Path, traces: list[dict]) -> None:
    """Insert trace rows. Each dict: trace_id, agent, model, feedback, started_at."""
    store = TraceStore(traces_path)
    for t in traces:
        store.save(
            Trace(
                trace_id=t["trace_id"],
                query=t.get("query", "q"),
                agent=t["agent"],
                model=t.get("model", "m1"),
                engine=t.get("engine", "e1"),
                result=t.get("result", "r"),
                feedback=t.get("feedback"),
                started_at=t.get("started_at", 1000.0),
                ended_at=t.get("started_at", 1000.0) + 1.0,
            )
        )
    store.close()


# ---------------------------------------------------------------------------
# RoCSRow dataclass properties
# ---------------------------------------------------------------------------


class TestRoCSRow:
    def test_rocs_with_no_graded_energy_is_zero(self):
        r = RoCSRow(bucket="t", graded_energy_joules=0.0, weighted_value_joules=0.0)
        assert r.rocs == 0.0

    def test_rocs_formula(self):
        r = RoCSRow(
            bucket="t", graded_energy_joules=10.0, weighted_value_joules=7.5
        )
        assert r.rocs == 0.75

    def test_pct_graded(self):
        r = RoCSRow(bucket="t", traces_count=4, graded_count=3)
        assert r.pct_graded == 0.75

    def test_pct_graded_with_no_traces_is_zero(self):
        assert RoCSRow(bucket="t").pct_graded == 0.0

    def test_joules_per_trace(self):
        r = RoCSRow(bucket="t", traces_count=5, total_energy_joules=20.0)
        assert r.joules_per_trace == 4.0


# ---------------------------------------------------------------------------
# Empty / missing-db edge cases
# ---------------------------------------------------------------------------


class TestComputeRoCSEmpty:
    def test_empty_telemetry_returns_no_rows(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        TelemetryStore(tel).close()
        TraceStore(traces).close()
        agg = TelemetryAggregator(tel)
        try:
            assert agg.compute_rocs(traces) == []
        finally:
            agg.close()

    def test_missing_traces_db_yields_all_ungraded(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        missing_traces = tmp_path / "does_not_exist.db"
        _seed_telemetry(
            tel,
            [
                {"timestamp": 1.0, "trace_id": "T1", "energy_joules": 2.0},
                {"timestamp": 2.0, "trace_id": "T2", "energy_joules": 3.0},
                {"timestamp": 3.0, "trace_id": "", "energy_joules": 1.0},
            ],
        )
        agg = TelemetryAggregator(tel)
        try:
            rows = agg.compute_rocs(missing_traces)
            # Should still get aggregation; no traces.db means no agent attribution
            assert len(rows) == 1
            r = rows[0]
            assert r.graded_count == 0
            assert r.ungraded_calls == 3
            assert r.total_energy_joules == 6.0
            assert r.rocs == 0.0
            # And the file MUST NOT have been created as a side-effect
            assert not missing_traces.exists()
        finally:
            agg.close()


# ---------------------------------------------------------------------------
# Exact RoCS formula correctness
# ---------------------------------------------------------------------------


class TestComputeRoCSFormula:
    def test_single_graded_trace_rocs_equals_feedback(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        _seed_telemetry(
            tel,
            [{"timestamp": 1.0, "trace_id": "T1", "energy_joules": 10.0}],
        )
        _seed_traces(traces, [{"trace_id": "T1", "agent": "a1", "feedback": 1.0}])

        agg = TelemetryAggregator(tel)
        try:
            rows = agg.compute_rocs(traces, group_by="agent")
            assert len(rows) == 1
            r = rows[0]
            assert r.bucket == "a1"
            assert r.traces_count == 1
            assert r.graded_count == 1
            assert r.ungraded_calls == 0
            assert r.graded_energy_joules == 10.0
            assert r.weighted_value_joules == 10.0
            assert r.rocs == 1.0
        finally:
            agg.close()

    def test_weighted_mean_across_two_traces(self, tmp_path: Path):
        """RoCS = sum(feedback * energy) / sum(graded_energy).

        Trace A: feedback=1.0, 10J  ->  contributes 10 value, 10 energy
        Trace B: feedback=0.5, 20J  ->  contributes 10 value, 20 energy
        => RoCS = 20 / 30 = 0.6667
        """
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        _seed_telemetry(
            tel,
            [
                {"timestamp": 1.0, "trace_id": "A", "energy_joules": 10.0},
                {"timestamp": 2.0, "trace_id": "B", "energy_joules": 20.0},
            ],
        )
        _seed_traces(
            traces,
            [
                {"trace_id": "A", "agent": "same_agent", "feedback": 1.0},
                {"trace_id": "B", "agent": "same_agent", "feedback": 0.5},
            ],
        )

        agg = TelemetryAggregator(tel)
        try:
            rows = agg.compute_rocs(traces, group_by="agent")
            assert len(rows) == 1
            r = rows[0]
            assert r.traces_count == 2
            assert r.graded_count == 2
            assert r.graded_energy_joules == 30.0
            assert r.weighted_value_joules == 20.0
            assert r.rocs == pytest.approx(20.0 / 30.0)
        finally:
            agg.close()

    def test_ungraded_traces_excluded_from_rocs_but_counted_in_total(
        self, tmp_path: Path
    ):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        _seed_telemetry(
            tel,
            [
                {"timestamp": 1.0, "trace_id": "G", "energy_joules": 5.0},
                {"timestamp": 2.0, "trace_id": "U", "energy_joules": 100.0},
                {"timestamp": 3.0, "trace_id": "", "energy_joules": 50.0},
            ],
        )
        _seed_traces(
            traces,
            [
                {"trace_id": "G", "agent": "a", "feedback": 0.8},
                {"trace_id": "U", "agent": "a"},  # no feedback
            ],
        )

        agg = TelemetryAggregator(tel)
        try:
            rows = agg.compute_rocs(traces, group_by="agent")
            # One bucket: "a". Direct-call (empty trace_id) buckets to "" (separate row).
            buckets = {r.bucket: r for r in rows}
            r_a = buckets["a"]
            assert r_a.traces_count == 2  # G + U
            assert r_a.graded_count == 1  # only G
            assert r_a.ungraded_calls == 1  # U has no feedback
            assert r_a.total_energy_joules == 105.0
            assert r_a.graded_energy_joules == 5.0
            assert r_a.weighted_value_joules == pytest.approx(0.8 * 5.0)
            assert r_a.rocs == pytest.approx(0.8)

            # Direct-call row (trace_id='') buckets to '' under agent grouping
            r_direct = buckets[""]
            assert r_direct.ungraded_calls == 1
            assert r_direct.total_energy_joules == 50.0
            assert r_direct.graded_count == 0
            assert r_direct.rocs == 0.0
        finally:
            agg.close()

    def test_multiple_telemetry_rows_per_trace(self, tmp_path: Path):
        """If a single trace produced N inference calls, each row gets the
        same trace's feedback, and the energy-weighted formula stays consistent."""
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        _seed_telemetry(
            tel,
            [
                {"timestamp": 1.0, "trace_id": "X", "energy_joules": 4.0},
                {"timestamp": 1.1, "trace_id": "X", "energy_joules": 4.0},
                {"timestamp": 1.2, "trace_id": "X", "energy_joules": 4.0},
            ],
        )
        _seed_traces(traces, [{"trace_id": "X", "agent": "a", "feedback": 0.9}])

        agg = TelemetryAggregator(tel)
        try:
            rows = agg.compute_rocs(traces, group_by="agent")
            assert len(rows) == 1
            r = rows[0]
            assert r.traces_count == 1  # distinct trace_ids
            assert r.graded_count == 1
            assert r.graded_energy_joules == 12.0
            assert r.weighted_value_joules == pytest.approx(0.9 * 12.0)
            assert r.rocs == pytest.approx(0.9)
        finally:
            agg.close()


# ---------------------------------------------------------------------------
# Grouping options
# ---------------------------------------------------------------------------


class TestComputeRoCSGrouping:
    def test_group_by_agent_separates_buckets(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        _seed_telemetry(
            tel,
            [
                {"timestamp": 1.0, "trace_id": "A", "energy_joules": 10.0},
                {"timestamp": 2.0, "trace_id": "B", "energy_joules": 20.0},
            ],
        )
        _seed_traces(
            traces,
            [
                {"trace_id": "A", "agent": "agent_one", "feedback": 1.0},
                {"trace_id": "B", "agent": "agent_two", "feedback": 0.0},
            ],
        )

        agg = TelemetryAggregator(tel)
        try:
            rows = {r.bucket: r for r in agg.compute_rocs(traces, group_by="agent")}
            assert rows["agent_one"].rocs == 1.0
            assert rows["agent_two"].rocs == 0.0
            # ORDER BY total_energy_joules DESC: agent_two (20J) before agent_one (10J)
            buckets_in_order = [
                r.bucket for r in agg.compute_rocs(traces, group_by="agent")
            ]
            assert buckets_in_order == ["agent_two", "agent_one"]
        finally:
            agg.close()

    def test_group_by_model(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        _seed_telemetry(
            tel,
            [
                {"timestamp": 1.0, "trace_id": "A", "model": "fast", "energy_joules": 5.0},
                {"timestamp": 2.0, "trace_id": "B", "model": "fast", "energy_joules": 5.0},
                {"timestamp": 3.0, "trace_id": "C", "model": "slow", "energy_joules": 50.0},
            ],
        )
        _seed_traces(
            traces,
            [
                {"trace_id": "A", "agent": "x", "feedback": 1.0},
                {"trace_id": "B", "agent": "x", "feedback": 1.0},
                {"trace_id": "C", "agent": "x", "feedback": 1.0},
            ],
        )

        agg = TelemetryAggregator(tel)
        try:
            rows = {r.bucket: r for r in agg.compute_rocs(traces, group_by="model")}
            # Same feedback across all traces → RoCS = 1.0 for both buckets
            assert rows["fast"].rocs == 1.0
            assert rows["slow"].rocs == 1.0
            # But "fast" did the same work for 1/5 the energy → 2 traces in 10J
            assert rows["fast"].graded_energy_joules == 10.0
            assert rows["slow"].graded_energy_joules == 50.0
        finally:
            agg.close()

    def test_group_by_day(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        # 2026-05-23 00:30 UTC and 2026-05-24 00:30 UTC
        d1 = 1779_523_800.0  # placeholder; SQLite date() handles real epochs
        d2 = d1 + 86_400
        _seed_telemetry(
            tel,
            [
                {"timestamp": d1, "trace_id": "A", "energy_joules": 10.0},
                {"timestamp": d2, "trace_id": "B", "energy_joules": 20.0},
            ],
        )
        _seed_traces(
            traces,
            [
                {"trace_id": "A", "agent": "x", "feedback": 1.0},
                {"trace_id": "B", "agent": "x", "feedback": 0.5},
            ],
        )

        agg = TelemetryAggregator(tel)
        try:
            rows = agg.compute_rocs(traces, group_by="day")
            assert len(rows) == 2
            # Bucket is YYYY-MM-DD; we don't assert specific dates (timezones)
            # — just that two distinct day buckets exist.
            assert len({r.bucket for r in rows}) == 2
        finally:
            agg.close()

    def test_invalid_group_by_raises(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        TelemetryStore(tel).close()
        TraceStore(traces).close()
        agg = TelemetryAggregator(tel)
        try:
            with pytest.raises(ValueError, match="group_by"):
                agg.compute_rocs(traces, group_by="not_a_real_dimension")
        finally:
            agg.close()


# ---------------------------------------------------------------------------
# Time window filtering
# ---------------------------------------------------------------------------


class TestComputeRoCSWindow:
    def test_since_filter_excludes_old_rows(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        _seed_telemetry(
            tel,
            [
                {"timestamp": 100.0, "trace_id": "old", "energy_joules": 999.0},
                {"timestamp": 200.0, "trace_id": "new", "energy_joules": 10.0},
            ],
        )
        _seed_traces(
            traces,
            [
                {"trace_id": "old", "agent": "x", "feedback": 0.0},
                {"trace_id": "new", "agent": "x", "feedback": 1.0},
            ],
        )

        agg = TelemetryAggregator(tel)
        try:
            rows = agg.compute_rocs(traces, since=150.0)
            assert len(rows) == 1
            r = rows[0]
            assert r.traces_count == 1
            assert r.rocs == 1.0
            assert r.total_energy_joules == 10.0
        finally:
            agg.close()


# ---------------------------------------------------------------------------
# Overall summary
# ---------------------------------------------------------------------------


class TestComputeRoCSOverall:
    def test_overall_sums_across_buckets(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        _seed_telemetry(
            tel,
            [
                {"timestamp": 1.0, "trace_id": "A", "energy_joules": 10.0},
                {"timestamp": 2.0, "trace_id": "B", "energy_joules": 20.0},
            ],
        )
        _seed_traces(
            traces,
            [
                {"trace_id": "A", "agent": "one", "feedback": 1.0},
                {"trace_id": "B", "agent": "two", "feedback": 0.5},
            ],
        )

        agg = TelemetryAggregator(tel)
        try:
            overall = agg.compute_rocs_overall(traces)
            assert overall.bucket == "ALL"
            assert overall.traces_count == 2
            assert overall.graded_count == 2
            assert overall.total_energy_joules == 30.0
            assert overall.graded_energy_joules == 30.0
            assert overall.weighted_value_joules == pytest.approx(10.0 + 10.0)
            assert overall.rocs == pytest.approx(20.0 / 30.0)
        finally:
            agg.close()


# ---------------------------------------------------------------------------
# DETACH cleanup — attach handle must be released so a second call works
# ---------------------------------------------------------------------------


class TestAttachCleanup:
    def test_attach_is_idempotent_across_calls(self, tmp_path: Path):
        tel = tmp_path / "tel.db"
        traces = tmp_path / "traces.db"
        _seed_telemetry(
            tel, [{"timestamp": 1.0, "trace_id": "T", "energy_joules": 1.0}]
        )
        _seed_traces(traces, [{"trace_id": "T", "agent": "x", "feedback": 0.5}])

        agg = TelemetryAggregator(tel)
        try:
            # Two sequential calls — second would fail with "database already attached"
            # if we forgot to DETACH.
            r1 = agg.compute_rocs(traces, group_by="agent")
            r2 = agg.compute_rocs(traces, group_by="model")
            assert r1 and r2
        finally:
            agg.close()
