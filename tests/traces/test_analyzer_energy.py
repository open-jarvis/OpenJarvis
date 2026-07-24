"""Tests for energy aggregation in TraceAnalyzer."""

from __future__ import annotations

import time

import pytest

from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.traces.analyzer import StepTypeStats, TraceAnalyzer
from openjarvis.traces.store import TraceStore


def _make_trace(steps: list[TraceStep]) -> Trace:
    return Trace(
        query="test",
        agent="test_agent",
        model="test_model",
        engine="test_engine",
        steps=steps,
        started_at=time.time(),
        ended_at=time.time() + 10,
        total_tokens=100,
        total_latency_seconds=10.0,
    )


def _gen_step(
    energy: float = 0.0,
    duration: float = 1.0,
    prompt_tokens: int = 50,
    completion_tokens: int = 25,
) -> TraceStep:
    return TraceStep(
        step_type=StepType.GENERATE,
        timestamp=time.time(),
        duration_seconds=duration,
        output={
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        metadata={
            "energy_joules": energy,
            "power_watts": energy / duration if duration > 0 else 0.0,
        },
    )


def _tool_step(duration: float = 0.5) -> TraceStep:
    return TraceStep(
        step_type=StepType.TOOL_CALL,
        timestamp=time.time(),
        duration_seconds=duration,
        input={"tool": "calculator"},
        output={"success": True},
    )


class TestTraceSummaryEnergyFields:
    def test_total_energy_joules(self, tmp_path):
        store = TraceStore(db_path=tmp_path / "traces.db")
        trace = _make_trace(
            [
                _gen_step(energy=10.0, duration=2.0),
                _tool_step(duration=0.5),
                _gen_step(energy=15.0, duration=3.0),
            ]
        )
        store.save(trace)
        analyzer = TraceAnalyzer(store)
        summary = analyzer.summary()
        assert summary.total_energy_joules == pytest.approx(25.0, rel=0.01)
        assert summary.total_generate_energy_joules == pytest.approx(25.0, rel=0.01)
        store.close()

    def test_step_type_stats(self, tmp_path):
        store = TraceStore(db_path=tmp_path / "traces.db")
        trace = _make_trace(
            [
                _gen_step(
                    energy=10.0,
                    duration=2.0,
                    prompt_tokens=100,
                    completion_tokens=50,
                ),
                _gen_step(
                    energy=20.0,
                    duration=4.0,
                    prompt_tokens=80,
                    completion_tokens=40,
                ),
                _tool_step(duration=0.5),
                _tool_step(duration=1.5),
            ]
        )
        store.save(trace)
        analyzer = TraceAnalyzer(store)
        summary = analyzer.summary()

        assert "generate" in summary.step_type_stats
        gen = summary.step_type_stats["generate"]
        assert gen.count == 2
        assert gen.avg_duration == pytest.approx(3.0, rel=0.01)
        assert gen.total_energy == pytest.approx(30.0, rel=0.01)
        assert gen.avg_input_tokens == pytest.approx(90.0, rel=0.01)
        assert gen.avg_output_tokens == pytest.approx(45.0, rel=0.01)
        assert gen.min_duration == pytest.approx(2.0, rel=0.01)
        assert gen.max_duration == pytest.approx(4.0, rel=0.01)

        assert "tool_call" in summary.step_type_stats
        tc = summary.step_type_stats["tool_call"]
        assert tc.count == 2
        assert tc.avg_duration == pytest.approx(1.0, rel=0.01)
        store.close()


class TestStepTypeStats:
    def test_dataclass_fields(self):
        s = StepTypeStats(count=5, avg_duration=2.0, total_energy=10.0)
        assert s.count == 5
        assert s.std_duration == 0.0  # default
