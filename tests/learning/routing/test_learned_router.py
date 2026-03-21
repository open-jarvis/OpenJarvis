"""Tests for LearnedRouterPolicy (merged trace-driven + SFT routing)."""

from __future__ import annotations

import time
from pathlib import Path

from openjarvis.core.types import StepType, Trace, TraceStep
from openjarvis.learning._stubs import RoutingContext
from openjarvis.learning.routing.learned_router import LearnedRouterPolicy
from openjarvis.traces.analyzer import TraceAnalyzer
from openjarvis.traces.store import TraceStore


def _make_trace(
    query: str = "test",
    model: str = "qwen3:8b",
    outcome: str | None = "success",
    feedback: float | None = 0.8,
) -> Trace:
    now = time.time()
    return Trace(
        query=query,
        agent="orchestrator",
        model=model,
        engine="ollama",
        result="result",
        outcome=outcome,
        feedback=feedback,
        started_at=now,
        ended_at=now + 0.5,
        total_tokens=100,
        total_latency_seconds=0.5,
        steps=[
            TraceStep(
                step_type=StepType.GENERATE,
                timestamp=now,
                duration_seconds=0.5,
                output={"tokens": 100},
            ),
        ],
    )


class TestLearnedRouterPolicy:
    def test_registered_as_learned(self) -> None:
        from openjarvis.core.registry import RouterPolicyRegistry
        from openjarvis.learning.routing.learned_router import ensure_registered

        ensure_registered()
        assert RouterPolicyRegistry.contains("learned")

    def test_fallback_no_traces(self) -> None:
        policy = LearnedRouterPolicy(default_model="qwen3:8b")
        ctx = RoutingContext(query="hello")
        assert policy.select_model(ctx) == "qwen3:8b"

    def test_fallback_chain(self) -> None:
        policy = LearnedRouterPolicy(
            default_model="missing",
            fallback_model="llama3:8b",
            available_models=["llama3:8b"],
        )
        ctx = RoutingContext(query="hello")
        assert policy.select_model(ctx) == "llama3:8b"

    def test_update_from_traces(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        for _ in range(6):
            store.save(
                _make_trace(
                    query="def foo(): pass",
                    model="codestral",
                    outcome="success",
                    feedback=0.9,
                )
            )
        for _ in range(6):
            store.save(
                _make_trace(
                    query="def bar(): return 1",
                    model="qwen3:8b",
                    outcome="failure",
                    feedback=0.3,
                )
            )

        analyzer = TraceAnalyzer(store)
        policy = LearnedRouterPolicy(
            analyzer=analyzer,
            default_model="qwen3:8b",
        )
        policy.min_samples = 3
        result = policy.update_from_traces()
        assert result["updated"] is True

        ctx = RoutingContext(query="import os; def main(): pass")
        assert policy.select_model(ctx) == "codestral"
        store.close()

    def test_policy_map_readable(self, tmp_path: Path) -> None:
        store = TraceStore(tmp_path / "test.db")
        for _ in range(5):
            store.save(
                _make_trace(
                    query="hello",
                    model="small-model",
                    outcome="success",
                )
            )

        analyzer = TraceAnalyzer(store)
        policy = LearnedRouterPolicy(analyzer=analyzer, default_model="default")
        policy.min_samples = 3
        policy.update_from_traces()

        pmap = policy.policy_map
        assert isinstance(pmap, dict)
        assert "short" in pmap
        assert pmap["short"] == "small-model"
        store.close()

    def test_observe_online(self) -> None:
        policy = LearnedRouterPolicy(default_model="default")
        policy.min_samples = 3
        policy.observe("hello", "fast-model", "success", 0.9)
        assert policy.policy_map.get("short") == "fast-model"

    def test_batch_update(self) -> None:
        """Test the batch update() method inherited from SFT routing logic."""
        from unittest.mock import MagicMock

        policy = LearnedRouterPolicy(default_model="default")
        mock_store = MagicMock()
        mock_store.list_traces.return_value = [
            _make_trace(
                query="def foo(): pass",
                model="code-model",
                outcome="success",
                feedback=0.9,
            ),
            _make_trace(
                query="def bar(): pass",
                model="code-model",
                outcome="success",
                feedback=0.85,
            ),
            _make_trace(
                query="def baz(): pass",
                model="code-model",
                outcome="success",
                feedback=0.88,
            ),
            _make_trace(
                query="def qux(): pass",
                model="code-model",
                outcome="success",
                feedback=0.92,
            ),
            _make_trace(
                query="def quux(): pass",
                model="code-model",
                outcome="success",
                feedback=0.87,
            ),
        ]
        result = policy.update(mock_store)
        assert isinstance(result, dict)
        assert "policy_map" in result
