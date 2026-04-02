"""Native terminal-bench v2 backend.

Uses Harness for Docker-based execution and scoring.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from openjarvis.evals.core.backend import InferenceBackend

LOGGER = logging.getLogger(__name__)

try:
    from terminal_bench import BenchmarkResults, Harness

    _HAS_TB = True
except ImportError:
    _HAS_TB = False


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
    ) -> None:
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

        harness = Harness(**harness_kwargs)
        self._results = harness.run()
        return self._results

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


__all__ = ["TerminalBenchNativeBackend"]
