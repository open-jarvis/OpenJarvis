"""Live evaluator for GEPA/DSPy agent optimization.

Instantiates the OpenJarvis agent with a candidate config dict, runs it
on benchmark tasks, and scores output via LLM judge. Returns accuracy.

The backend is rebuilt only when construction-time params change
(agent_type, tools, max_turns). Per-call params (system_prompt,
temperature, max_tokens) are passed directly to generate_full().

Usage:
    from scripts.optimization.evaluator import LiveEvaluator

    evaluator = LiveEvaluator(
        model="Qwen/Qwen3.5-9B",
        benchmark="pinchbench",
        engine_key="vllm",
        max_samples=15,
    )

    score = evaluator.evaluate(candidate_config_dict)
    evaluator.close()
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _construction_key(candidate: Dict[str, Any]) -> str:
    """Hash the construction-time params to detect when backend must rebuild."""
    parts = [
        str(candidate.get("agent_type", "monitor_operative")),
        str(candidate.get("tool_set", "")),
        str(candidate.get("max_turns", "25")),
        str(candidate.get("skills_enabled", "true")),
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:12]


class LiveEvaluator:
    """Evaluates candidate configs by running the agent on benchmark tasks.

    Parameters
    ----------
    model:
        Model identifier (e.g. "Qwen/Qwen3.5-9B"). Held fixed.
    benchmark:
        Benchmark name (e.g. "pinchbench", "toolcall15", "taubench").
    engine_key:
        Engine backend (e.g. "vllm", "cloud", "ollama").
    max_samples:
        Max tasks per evaluation call. Lower = faster but noisier.
    judge_model:
        LLM judge for scoring. Default: gpt-5-mini.
    seed:
        Random seed for task sampling.
    output_dir:
        Directory for per-eval JSONL output files.
    """

    def __init__(
        self,
        model: str,
        benchmark: str,
        engine_key: str = "vllm",
        max_samples: int = 15,
        judge_model: str = "gpt-5-mini-2025-08-07",
        seed: int = 42,
        output_dir: str = "/tmp/optimization_evals",
    ) -> None:
        self.model = model
        self.benchmark = benchmark
        self.engine_key = engine_key
        self.max_samples = max_samples
        self.judge_model = judge_model
        self.seed = seed
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Lazy-loaded components
        self._dataset = None
        self._scorer = None
        self._judge_backend = None
        self._backend = None
        self._backend_key: Optional[str] = None
        self._eval_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, candidate: Dict[str, Any]) -> float:
        """Run agent with candidate config, return accuracy (0.0-1.0).

        The candidate dict should contain keys matching the seed_candidate
        schema from the experiment plan (system_prompt, temperature, etc.).
        """
        self._eval_count += 1
        t0 = time.monotonic()

        # Ensure shared components are built
        self._ensure_dataset()
        self._ensure_judge()

        # Rebuild backend if construction-time params changed
        key = _construction_key(candidate)
        if key != self._backend_key:
            self._rebuild_backend(candidate)
            self._backend_key = key

        # Extract per-call params
        system_prompt = str(candidate.get("system_prompt", ""))
        temperature = float(candidate.get("temperature", 0.3))
        max_tokens = int(candidate.get("max_tokens", 4096))

        # Run eval — load() populates internal state, iter_records() yields them
        self._dataset.load(
            max_samples=self.max_samples,
            seed=self.seed,
        )
        records = list(self._dataset.iter_records())

        correct = 0
        scored = 0
        errors = 0

        for record in records:
            try:
                result = self._backend.generate_full(
                    prompt=record.problem,
                    model=self.model,
                    system=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = result.get("content", "")
                is_correct, _ = self._scorer.score(record, content)

                if is_correct is not None:
                    scored += 1
                    if is_correct:
                        correct += 1
            except Exception as exc:
                logger.warning(
                    "Eval %d: Error on %s: %s",
                    self._eval_count, record.record_id, exc,
                )
                errors += 1

        accuracy = correct / scored if scored > 0 else 0.0
        elapsed = time.monotonic() - t0

        logger.info(
            "Eval %d: %d/%d correct (%.1f%%), %d errors, %.1fs",
            self._eval_count, correct, scored, accuracy * 100, errors, elapsed,
        )

        return accuracy

    def evaluate_single(
        self, candidate: Dict[str, Any], query: str,
    ) -> float:
        """Evaluate candidate on a single query. Returns 0.0 or 1.0.

        Useful for GEPA's per-example evaluator interface.
        """
        self._ensure_dataset()
        self._ensure_judge()

        key = _construction_key(candidate)
        if key != self._backend_key:
            self._rebuild_backend(candidate)
            self._backend_key = key

        system_prompt = str(candidate.get("system_prompt", ""))
        temperature = float(candidate.get("temperature", 0.3))
        max_tokens = int(candidate.get("max_tokens", 4096))

        # Find matching record from dataset
        self._dataset.load(max_samples=self.max_samples, seed=self.seed)
        records = list(self._dataset.iter_records())
        record = None
        for r in records:
            if query in r.problem or r.record_id in query:
                record = r
                break

        if record is None:
            # Use query directly as a problem
            from openjarvis.evals.core.types import EvalRecord
            record = EvalRecord(
                record_id=f"dynamic_{hash(query) % 10000}",
                problem=query,
                reference="",
                category="unknown",
            )

        try:
            result = self._backend.generate_full(
                prompt=record.problem,
                model=self.model,
                system=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = result.get("content", "")
            is_correct, _ = self._scorer.score(record, content)
            return 1.0 if is_correct else 0.0
        except Exception as exc:
            logger.warning("Single eval error: %s", exc)
            return 0.0

    def close(self) -> None:
        """Release all resources."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        if self._judge_backend is not None:
            self._judge_backend.close()
            self._judge_backend = None
        self._backend_key = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dataset(self) -> None:
        if self._dataset is None:
            from openjarvis.evals.cli import _build_dataset
            self._dataset = _build_dataset(self.benchmark)

    def _ensure_judge(self) -> None:
        if self._judge_backend is None:
            from openjarvis.evals.cli import (
                _build_judge_backend,
                _build_scorer,
            )
            self._judge_backend = _build_judge_backend(self.judge_model)
            self._scorer = _build_scorer(
                self.benchmark, self._judge_backend, self.judge_model,
            )

    def _rebuild_backend(self, candidate: Dict[str, Any]) -> None:
        """Rebuild the agent backend from candidate config."""
        if self._backend is not None:
            self._backend.close()

        from openjarvis.evals.cli import _build_backend

        agent_type = str(candidate.get("agent_type", "monitor_operative"))
        tool_set_str = str(candidate.get("tool_set", ""))
        tools = [t.strip() for t in tool_set_str.split(",") if t.strip()]
        max_turns = int(candidate.get("max_turns", 25))

        self._backend = _build_backend(
            backend_name="jarvis-agent",
            engine_key=self.engine_key,
            agent_name=agent_type,
            tools=tools,
            model=self.model,
            max_turns=max_turns,
        )

        logger.info(
            "Rebuilt backend: agent=%s, tools=%d, max_turns=%d",
            agent_type, len(tools), max_turns,
        )


def load_benchmark_queries(
    benchmark: str,
    max_samples: Optional[int] = None,
    seed: int = 42,
) -> List[str]:
    """Load benchmark task queries (problems only, no answers).

    Returns a list of query strings for data config C2/C3.
    """
    from openjarvis.evals.cli import _build_dataset

    dataset = _build_dataset(benchmark)
    dataset.load(max_samples=max_samples, seed=seed)
    records = list(dataset.iter_records())
    return [r.problem for r in records]


def load_external_data(source: str, max_samples: int = 5000) -> List[Dict[str, str]]:
    """Load external training data for data config C1/C3.

    Parameters
    ----------
    source:
        One of "general_thought", "agent_data".
    max_samples:
        Maximum examples to load.

    Returns list of {"query": ..., "reference": ...} dicts.
    """
    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning("datasets library not installed, returning empty")
        return []

    if source == "general_thought":
        ds = load_dataset(
            "GeneralThought/GeneralThought-430K",
            split=f"train[:{max_samples}]",
        )
        return [
            {"query": str(ex.get("instruction", "")), "reference": str(ex.get("output", ""))}
            for ex in ds
        ]
    elif source == "agent_data":
        ds = load_dataset(
            "neulab/agent-data-collection",
            split=f"train[:{max_samples}]",
        )
        return [
            {"query": str(ex.get("task", "")), "reference": str(ex.get("result", ""))}
            for ex in ds
        ]
    else:
        raise ValueError(f"Unknown source: {source}")


__all__ = ["LiveEvaluator", "load_benchmark_queries", "load_external_data"]
