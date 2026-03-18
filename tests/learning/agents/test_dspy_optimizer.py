"""Tests for the DSPy agent optimizer (mocked -- no dspy dependency required)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch


class TestDSPyOptimizerConfig:
    def test_default_config(self) -> None:
        from openjarvis.core.config import DSPyOptimizerConfig

        cfg = DSPyOptimizerConfig()
        assert cfg.optimizer == "BootstrapFewShotWithRandomSearch"
        assert cfg.max_bootstrapped_demos == 4
        assert cfg.min_traces == 20

    def test_optimizer_init(self) -> None:
        from openjarvis.core.config import DSPyOptimizerConfig
        from openjarvis.learning.agents.dspy_optimizer import DSPyAgentOptimizer

        cfg = DSPyOptimizerConfig()
        optimizer = DSPyAgentOptimizer(cfg)
        assert optimizer.config is cfg


class TestDSPyOptimizerTraceConversion:
    def test_too_few_traces_skipped(self) -> None:
        from openjarvis.core.config import DSPyOptimizerConfig
        from openjarvis.learning.agents.dspy_optimizer import DSPyAgentOptimizer

        optimizer = DSPyAgentOptimizer(DSPyOptimizerConfig(min_traces=10))
        mock_store = MagicMock()
        mock_store.list_traces.return_value = []

        result = optimizer.optimize(mock_store)
        assert result["status"] == "skipped"

    def test_optimize_returns_toml_updates(self) -> None:
        from openjarvis.core.config import DSPyOptimizerConfig
        from openjarvis.core.types import StepType, Trace, TraceStep
        from openjarvis.learning.agents.dspy_optimizer import DSPyAgentOptimizer

        cfg = DSPyOptimizerConfig(min_traces=1)
        optimizer = DSPyAgentOptimizer(cfg)

        # Create mock traces
        now = time.time()
        traces = []
        for i in range(5):
            traces.append(
                Trace(
                    query=f"test query {i}",
                    agent="native_react",
                    model="qwen3:8b",
                    result=f"result {i}",
                    outcome="success",
                    feedback=0.9,
                    started_at=now,
                    ended_at=now + 1,
                    total_tokens=100,
                    total_latency_seconds=1.0,
                    steps=[
                        TraceStep(
                            step_type=StepType.GENERATE,
                            timestamp=now,
                            duration_seconds=0.5,
                        )
                    ],
                )
            )

        mock_store = MagicMock()
        mock_store.list_traces.return_value = traces

        # Mock dspy so the test works without the dependency
        import openjarvis.learning.agents.dspy_optimizer as mod

        with patch.object(mod, "HAS_DSPY", True):
            with patch.object(
                optimizer,
                "_run_dspy_optimization",
                return_value={
                    "system_prompt": "You are a helpful assistant.",
                    "few_shot_examples": [{"input": "hi", "output": "hello"}],
                },
            ):
                result = optimizer.optimize(mock_store)
                assert result["status"] == "completed"
                assert "config_updates" in result
