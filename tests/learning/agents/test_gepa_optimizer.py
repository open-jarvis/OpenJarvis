"""Tests for the GEPA agent optimizer (mocked -- no gepa dependency required)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch


class TestGEPAOptimizerConfig:
    def test_default_config(self) -> None:
        from openjarvis.core.config import GEPAOptimizerConfig

        cfg = GEPAOptimizerConfig()
        assert cfg.max_metric_calls == 150
        assert cfg.population_size == 10
        assert cfg.min_traces == 20

    def test_optimizer_init(self) -> None:
        from openjarvis.core.config import GEPAOptimizerConfig
        from openjarvis.learning.agents.gepa_optimizer import GEPAAgentOptimizer

        cfg = GEPAOptimizerConfig()
        optimizer = GEPAAgentOptimizer(cfg)
        assert optimizer.config is cfg


class TestGEPAOptimizerOptimize:
    def test_too_few_traces_skipped(self) -> None:
        from openjarvis.core.config import GEPAOptimizerConfig
        from openjarvis.learning.agents.gepa_optimizer import GEPAAgentOptimizer

        optimizer = GEPAAgentOptimizer(GEPAOptimizerConfig(min_traces=10))
        mock_store = MagicMock()
        mock_store.list_traces.return_value = []

        result = optimizer.optimize(mock_store)
        assert result["status"] == "skipped"

    def test_no_gepa_reports_error(self) -> None:
        from openjarvis.core.config import GEPAOptimizerConfig
        from openjarvis.core.types import StepType, Trace, TraceStep
        from openjarvis.learning.agents.gepa_optimizer import GEPAAgentOptimizer

        cfg = GEPAOptimizerConfig(min_traces=1)
        optimizer = GEPAAgentOptimizer(cfg)

        now = time.time()
        traces = [
            Trace(
                query="test",
                agent="native_react",
                model="qwen3:8b",
                result="result",
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
        ]

        mock_store = MagicMock()
        mock_store.list_traces.return_value = traces

        # Ensure gepa is not available
        with patch.dict("sys.modules", {"gepa": None}):
            with patch(
                "openjarvis.learning.agents.gepa_optimizer.HAS_GEPA",
                False,
            ):
                result = optimizer.optimize(mock_store)
                assert result["status"] == "error"
                assert "gepa" in result["reason"].lower()


class TestOpenJarvisGEPAAdapter:
    def test_adapter_init(self) -> None:
        from openjarvis.core.config import GEPAOptimizerConfig
        from openjarvis.learning.agents.gepa_optimizer import (
            OpenJarvisGEPAAdapter,
        )

        mock_store = MagicMock()
        adapter = OpenJarvisGEPAAdapter(
            mock_store,
            "native_react",
            GEPAOptimizerConfig(),
        )
        assert adapter.agent_name == "native_react"
