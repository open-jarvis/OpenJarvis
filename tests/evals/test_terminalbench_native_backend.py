"""Tests for the TerminalBench native backend (mocked terminal_bench).

Covers: timeout kwargs threading (config -> backend -> Harness kwargs),
loud failure on terminal-bench builds without the timeout kwargs, and the
harness-error classification in ``summarize_benchmark_results`` —
including the zero-model-contact vs genuine-model-miss distinction.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

import openjarvis.evals.backends.terminalbench_native as tbn
from openjarvis.evals.backends.terminalbench_native import (
    summarize_benchmark_results,
)

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def make_trial(
    task_id: str,
    *,
    is_resolved: bool,
    failure_mode: str = "unset",
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
) -> SimpleNamespace:
    """Build a duck-typed terminal-bench 0.2.18 TrialResults."""
    return SimpleNamespace(
        task_id=task_id,
        trial_name=f"{task_id}.1-of-1",
        is_resolved=is_resolved,
        failure_mode=SimpleNamespace(value=failure_mode),
        total_input_tokens=input_tokens,
        total_output_tokens=output_tokens,
    )


class FakeHarness:
    """Records constructor kwargs; run() returns the configured results."""

    captured_kwargs: Dict[str, Any] = {}
    results: Any = SimpleNamespace(results=[])

    def __init__(self, **kwargs: Any) -> None:
        type(self).captured_kwargs = kwargs

    def run(self) -> Any:
        return type(self).results


class OldFakeHarness:
    """A pre-timeout-kwargs Harness signature (no **kwargs)."""

    def __init__(
        self,
        output_path: Any = None,
        run_id: Any = None,
        dataset_name: Any = None,
        dataset_version: Any = None,
        model_name: Any = None,
        n_concurrent_trials: Any = None,
        cleanup: Any = None,
        agent_name: Any = None,
        agent_kwargs: Any = None,
        n_tasks: Any = None,
    ) -> None:
        pass

    def run(self) -> Any:
        return SimpleNamespace(results=[])


@pytest.fixture()
def fake_tb_backend(monkeypatch):
    """Enable the backend without the real terminal_bench package."""
    FakeHarness.captured_kwargs = {}
    FakeHarness.results = SimpleNamespace(results=[])
    monkeypatch.setattr(tbn, "_HAS_TB", True)
    monkeypatch.setattr(tbn, "Harness", FakeHarness, raising=False)

    mod_tb = types.ModuleType("terminal_bench")
    mod_agents = types.ModuleType("terminal_bench.agents")
    mod_agent_name = types.ModuleType("terminal_bench.agents.agent_name")
    mod_agent_name.AgentName = lambda name: name
    mod_tb.agents = mod_agents
    mod_agents.agent_name = mod_agent_name
    monkeypatch.setitem(sys.modules, "terminal_bench", mod_tb)
    monkeypatch.setitem(sys.modules, "terminal_bench.agents", mod_agents)
    monkeypatch.setitem(sys.modules, "terminal_bench.agents.agent_name", mod_agent_name)
    return FakeHarness


# ---------------------------------------------------------------------------
# Timeout kwargs threading
# ---------------------------------------------------------------------------


class TestTimeoutKwargs:
    def test_default_bound_reaches_harness(self, fake_tb_backend, tmp_path):
        backend = tbn.TerminalBenchNativeBackend(output_dir=str(tmp_path))
        backend.run_harness("run-1")
        kwargs = fake_tb_backend.captured_kwargs
        assert kwargs["global_agent_timeout_sec"] == 1800.0
        assert "global_timeout_multiplier" not in kwargs

    def test_explicit_values_reach_harness(self, fake_tb_backend, tmp_path):
        backend = tbn.TerminalBenchNativeBackend(
            output_dir=str(tmp_path),
            global_agent_timeout_sec=1234.0,
            global_timeout_multiplier=2.0,
        )
        backend.run_harness("run-1")
        kwargs = fake_tb_backend.captured_kwargs
        assert kwargs["global_agent_timeout_sec"] == 1234.0
        assert kwargs["global_timeout_multiplier"] == 2.0

    def test_zero_disables_bound(self, fake_tb_backend, tmp_path):
        backend = tbn.TerminalBenchNativeBackend(
            output_dir=str(tmp_path), global_agent_timeout_sec=0
        )
        backend.run_harness("run-1")
        assert "global_agent_timeout_sec" not in fake_tb_backend.captured_kwargs

    def test_old_terminal_bench_fails_loud(
        self, fake_tb_backend, monkeypatch, tmp_path
    ):
        """An old Harness without the kwargs must not hang silently."""
        monkeypatch.setattr(tbn, "Harness", OldFakeHarness, raising=False)
        backend = tbn.TerminalBenchNativeBackend(output_dir=str(tmp_path))
        with pytest.raises(RuntimeError, match="global_agent_timeout_sec"):
            backend.run_harness("run-1")


# ---------------------------------------------------------------------------
# Harness-error classification (zero-model-contact detection)
# ---------------------------------------------------------------------------


class TestSummarizeBenchmarkResults:
    def test_genuine_model_miss_is_not_flagged(self):
        """MANDATORY: a real miss (tokens>0, failure_mode unset) stays a miss.

        terminal-bench 0.2.18 leaves failure_mode UNSET on success and on
        genuine unresolved misses — classifying on failure_mode would flag
        every real miss as a harness error and inflate accuracy.
        """
        results = SimpleNamespace(
            results=[
                make_trial(
                    "t-ok", is_resolved=True, input_tokens=900, output_tokens=100
                ),
                make_trial(
                    "t-miss", is_resolved=False, input_tokens=800, output_tokens=50
                ),
                make_trial(
                    "t-setup-dead",
                    is_resolved=False,
                    failure_mode="agent_installation_failed",
                    input_tokens=0,
                    output_tokens=0,
                ),
            ]
        )
        summary, failures = summarize_benchmark_results(results, model="m")
        assert summary.total_samples == 3
        assert summary.scored_samples == 2  # genuine miss stays in denominator
        assert summary.correct == 1
        assert summary.accuracy == 0.5  # not 1.0 (miss kept), not 1/3 (infra out)
        assert summary.errors == 1
        assert [f["task_id"] for f in failures] == ["t-setup-dead"]
        assert failures[0]["reason"] == "zero_model_requests"

    def test_zero_contact_flagged_even_with_unset_failure_mode(self):
        """Setup hang signature: unresolved, zero requests, failure_mode unset."""
        results = SimpleNamespace(
            results=[
                make_trial("t-hang", is_resolved=False, input_tokens=0),
            ]
        )
        summary, failures = summarize_benchmark_results(results, model="m")
        assert summary.errors == 1
        assert summary.scored_samples == 0
        assert failures[0]["reason"] == "zero_model_requests"

    def test_missing_token_fields_treated_as_zero_contact(self):
        results = SimpleNamespace(results=[make_trial("t-none", is_resolved=False)])
        summary, failures = summarize_benchmark_results(results, model="m")
        assert summary.errors == 1

    def test_infra_failure_mode_flagged_despite_tokens(self):
        results = SimpleNamespace(
            results=[
                make_trial(
                    "t-crash",
                    is_resolved=False,
                    failure_mode="unknown_agent_error",
                    input_tokens=500,
                    output_tokens=20,
                ),
            ]
        )
        summary, failures = summarize_benchmark_results(results, model="m")
        assert summary.errors == 1
        assert failures[0]["reason"] == "unknown_agent_error"

    def test_resolved_with_zero_tokens_not_flagged(self):
        """Installed agents report 0 tokens on success — never flag resolved."""
        results = SimpleNamespace(
            results=[
                make_trial("t-ok", is_resolved=True, input_tokens=0, output_tokens=0),
            ]
        )
        summary, failures = summarize_benchmark_results(results, model="m")
        assert summary.errors == 0
        assert summary.correct == 1
        assert summary.accuracy == 1.0

    def test_empty_results(self):
        summary, failures = summarize_benchmark_results(
            SimpleNamespace(results=[]), model="m"
        )
        assert summary.total_samples == 0
        assert summary.accuracy == 0.0
        assert failures == []


# ---------------------------------------------------------------------------
# CLI wiring: config -> backend -> harness kwargs -> RunSummary
# ---------------------------------------------------------------------------


class TestRunTerminalbenchNativeWiring:
    def _run(self, fake_tb_backend, tmp_path, trials: List[Any], **config_kwargs):
        from rich.console import Console

        from openjarvis.evals.cli import _run_terminalbench_native
        from openjarvis.evals.core.types import RunConfig

        fake_tb_backend.results = SimpleNamespace(results=trials)
        config = RunConfig(
            benchmark="terminalbench-native",
            backend="terminalbench-native",
            model="test-model",
            output_path=str(tmp_path / "out"),
            **config_kwargs,
        )
        console = Console(record=True, width=120)
        summary = _run_terminalbench_native(config, console)
        return summary, console.export_text()

    def test_config_timeouts_reach_harness_kwargs(self, fake_tb_backend, tmp_path):
        """(d) timeout kwargs travel config -> backend -> harness_kwargs."""
        self._run(
            fake_tb_backend,
            tmp_path,
            [],
            global_agent_timeout_sec=901.0,
            global_timeout_multiplier=1.5,
        )
        kwargs = fake_tb_backend.captured_kwargs
        assert kwargs["global_agent_timeout_sec"] == 901.0
        assert kwargs["global_timeout_multiplier"] == 1.5

    def test_config_defaults_use_backend_bound(self, fake_tb_backend, tmp_path):
        self._run(fake_tb_backend, tmp_path, [])
        assert fake_tb_backend.captured_kwargs["global_agent_timeout_sec"] == 1800.0

    def test_summary_counts_real_trials(self, fake_tb_backend, tmp_path):
        """Regression: results field is ``results``, not ``trial_results``.

        The old conversion read the nonexistent ``trial_results`` attribute
        and hardcoded errors=0, rendering every run as 0 samples / 0.0.
        """
        trials = [
            make_trial("t-ok", is_resolved=True, input_tokens=10, output_tokens=10),
            make_trial("t-miss", is_resolved=False, input_tokens=10, output_tokens=2),
            make_trial(
                "t-hang",
                is_resolved=False,
                failure_mode="agent_timeout",
                input_tokens=0,
                output_tokens=0,
            ),
        ]
        summary, output = self._run(fake_tb_backend, tmp_path, trials)
        assert summary.total_samples == 3
        assert summary.scored_samples == 2
        assert summary.correct == 1
        assert summary.accuracy == 0.5
        assert summary.errors == 1
        # The harness failure is reported loudly with its task id.
        assert "t-hang" in output
        assert "zero_model_requests" in output
