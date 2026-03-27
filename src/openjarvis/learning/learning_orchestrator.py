"""LearningOrchestrator — coordinate the full trace->learn->eval loop.

Pulls traces from a :class:`TraceStore`, mines training data via
:class:`TrainingDataMiner`, evolves agent configs via
:class:`AgentConfigEvolver`, optionally runs LoRA fine-tuning, and
gates acceptance on an evaluation function.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

logger = logging.getLogger(__name__)


class LearningOrchestrator:
    """Orchestrate a single trace->learn->eval cycle.

    Parameters
    ----------
    trace_store:
        Object with ``list_traces(limit=...)`` returning ``List[Trace]``
        (typically a :class:`TraceStore`).
    config_dir:
        Directory where agent TOML configs are written / evolved.
    eval_fn:
        Optional callable returning a float score (higher = better).
        Called before and after learning to gate acceptance.
    min_improvement:
        Minimum improvement in eval score required to accept the update.
    min_sft_pairs:
        Minimum number of SFT pairs required to trigger LoRA training.
    min_quality:
        Minimum feedback quality threshold for :class:`TrainingDataMiner`.
    lora_config:
        Optional :class:`LoRATrainingConfig`.  When provided (and enough
        SFT pairs exist and ``torch`` is available), LoRA training runs.
    model_name:
        Model name for LoRA training (passed to :class:`LoRATrainer`).
    """

    def __init__(
        self,
        *,
        trace_store: Any,
        config_dir: Union[str, Path],
        eval_fn: Optional[Callable[[], float]] = None,
        min_improvement: float = 0.02,
        min_sft_pairs: int = 10,
        min_quality: float = 0.7,
        lora_config: Optional[Any] = None,
        model_name: Optional[str] = None,
    ) -> None:
        from openjarvis.learning.agents.agent_evolver import AgentConfigEvolver
        from openjarvis.learning.training.data import TrainingDataMiner

        self._trace_store = trace_store
        self._config_dir = Path(config_dir)
        self._eval_fn = eval_fn
        self._min_improvement = min_improvement
        self._min_sft_pairs = min_sft_pairs
        self._lora_config = lora_config
        self._model_name = model_name

        self._miner = TrainingDataMiner(trace_store, min_quality=min_quality)
        self._evolver = AgentConfigEvolver(trace_store, config_dir=self._config_dir)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def run(self, *, agent_id: str | None = None) -> Dict[str, Any]:
        """Execute one learning cycle.

        Parameters
        ----------
        agent_id:
            When provided, only traces from this agent are considered.

        Returns a dict with at least ``timestamp`` and ``status`` keys.

        Steps
        -----
        1. Mine traces: extract sft_pairs, routing_pairs, agent_pairs
        2. If no data: return skipped
        3. Run baseline eval (if eval_fn provided)
        4. Update routing recommendations
        5. Evolve agent configs
        6. Run LoRA training (if lora_config provided AND enough pairs
           AND torch available)
        7. Run post-learning eval (if eval_fn provided)
        8. Accept/reject based on improvement threshold
        """
        result: Dict[str, Any] = {
            "timestamp": time.time(),
        }

        # 1. Mine training data from traces
        sft_pairs = self._miner.extract_sft_pairs(agent=agent_id)
        routing_pairs = self._miner.extract_routing_pairs(agent=agent_id)
        agent_pairs = self._miner.extract_agent_config_pairs(agent=agent_id)

        result["sft_pairs"] = len(sft_pairs)
        result["routing_classes"] = len(routing_pairs)
        result["agent_classes"] = len(agent_pairs)

        # 2. Check if there is any data at all
        total_data = len(sft_pairs) + len(routing_pairs) + len(agent_pairs)
        if total_data == 0:
            result["status"] = "skipped"
            result["reason"] = "no training data available"
            return result

        # 3. Run baseline eval
        baseline_score: Optional[float] = None
        if self._eval_fn is not None:
            baseline_score = self._eval_fn()
            result["baseline_score"] = baseline_score

        # 4. Update routing recommendations
        result["routing_updated"] = len(routing_pairs) > 0

        # 5. Evolve agent configs
        recommendations = self._evolver.analyze()
        result["agent_configs_evolved"] = len(recommendations) > 0
        for rec in recommendations:
            agent_name = rec.get("recommended_agent", "default")
            tools = rec.get("recommended_tools", [])
            max_turns = rec.get("recommended_max_turns", 10)
            self._evolver.write_config(agent_name, tools=tools, max_turns=max_turns)

        # 6. LoRA training (optional)
        result["lora_training"] = None
        if self._lora_config is not None and len(sft_pairs) >= self._min_sft_pairs:
            lora_result = self._try_lora_training(sft_pairs)
            result["lora_training"] = lora_result

        # 7. Post-learning eval
        post_score: Optional[float] = None
        if self._eval_fn is not None:
            post_score = self._eval_fn()
            result["post_score"] = post_score

        # 8. Accept/reject based on improvement
        if baseline_score is not None and post_score is not None:
            improvement = post_score - baseline_score
            result["improvement"] = improvement
            if improvement >= self._min_improvement:
                result["accepted"] = True
                result["status"] = "completed"
            else:
                result["accepted"] = False
                result["status"] = "rejected"
                result["reason"] = (
                    f"eval improvement {improvement:.4f} below "
                    f"threshold {self._min_improvement}"
                )
        else:
            # No eval gate — always accept
            result["accepted"] = True
            result["status"] = "completed"

        return result

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _try_lora_training(
        self, sft_pairs: list[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Attempt LoRA training, returning result or None on failure."""
        try:
            from openjarvis.learning.training.lora import (
                HAS_TORCH,
                LoRATrainer,
            )
        except ImportError:
            logger.info("LoRA training skipped: training.lora not importable")
            return {"status": "skipped", "reason": "lora module unavailable"}

        if not HAS_TORCH:
            logger.info("LoRA training skipped: torch not available")
            return {"status": "skipped", "reason": "torch not available"}

        try:
            model_name = self._model_name or "Qwen/Qwen3-0.6B"
            trainer = LoRATrainer(self._lora_config, model_name=model_name)
            return trainer.train(sft_pairs)
        except Exception as exc:
            logger.warning("LoRA training failed: %s", exc)
            return {"status": "error", "reason": str(exc)}


__all__ = ["LearningOrchestrator"]
