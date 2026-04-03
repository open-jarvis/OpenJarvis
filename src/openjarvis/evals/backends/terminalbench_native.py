"""Native terminal-bench backend.

Each call to generate_full() runs a single terminal-bench task through the
official Harness (Docker + terminus-2 agent + test scripts), then stores
is_resolved in the record metadata for the scorer to read.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from openjarvis.evals.core.backend import InferenceBackend

LOGGER = logging.getLogger(__name__)

try:
    from terminal_bench import BenchmarkResults, Harness
    from terminal_bench.agents.agent_name import AgentName

    _HAS_TB = True
except ImportError:
    _HAS_TB = False

# LiteLLM model prefix and api_base by engine type.
_ENGINE_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "vllm": {"prefix": "openai/", "api_base": "http://localhost:8000/v1"},
    "ollama": {"prefix": "openai/", "api_base": "http://localhost:11434/v1"},
    "cloud": {"prefix": "", "api_base": None},
}


def _litellm_model(model: str, engine_key: str) -> tuple[str, Optional[str]]:
    """Return (litellm_model_string, api_base) for the given engine."""
    cfg = _ENGINE_DEFAULTS.get(engine_key, _ENGINE_DEFAULTS["cloud"])
    return cfg["prefix"] + model, cfg["api_base"]


def _run_id(task_id: str) -> str:
    """Docker-safe run_id from task_id (lowercase alphanumeric + hyphens)."""
    return re.sub(r"[^a-z0-9-]", "-", f"oj-{task_id}".lower())[:60]


class TerminalBenchNativeBackend(InferenceBackend):
    """Runs terminal-bench tasks natively via Harness with Docker execution.

    generate_full() runs one task per call through the terminal-bench Harness
    (terminus-2 agent + Docker containers + test scripts), writing is_resolved
    into the record metadata so TerminalBenchNativeScorer can read it.

    EvalRunner must call set_current_record(record) immediately before each
    generate_full() call so the backend knows which task directory to target.
    """

    backend_id = "terminalbench-native"

    def __init__(
        self,
        model: str = "claude-3-5-haiku-20241022",
        engine_key: str = "cloud",
        output_dir: str = "results/terminalbench-native/",
        temperature: float = 0.6,
        dataset_name: str = "terminal-bench-core",
        dataset_version: str = "0.1.1",
        max_samples: Optional[int] = None,
        n_concurrent: int = 4,
    ) -> None:
        if not _HAS_TB:
            raise ImportError("terminal-bench is required: pip install terminal-bench")

        self._litellm_model, self._api_base = _litellm_model(model, engine_key)
        self._temperature = temperature
        self._output_dir = Path(output_dir)
        self._dataset_name = dataset_name
        self._dataset_version = dataset_version
        self._max_samples = max_samples
        self._n_concurrent = n_concurrent
        self._current_record: Any = None

    # ------------------------------------------------------------------
    # Pipeline integration
    # ------------------------------------------------------------------

    def set_current_record(self, record: Any) -> None:
        """Called by EvalRunner before each generate_full() to identify the task."""
        self._current_record = record

    def generate_full(
        self,
        prompt: str,
        *,
        model: str = "",
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Run a single terminal-bench task through the official Harness.

        Requires set_current_record() to have been called first so we know
        the task directory. Stores is_resolved + test_results in the record
        metadata for the scorer.
        """
        if self._current_record is None:
            LOGGER.warning("set_current_record() not called; returning empty result.")
            return {"content": "", "usage": {}, "latency_seconds": 0.0}

        task_dir = Path(self._current_record.metadata["task_dir"])
        task_id = task_dir.name

        # Use caller-supplied temperature if non-zero, else fall back to default.
        effective_temp = temperature if temperature else self._temperature
        # Use caller-supplied model if provided and non-empty.
        effective_model = model or self._litellm_model

        output_path = self._output_dir / "trials"
        output_path.mkdir(parents=True, exist_ok=True)

        harness = Harness(
            output_path=output_path,
            run_id=_run_id(task_id),
            dataset_path=task_dir.parent,
            task_ids=[task_id],
            model_name=effective_model,
            agent_name=AgentName("terminus-2"),
            agent_kwargs={
                "model_name": effective_model,
                "api_base": self._api_base,
                "temperature": effective_temp,
            },
            n_concurrent_trials=1,
            n_attempts=1,
            cleanup=True,
        )

        t0 = time.monotonic()
        results = harness.run()
        latency = time.monotonic() - t0

        trial = results.results[0] if results.results else None
        is_resolved = bool(trial.is_resolved) if trial else False

        # Write into record metadata so TerminalBenchNativeScorer can read it.
        self._current_record.metadata["is_resolved"] = is_resolved
        self._current_record.metadata["test_results"] = {
            "parser_results": (
                {k: v.value for k, v in (trial.parser_results or {}).items()}
                if trial else {}
            ),
            "failure_mode": (
                trial.failure_mode.value
                if trial and trial.failure_mode else None
            ),
        }

        return {
            "content": "",
            "usage": {
                "prompt_tokens": (trial.total_input_tokens or 0) if trial else 0,
                "completion_tokens": (trial.total_output_tokens or 0) if trial else 0,
            },
            "latency_seconds": latency,
            "cost_usd": 0.0,
        }

    def generate(self, prompt: str, **kwargs: Any) -> str:
        return self.generate_full(prompt, **kwargs).get("content", "")

    # ------------------------------------------------------------------
    # Bulk / legacy path
    # ------------------------------------------------------------------

    def run_harness(self, run_id: str) -> "BenchmarkResults":
        """Run the full dataset through the Harness in one shot (legacy/bulk)."""
        output_path = self._output_dir / run_id
        output_path.mkdir(parents=True, exist_ok=True)

        harness = Harness(
            output_path=output_path,
            run_id=run_id,
            dataset_name=self._dataset_name,
            dataset_version=self._dataset_version,
            model_name=self._litellm_model,
            agent_name=AgentName("terminus-2"),
            agent_kwargs={
                "model_name": self._litellm_model,
                "api_base": self._api_base,
                "temperature": self._temperature,
            },
            n_concurrent_trials=self._n_concurrent,
            n_tasks=self._max_samples,
            cleanup=True,
        )
        return harness.run()

    def close(self) -> None:
        pass


__all__ = ["TerminalBenchNativeBackend"]
