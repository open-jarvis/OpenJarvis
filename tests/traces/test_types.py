"""Tests for Trace and TraceStep types."""

from __future__ import annotations

import time

from openjarvis.core.types import StepType, Trace, TraceStep


class TestTraceStep:
    def test_create_step(self) -> None:
        step = TraceStep(
            step_type=StepType.GENERATE,
            timestamp=time.time(),
            duration_seconds=0.5,
            input={"model": "qwen3:8b"},
            output={"tokens": 100},
        )
        assert step.step_type == StepType.GENERATE
        assert step.duration_seconds == 0.5
        assert step.output["tokens"] == 100

    def test_step_defaults(self) -> None:
        step = TraceStep(step_type=StepType.ROUTE, timestamp=0.0)
        assert step.duration_seconds == 0.0
        assert step.input == {}
        assert step.output == {}
        assert step.metadata == {}

    def test_all_step_types(self) -> None:
        for st in StepType:
            step = TraceStep(step_type=st, timestamp=0.0)
            assert step.step_type == st


class TestTrace:
    def test_create_trace(self) -> None:
        trace = Trace(query="What is 2+2?", agent="orchestrator", model="qwen3:8b")
        assert trace.query == "What is 2+2?"
        assert trace.agent == "orchestrator"
        assert len(trace.trace_id) == 16  # hex uuid

    def test_trace_id_unique(self) -> None:
        t1 = Trace()
        t2 = Trace()
        assert t1.trace_id != t2.trace_id

    def test_add_step(self) -> None:
        trace = Trace(query="test")
        step = TraceStep(
            step_type=StepType.GENERATE,
            timestamp=time.time(),
            duration_seconds=1.0,
            output={"tokens": 50},
        )
        trace.add_step(step)
        assert len(trace.steps) == 1
        assert trace.total_latency_seconds == 1.0
        assert trace.total_tokens == 50

    def test_add_multiple_steps(self) -> None:
        trace = Trace(query="test")
        trace.add_step(
            TraceStep(
                step_type=StepType.RETRIEVE,
                timestamp=0.0,
                duration_seconds=0.3,
                output={"tokens": 0},
            )
        )
        trace.add_step(
            TraceStep(
                step_type=StepType.GENERATE,
                timestamp=0.0,
                duration_seconds=1.0,
                output={"tokens": 100},
            )
        )
        trace.add_step(
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=0.0,
                duration_seconds=0.5,
                output={"tokens": 0},
            )
        )
        assert len(trace.steps) == 3
        assert trace.total_latency_seconds == 1.8
        assert trace.total_tokens == 100

    def test_trace_defaults(self) -> None:
        trace = Trace()
        assert trace.query == ""
        assert trace.agent == ""
        assert trace.model == ""
        assert trace.outcome is None
        assert trace.feedback is None
        assert trace.steps == []
        assert trace.total_tokens == 0

    def test_trace_with_outcome(self) -> None:
        trace = Trace(query="test", outcome="success", feedback=0.9)
        assert trace.outcome == "success"
        assert trace.feedback == 0.9
