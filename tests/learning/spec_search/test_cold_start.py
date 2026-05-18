"""Tests for openjarvis.learning.spec_search.gate.cold_start module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from unittest.mock import MagicMock


@dataclass
class _StubTrace:
    trace_id: str = "t1"
    query: str = "test"
    feedback: Optional[float] = 0.8
    agent: str = "simple"
    model: str = "qwen"
    outcome: Optional[str] = "success"
    result: str = "answer"
    started_at: float = 1712534400.0
    ended_at: float = 1712534401.0
    steps: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    total_tokens: int = 100
    total_latency_seconds: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    engine: str = "ollama"


def _make_trace_store(count: int = 0, high_feedback_count: int = 0) -> MagicMock:
    store = MagicMock()
    store.count.return_value = count
    # list_traces returns traces with high feedback
    high_traces = [
        _StubTrace(trace_id=f"t{i}", feedback=0.9) for i in range(high_feedback_count)
    ]
    store.list_traces.return_value = high_traces
    return store


class TestCheckReadiness:
    """Tests for check_readiness()."""

    def test_not_ready_with_no_traces(self) -> None:
        from openjarvis.learning.spec_search.gate.cold_start import (
            check_readiness,
        )

        store = _make_trace_store(count=0)
        result = check_readiness(store, min_traces=20)
        assert not result.ready
        assert "not enough traces" in result.message.lower()

    def test_not_ready_with_few_traces(self) -> None:
        from openjarvis.learning.spec_search.gate.cold_start import (
            check_readiness,
        )

        store = _make_trace_store(count=10)
        result = check_readiness(store, min_traces=20)
        assert not result.ready

    def test_ready_with_enough_traces(self) -> None:
        from openjarvis.learning.spec_search.gate.cold_start import (
            check_readiness,
        )

        store = _make_trace_store(count=25)
        result = check_readiness(store, min_traces=20)
        assert result.ready


class TestCheckBenchmarkReady:
    """Tests for check_benchmark_ready()."""

    def test_not_ready_with_no_high_feedback_traces(self) -> None:
        from openjarvis.learning.spec_search.gate.cold_start import (
            check_benchmark_ready,
        )

        store = _make_trace_store(count=30, high_feedback_count=0)
        result = check_benchmark_ready(store, min_feedback=0.7, min_samples=10)
        assert not result.ready
        assert "benchmark" in result.message.lower()

    def test_not_ready_with_few_high_feedback_traces(self) -> None:
        from openjarvis.learning.spec_search.gate.cold_start import (
            check_benchmark_ready,
        )

        store = _make_trace_store(count=30, high_feedback_count=5)
        result = check_benchmark_ready(store, min_feedback=0.7, min_samples=10)
        assert not result.ready

    def test_ready_with_enough_high_feedback_traces(self) -> None:
        from openjarvis.learning.spec_search.gate.cold_start import (
            check_benchmark_ready,
        )

        store = _make_trace_store(count=30, high_feedback_count=15)
        result = check_benchmark_ready(store, min_feedback=0.7, min_samples=10)
        assert result.ready
