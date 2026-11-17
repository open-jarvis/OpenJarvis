"""Tests for the DSPy agent optimizer (mocked -- no dspy dependency required)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
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
    def test_missing_safe_cache_controls_fail_before_model_use(self, monkeypatch):
        import openjarvis.learning.agents.dspy_optimizer as mod
        from openjarvis.core.config import DSPyOptimizerConfig

        model = MagicMock()
        monkeypatch.setattr(mod, "HAS_DSPY", True)
        monkeypatch.setattr(mod, "dspy", SimpleNamespace(ChainOfThought=model))
        store = SimpleNamespace(list_traces=lambda **kwargs: [SimpleNamespace()])
        optimizer = mod.DSPyAgentOptimizer(DSPyOptimizerConfig(min_traces=1))

        result = optimizer.optimize(store)

        assert result["status"] == "error"
        model.assert_not_called()

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

    def test_extracts_demos_from_compiled_chain_of_thought(self, monkeypatch) -> None:
        """DSPy stores compiled ChainOfThought demos on its inner predictor."""
        import openjarvis.learning.agents.dspy_optimizer as mod
        from openjarvis.core.config import DSPyOptimizerConfig

        class FakeExample:
            def __init__(self, *, question: str, answer: str) -> None:
                fake_dspy.configure_cache.assert_called_once_with(
                    enable_disk_cache=False,
                    enable_memory_cache=True,
                    restrict_pickle=True,
                )
                self.question = question
                self.answer = answer

            def with_inputs(self, *names: str):
                assert names == ("question",)
                return self

        class FakeModule:
            pass

        class FakeChainOfThought:
            def __init__(self, signature: str) -> None:
                assert signature == "question -> answer"

        class FakeBootstrapFewShot:
            def __init__(self, **kwargs) -> None:
                pass

            def compile(self, program, *, trainset):
                assert isinstance(program.generate, FakeChainOfThought)
                assert trainset[0].question == "How are you?"
                demos = [FakeExample(question="How are you?", answer="Well")]
                return SimpleNamespace(
                    generate=SimpleNamespace(predict=SimpleNamespace(demos=demos))
                )

        fake_dspy = SimpleNamespace(
            Example=FakeExample,
            Module=FakeModule,
            ChainOfThought=FakeChainOfThought,
            BootstrapFewShot=FakeBootstrapFewShot,
            configure_cache=MagicMock(),
        )
        monkeypatch.setattr(mod, "dspy", fake_dspy)
        monkeypatch.setattr(mod, "HAS_DSPY", True)

        optimizer = mod.DSPyAgentOptimizer(
            DSPyOptimizerConfig(optimizer="BootstrapFewShot", min_traces=1)
        )
        trace = SimpleNamespace(query="How are you?", result="Well", feedback=1.0)
        store = SimpleNamespace(list_traces=lambda **kwargs: [trace])

        result = optimizer.optimize(store)

        assert result["status"] == "completed"
        fake_dspy.configure_cache.assert_called_once_with(
            enable_disk_cache=False,
            enable_memory_cache=True,
            restrict_pickle=True,
        )
        assert result["config_updates"]["few_shot_examples"] == [
            {"input": "How are you?", "output": "Well"}
        ]


def test_importing_optimizer_does_not_load_optional_sdk(tmp_path):
    (tmp_path / "dspy.py").write_text(
        "raise AssertionError('SDK imported at startup')\n"
    )
    source = Path(__file__).resolve().parents[3] / "src"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "from openjarvis.learning.agents import dspy_optimizer as m; "
            "assert m.HAS_DSPY; assert 'dspy' not in sys.modules",
        ],
        env={**os.environ, "PYTHONPATH": str(tmp_path) + os.pathsep + str(source)},
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
