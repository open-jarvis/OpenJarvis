"""Native TerminalBench V2.1 backend.

Uses Harness for Docker-based execution and scoring.
"""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.backend import InferenceBackend
from openjarvis.evals.core.types import RunSummary

LOGGER = logging.getLogger(__name__)

try:
    from terminal_bench import BenchmarkResults, Harness

    _HAS_TB = True
except ImportError:
    _HAS_TB = False

# terminal-bench FailureMode values that are definitionally infrastructure
# failures (the harness broke before/while driving the agent), never a
# judgment on the model's answer. NOTE: clean trials leave failure_mode
# "unset" in terminal-bench 0.2.18 — both on success AND on genuine
# unresolved misses — so failure_mode alone can NOT be used to detect
# harness errors (it would misflag every real model miss).
_INFRA_FAILURE_MODES = frozenset({"agent_installation_failed", "unknown_agent_error"})

# Harness kwargs that older terminal-bench versions may not support.
_TIMEOUT_KWARGS = ("global_agent_timeout_sec", "global_timeout_multiplier")


def summarize_benchmark_results(
    results: Any,
    *,
    model: str,
    benchmark: str = "terminalbench-native",
) -> Tuple[RunSummary, List[Dict[str, str]]]:
    """Convert terminal-bench ``BenchmarkResults`` into a ``RunSummary``.

    Trials are classified into three buckets:

    - resolved: ``is_resolved`` is True -> counted correct.
    - model miss: unresolved, but the model was actually contacted ->
      counted in the accuracy denominator.
    - harness/infra failure: excluded from the accuracy denominator and
      reported in ``RunSummary.errors`` plus the returned failure list.

    Zero-model-contact signal choice: terminal-bench 0.2.18 leaves
    ``failure_mode`` UNSET both on clean success and on genuine unresolved
    misses, so failure_mode cannot distinguish "the model tried and failed"
    from "the agent never called the model". Token usage can: this backend
    always runs terminus-2, which reports real LiteLLM usage, so an
    unresolved trial with zero/missing input+output tokens means no model
    request ever completed — an infrastructure failure (in-container setup
    hang/death, tmux failure), not a model miss. CAVEAT: terminal-bench
    "installed agents" (openhands, claude-code, ...) hardcode 0 tokens even
    on success; if this backend ever honors ``agent_name`` for installed
    agents, this heuristic must be gated on the agent type.
    """
    trials = list(getattr(results, "results", None) or [])

    harness_failures: List[Dict[str, str]] = []
    scored = 0
    correct = 0

    for tr in trials:
        task_id = getattr(tr, "task_id", None) or getattr(tr, "trial_name", "unknown")
        is_resolved = getattr(tr, "is_resolved", None) is True
        fm = getattr(tr, "failure_mode", None)
        fm_value = str(getattr(fm, "value", fm) or "unset").lower()
        tokens = (getattr(tr, "total_input_tokens", None) or 0) + (
            getattr(tr, "total_output_tokens", None) or 0
        )

        zero_model_contact = not is_resolved and tokens == 0
        infra_failure_mode = fm_value in _INFRA_FAILURE_MODES

        if zero_model_contact or infra_failure_mode:
            harness_failures.append(
                {
                    "task_id": str(task_id),
                    "failure_mode": fm_value,
                    "reason": (
                        "zero_model_requests" if zero_model_contact else fm_value
                    ),
                }
            )
            continue

        scored += 1
        if is_resolved:
            correct += 1

    return (
        RunSummary(
            benchmark=benchmark,
            category="agentic",
            backend="terminalbench-native",
            model=model,
            total_samples=len(trials),
            scored_samples=scored,
            correct=correct,
            accuracy=correct / scored if scored else 0.0,
            errors=len(harness_failures),
            mean_latency_seconds=0.0,
            total_cost_usd=0.0,
        ),
        harness_failures,
    )


class TerminalBenchNativeBackend(InferenceBackend):
    """Runs terminal-bench tasks natively via Harness with Docker execution.

    Uses terminal-bench's own agent + LiteLLM to call the model,
    Docker containers for task execution, and built-in test scripts
    for scoring. This gives real agentic evaluation, not text-only.
    """

    backend_id = "terminalbench-native"

    def __init__(
        self,
        model: str = "openai/default",
        api_base: str = "http://localhost:8000/v1",
        temperature: float = 0.2,
        agent_name: str = "naive",
        output_dir: str = "results/terminalbench/",
        max_samples: Optional[int] = None,
        dataset_name: str = "terminal-bench-core",
        dataset_version: str = "0.1.1",
        system_prompt: str = "",
        max_tokens: int = 16384,
        n_concurrent: int = 4,
        global_agent_timeout_sec: Optional[float] = 1800.0,
        global_timeout_multiplier: Optional[float] = None,
    ) -> None:
        """Args of note:

        global_agent_timeout_sec: Hard wall-clock bound for each trial's
            agent phase. terminal-bench runs installed-agent SETUP inside
            this same budget with an infinite tmux timeout, so this bounds
            SETUP+RUN together (a setup-only timeout needs an upstream
            terminal-bench change). When set, it REPLACES each task's own
            ``max_agent_timeout_sec``. Set ``None`` or ``0`` to fall back
            to per-task budgets.
        global_timeout_multiplier: Scales per-task budgets when
            ``global_agent_timeout_sec`` is not set. ``None`` keeps
            terminal-bench's default (1.0).
        """
        if not _HAS_TB:
            raise ImportError("terminal-bench is required: pip install terminal-bench")

        self._model = model
        self._api_base = api_base
        self._temperature = temperature
        self._agent_name = agent_name
        self._output_dir = Path(output_dir)
        self._max_samples = max_samples
        self._dataset_name = dataset_name
        self._dataset_version = dataset_version
        self._system_prompt = system_prompt
        self._max_tokens = max_tokens
        self._n_concurrent = n_concurrent
        self._global_agent_timeout_sec = global_agent_timeout_sec
        self._global_timeout_multiplier = global_timeout_multiplier
        self._results: Optional[BenchmarkResults] = None

    def run_harness(self, run_id: str) -> BenchmarkResults:
        """Run the full terminal-bench harness and return results."""
        output_path = self._output_dir / run_id
        output_path.mkdir(parents=True, exist_ok=True)

        harness_kwargs: Dict[str, Any] = {
            "output_path": output_path,
            "run_id": run_id,
            "dataset_name": self._dataset_name,
            "dataset_version": self._dataset_version,
            "model_name": self._model,
            "n_concurrent_trials": self._n_concurrent,
            "cleanup": True,
        }

        # Use terminus-2 agent which accepts model_name + api_base as
        # serializable strings (avoids Pydantic serialization issues with
        # LLM objects in the harness lock file).
        from terminal_bench.agents.agent_name import AgentName

        harness_kwargs["agent_name"] = AgentName("terminus-2")
        harness_kwargs["agent_kwargs"] = {
            "model_name": self._model,
            "api_base": self._api_base,
            "temperature": self._temperature,
        }

        if self._max_samples is not None:
            harness_kwargs["n_tasks"] = self._max_samples

        # Bound each trial's agent phase. Without this, an in-container
        # installed-agent SETUP hang runs with an infinite tmux timeout,
        # bounded only by whatever budget the task happens to declare.
        if self._global_agent_timeout_sec:
            harness_kwargs["global_agent_timeout_sec"] = float(
                self._global_agent_timeout_sec
            )
        if self._global_timeout_multiplier is not None:
            harness_kwargs["global_timeout_multiplier"] = float(
                self._global_timeout_multiplier
            )

        self._check_timeout_kwargs_supported(harness_kwargs)

        harness = Harness(**harness_kwargs)
        self._results = harness.run()
        return self._results

    @staticmethod
    def _check_timeout_kwargs_supported(harness_kwargs: Dict[str, Any]) -> None:
        """Fail loudly if this terminal-bench build lacks the timeout kwargs.

        terminal-bench is an undeclared, unpinned dependency, so installs may
        predate the global timeout kwargs (added by 0.2.x). Passing an
        unknown kwarg raises an opaque TypeError; dropping it silently would
        re-create the unbounded-setup hang. Detect and explain instead.
        """
        try:
            params = inspect.signature(Harness.__init__).parameters
        except (TypeError, ValueError):
            return
        if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return
        unsupported = [
            key
            for key in _TIMEOUT_KWARGS
            if key in harness_kwargs and key not in params
        ]
        if unsupported:
            raise RuntimeError(
                "The installed terminal-bench does not support "
                f"{', '.join(unsupported)} (requires terminal-bench >= "
                "0.2.18). Upgrade terminal-bench, or disable the bound by "
                "setting global_agent_timeout_sec = 0 in the eval config "
                "[run] section."
            )

    def generate(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        return ""

    def generate_full(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        return {"content": "", "usage": {}, "model": model, "latency_seconds": 0.0}

    def close(self) -> None:
        pass


__all__ = ["TerminalBenchNativeBackend", "summarize_benchmark_results"]
