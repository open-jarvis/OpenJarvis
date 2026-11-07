"""Tests for LearningOrchestrator -- coordinate trace->learn->eval loop."""

from __future__ import annotations

import time
from pathlib import Path

from friday_ai.core.types import StepType, Trace, TraceStep
from friday_ai.learning.learning_orchestrator import LearningOrchestrator
from friday_ai.traces.store import TraceStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace(
    *,
    query: str = "hello",
    agent: str = "orchestrator",
    model: str = "qwen3:8b",
    tools: list[str] | None = None,
    outcome: str = "success",
    feedback: float = 0.9,
) -> Trace:
    """Build a Trace with TOOL_CALL steps for the given tool names."""
    steps: list[TraceStep] = []
    for tool_name in tools or []:
        steps.append(
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=time.time(),
                duration_seconds=0.1,
                input={"tool": tool_name, "args": {}},
                output={"result": "ok"},
            )
        )
    steps.append(
        TraceStep(
            step_type=StepType.GENERATE,
            timestamp=time.time(),
            duration_seconds=0.5,
            input={"prompt": query},
            output={"content": "answer", "tokens": 50},
        )
    )
    return Trace(
        query=query,
        agent=agent,
        model=model,
        steps=steps,
        result="answer",
        outcome=outcome,
        feedback=feedback,
        started_at=time.time(),
        ended_at=time.time() + 1.0,
        total_tokens=50,
        total_latency_seconds=0.6,
    )


def _populate_store(store: TraceStore, count: int = 10) -> None:
    """Save *count* high-quality traces into the store."""
    for i in range(count):
        t = _make_trace(
            query=f"calculate {i + 1} + {i + 2}",
            agent="orchestrator",
            model="qwen3:8b",
            tools=["calculator", "think"],
            outcome="success",
            feedback=0.9,
        )
        store.save(t)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLearningOrchestrator:
    def test_run_with_no_traces_is_noop(self, tmp_path: Path) -> None:
        """Empty trace store -> status='skipped', reason mentions no data."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        orch = LearningOrchestrator(
            trace_store=store,
            config_dir=config_dir,
        )
        result = orch.run()

        assert result["status"] == "skipped"
        assert "no" in result["reason"].lower() or "data" in result["reason"].lower()
        assert "timestamp" in result
        store.close()

    def test_run_extracts_data_and_updates_routing(self, tmp_path: Path) -> None:
        """With traces present, run extracts data and result has counts."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        _populate_store(store, count=10)

        orch = LearningOrchestrator(
            trace_store=store,
            config_dir=config_dir,
        )
        result = orch.run()

        assert result["status"] in ("completed", "skipped")
        # Should have extracted some data counts
        assert "sft_pairs" in result or "routing_classes" in result
        assert "timestamp" in result
        store.close()

    def test_run_with_eval_gate_rejects(self, tmp_path: Path) -> None:
        """eval_fn returns worse score after learning -> accepted=False."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        _populate_store(store, count=10)

        # First call (baseline) returns 0.8, second call (post) returns 0.7
        call_count = 0

        def eval_fn() -> float:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 0.8
            return 0.7  # worse

        orch = LearningOrchestrator(
            trace_store=store,
            config_dir=config_dir,
            eval_fn=eval_fn,
            min_improvement=0.02,
        )
        result = orch.run()

        assert result.get("accepted") is False or result["status"] == "rejected"
        assert "timestamp" in result
        store.close()

    def test_run_with_eval_gate_accepts(self, tmp_path: Path) -> None:
        """eval_fn returns better score after learning -> accepted=True."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        _populate_store(store, count=10)

        # First call (baseline) returns 0.7, second call (post) returns 0.8
        call_count = 0

        def eval_fn() -> float:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return 0.7
            return 0.8  # better

        orch = LearningOrchestrator(
            trace_store=store,
            config_dir=config_dir,
            eval_fn=eval_fn,
            min_improvement=0.02,
        )
        result = orch.run()

        assert result.get("accepted") is True or result["status"] == "completed"
        assert "timestamp" in result
        store.close()

    def test_run_records_timestamp(self, tmp_path: Path) -> None:
        """Result always has a 'timestamp' key regardless of outcome."""
        db = tmp_path / "traces.db"
        store = TraceStore(db)
        config_dir = tmp_path / "configs"

        # Test with empty store
        orch = LearningOrchestrator(
            trace_store=store,
            config_dir=config_dir,
        )
        result = orch.run()

        assert "timestamp" in result
        assert isinstance(result["timestamp"], (int, float, str))
        store.close()
