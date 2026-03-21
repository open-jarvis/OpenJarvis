"""Tests for TrainingDataMiner — SFT, routing, and agent config extraction."""

from __future__ import annotations

import time
from typing import Any, List

from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.learning.training.data import TrainingDataMiner

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace(
    *,
    query: str = "Hello world",
    agent: str = "simple",
    model: str = "qwen3:8b",
    engine: str = "ollama",
    result: str = "Hi there!",
    feedback: float | None = 0.9,
    outcome: str | None = "success",
    tools: List[str] | None = None,
) -> Trace:
    """Build a Trace with optional TOOL_CALL steps."""
    now = time.time()
    steps: list[TraceStep] = [
        TraceStep(
            step_type=StepType.GENERATE,
            timestamp=now,
            duration_seconds=0.5,
            input={"prompt": query},
            output={"text": result, "tokens": 10},
        ),
    ]
    if tools:
        for tool_name in tools:
            steps.append(
                TraceStep(
                    step_type=StepType.TOOL_CALL,
                    timestamp=now + 0.1,
                    duration_seconds=0.1,
                    input={"tool": tool_name, "args": {}},
                    output={"result": "ok"},
                )
            )
    steps.append(
        TraceStep(
            step_type=StepType.RESPOND,
            timestamp=now + 1.0,
            duration_seconds=0.0,
            input={},
            output={"text": result},
        )
    )
    return Trace(
        query=query,
        agent=agent,
        model=model,
        engine=engine,
        result=result,
        feedback=feedback,
        outcome=outcome,
        started_at=now,
        ended_at=now + 1.0,
        total_tokens=10,
        total_latency_seconds=1.0,
        steps=steps,
    )


class FakeTraceStore:
    """Minimal mock that satisfies TrainingDataMiner's needs."""

    def __init__(self, traces: list[Trace] | None = None):
        self._traces = traces or []

    def list_traces(self, *, limit: int = 10000, **kwargs: Any) -> list[Trace]:
        return self._traces[:limit]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtractSFTPairs:
    def test_extract_sft_pairs_from_successful_traces(self) -> None:
        """SFT pairs are extracted from high-quality traces."""
        traces = [
            _make_trace(
                query="Write a hello world in Python",
                result="print('hello')",
                feedback=0.9,
            ),
            _make_trace(query="Solve x^2=4", result="x=2 or x=-2", feedback=0.8),
        ]
        store = FakeTraceStore(traces)
        miner = TrainingDataMiner(store)
        pairs = miner.extract_sft_pairs()

        assert len(pairs) == 2
        # Check structure of first pair
        p0 = pairs[0]
        assert p0["input"] == "Write a hello world in Python"
        assert p0["output"] == "print('hello')"
        assert "query_class" in p0
        assert p0["model"] == "qwen3:8b"
        assert p0["feedback"] == 0.9

    def test_deduplication(self) -> None:
        """Duplicate (input, output) pairs are collapsed to a single entry."""
        traces = [
            _make_trace(query="Hi", result="Hello!", feedback=0.9),
            _make_trace(query="Hi", result="Hello!", feedback=0.95),
        ]
        store = FakeTraceStore(traces)
        miner = TrainingDataMiner(store)
        pairs = miner.extract_sft_pairs()

        assert len(pairs) == 1

    def test_min_quality_filter(self) -> None:
        """Traces below min_quality are excluded from SFT pairs."""
        traces = [
            _make_trace(query="Good", result="Fine", feedback=0.9),
            _make_trace(query="Bad", result="Nope", feedback=0.3),
            _make_trace(query="None", result="Null", feedback=None),
        ]
        store = FakeTraceStore(traces)
        miner = TrainingDataMiner(store, min_quality=0.7)
        pairs = miner.extract_sft_pairs()

        assert len(pairs) == 1
        assert pairs[0]["input"] == "Good"


class TestExtractRoutingPairs:
    def test_extract_routing_pairs(self) -> None:
        """Routing pairs group traces by query class and find best model."""
        traces = [
            _make_trace(query="def foo(): pass", model="codellama:7b", feedback=0.95),
            _make_trace(
                query="import os; print(os.getcwd())",
                model="codellama:7b",
                feedback=0.85,
            ),
            _make_trace(query="def bar(): return 1", model="qwen3:8b", feedback=0.7),
        ]
        store = FakeTraceStore(traces)
        miner = TrainingDataMiner(store, min_quality=0.7)
        routing = miner.extract_routing_pairs()

        assert "code" in routing
        code_entry = routing["code"]
        assert code_entry["best_model"] == "codellama:7b"
        assert code_entry["sample_count"] == 3
        assert "codellama:7b" in code_entry["all_models"]
        assert "qwen3:8b" in code_entry["all_models"]


class TestExtractAgentConfigPairs:
    def test_extract_agent_config_pairs(self) -> None:
        """Agent config pairs find best agent and tools per query class."""
        traces = [
            _make_trace(
                query="Calculate 2+2",
                agent="orchestrator",
                tools=["calculator"],
                feedback=0.95,
            ),
            _make_trace(
                query="Compute 3*3",
                agent="orchestrator",
                tools=["calculator", "think"],
                feedback=0.9,
            ),
            _make_trace(
                query="Solve x+1=3",
                agent="simple",
                feedback=0.6,
            ),
        ]
        store = FakeTraceStore(traces)
        miner = TrainingDataMiner(store, min_quality=0.5)
        agent_cfg = miner.extract_agent_config_pairs()

        assert "math" in agent_cfg
        math_entry = agent_cfg["math"]
        assert math_entry["best_agent"] == "orchestrator"
        assert "calculator" in math_entry["best_tools"]
        assert math_entry["sample_count"] == 3


class TestOutcomeFilter:
    def test_failure_traces_excluded_despite_high_feedback(self) -> None:
        """Traces with outcome='failure' are excluded even if feedback is high."""
        traces = [
            _make_trace(
                query="Good query",
                result="Good answer",
                feedback=0.9,
                outcome="success",
            ),
            _make_trace(
                query="Bad query",
                result="Bad answer",
                feedback=0.9,
                outcome="failure",
            ),
        ]
        store = FakeTraceStore(traces)
        miner = TrainingDataMiner(store, min_quality=0.7)

        sft = miner.extract_sft_pairs()
        assert len(sft) == 1
        assert sft[0]["input"] == "Good query"

        routing = miner.extract_routing_pairs()
        total = sum(v["sample_count"] for v in routing.values())
        assert total == 1

        agent_cfg = miner.extract_agent_config_pairs()
        total_agent = sum(v["sample_count"] for v in agent_cfg.values())
        assert total_agent == 1


class TestEmptyStore:
    def test_empty_store_returns_empty(self) -> None:
        """All extractors return empty results for an empty store."""
        store = FakeTraceStore([])
        miner = TrainingDataMiner(store)

        assert miner.extract_sft_pairs() == []
        assert miner.extract_routing_pairs() == {}
        assert miner.extract_agent_config_pairs() == {}
