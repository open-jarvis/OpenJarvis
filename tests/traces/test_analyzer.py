"""Tests for the TraceAnalyzer."""

from __future__ import annotations

import time
from pathlib import Path

from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.traces.analyzer import TraceAnalyzer
from openjarvis.traces.store import TraceStore


def _make_trace(
    query: str = "test",
    agent: str = "orchestrator",
    model: str = "qwen3:8b",
    outcome: str | None = None,
    feedback: float | None = None,
    latency: float = 1.0,
    tokens: int = 100,
    tool_name: str | None = None,
) -> Trace:
    now = time.time()
    steps = [
        TraceStep(
            step_type=StepType.GENERATE,
            timestamp=now,
            duration_seconds=latency * 0.8,
            input={"model": model},
            output={"tokens": tokens},
        ),
    ]
    if tool_name:
        steps.append(
            TraceStep(
                step_type=StepType.TOOL_CALL,
                timestamp=now + 0.1,
                duration_seconds=latency * 0.2,
                input={"tool": tool_name},
                output={"success": True},
            )
        )
    steps.append(
        TraceStep(
            step_type=StepType.RESPOND,
            timestamp=now + latency,
            duration_seconds=0.0,
            output={"content": "result"},
        )
    )
    return Trace(
        query=query,
        agent=agent,
        model=model,
        engine="ollama",
        result="result",
        outcome=outcome,
        feedback=feedback,
        started_at=now,
        ended_at=now + latency,
        total_tokens=tokens,
        total_latency_seconds=latency,
        steps=steps,
    )


class TestTraceAnalyzer:
    def test_empty_summary(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        analyzer = TraceAnalyzer(store)
        summary = analyzer.summary()
        assert summary.total_traces == 0
        assert summary.total_steps == 0
        store.close()

    def test_summary(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        store.save(_make_trace(outcome="success", latency=1.0, tokens=100))
        store.save(_make_trace(outcome="success", latency=2.0, tokens=200))
        store.save(_make_trace(outcome="failure", latency=0.5, tokens=50))

        analyzer = TraceAnalyzer(store)
        summary = analyzer.summary()
        assert summary.total_traces == 3
        assert summary.avg_latency > 0
        assert summary.avg_tokens > 0
        assert summary.success_rate == 2 / 3
        assert "generate" in summary.step_type_distribution
        assert "respond" in summary.step_type_distribution
        store.close()

    def test_per_route_stats(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        store.save(
            _make_trace(
                model="qwen3:8b",
                agent="simple",
                outcome="success",
                feedback=0.9,
            )
        )
        store.save(
            _make_trace(
                model="qwen3:8b",
                agent="simple",
                outcome="success",
                feedback=0.8,
            )
        )
        store.save(
            _make_trace(
                model="llama3:70b",
                agent="orchestrator",
                outcome="failure",
            )
        )

        analyzer = TraceAnalyzer(store)
        stats = analyzer.per_route_stats()
        assert len(stats) == 2

        qwen_stats = [s for s in stats if s.model == "qwen3:8b"][0]
        assert qwen_stats.count == 2
        assert qwen_stats.success_rate == 1.0
        assert abs(qwen_stats.avg_feedback - 0.85) < 1e-9

        llama_stats = [s for s in stats if s.model == "llama3:70b"][0]
        assert llama_stats.count == 1
        assert llama_stats.success_rate == 0.0
        assert llama_stats.avg_feedback is None
        store.close()

    def test_per_tool_stats(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        store.save(_make_trace(tool_name="calculator"))
        store.save(_make_trace(tool_name="calculator"))
        store.save(_make_trace(tool_name="web_search"))
        store.save(_make_trace())  # no tool

        analyzer = TraceAnalyzer(store)
        stats = analyzer.per_tool_stats()
        assert len(stats) == 2

        calc = [s for s in stats if s.tool_name == "calculator"][0]
        assert calc.call_count == 2
        assert calc.success_rate == 1.0

        web = [s for s in stats if s.tool_name == "web_search"][0]
        assert web.call_count == 1
        store.close()

    def test_per_route_stats_no_evaluated(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        store.save(_make_trace(outcome=None))  # unknown outcome

        analyzer = TraceAnalyzer(store)
        stats = analyzer.per_route_stats()
        assert len(stats) == 1
        assert stats[0].success_rate == 0.0  # no evaluated traces
        store.close()

    def test_export_traces(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        store.save(_make_trace(query="q1"))
        store.save(_make_trace(query="q2"))

        analyzer = TraceAnalyzer(store)
        exported = analyzer.export_traces()
        assert len(exported) == 2
        assert all(isinstance(e, dict) for e in exported)
        assert exported[0]["query"] in ("q1", "q2")
        assert "steps" in exported[0]
        assert len(exported[0]["steps"]) > 0
        store.close()

    def test_traces_for_query_type_code(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        store.save(_make_trace(query="def foo(): pass"))
        store.save(_make_trace(query="what is the weather"))

        analyzer = TraceAnalyzer(store)
        code_traces = analyzer.traces_for_query_type(has_code=True)
        assert len(code_traces) == 1
        assert "def foo" in code_traces[0].query
        store.close()

    def test_traces_for_query_type_length(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        store.save(_make_trace(query="hi"))
        store.save(_make_trace(query="a" * 200))

        analyzer = TraceAnalyzer(store)
        long_traces = analyzer.traces_for_query_type(min_length=100)
        assert len(long_traces) == 1
        store.close()
