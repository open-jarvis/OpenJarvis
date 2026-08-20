"""General-purpose SFT trainer -- fine-tune any local LM on trace-derived pairs.

Delegates to :class:`LoRATrainer` from ``training/lora.py`` when ``use_lora=True``.
Supports ``train(trace_store)`` for end-to-end pipeline and ``train_on_pairs()``
for pre-extracted data.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from openjarvis.core.config import SFTConfig
from openjarvis.core.registry import LearningRegistry
from openjarvis.learning._stubs import IntelligenceLearningPolicy

logger = logging.getLogger(__name__)


class SFTTrainer:
    """General-purpose supervised fine-tuning trainer.

    Parameters
    ----------
    config:
        SFTConfig controlling model, LoRA params, and training hyperparams.
    """

    def __init__(self, config: SFTConfig) -> None:
        self.config = config

    @property
    def target_module_list(self) -> List[str]:
        """Parse comma-separated target_modules string into a list."""
        return [m.strip() for m in self.config.target_modules.split(",") if m.strip()]

    def train(self, trace_store: Any) -> Dict[str, Any]:
        """End-to-end: mine SFT pairs from traces, then train.

        Parameters
        ----------
        trace_store:
            Object with ``list_traces()`` returning trace objects.

        Returns
        -------
        dict with at least ``status`` key.
        """
        pairs = self._mine_pairs(trace_store)
        return self.train_on_pairs(pairs)

    def train_on_pairs(self, pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Train on pre-extracted SFT pairs.

        Parameters
        ----------
        pairs:
            List of dicts with at least ``input`` and ``output`` keys.

        Returns
        -------
        dict with ``status``, ``training_samples``, and training metrics.
        """
        if not pairs:
            return {"status": "skipped", "reason": "no training data"}

        if len(pairs) < self.config.min_pairs:
            return {
                "status": "skipped",
                "reason": f"only {len(pairs)} pairs, min_pairs={self.config.min_pairs}",
            }

        if self.config.use_lora:
            return self._train_lora(pairs)

        return self._train_full(pairs)

    def _mine_pairs(self, trace_store: Any) -> List[Dict[str, Any]]:
        """Extract SFT pairs from the trace store using TrainingDataMiner."""
        from openjarvis.learning.training.data import TrainingDataMiner

        miner = TrainingDataMiner(trace_store, min_quality=0.7)
        agent_filter = self.config.agent_filter or None
        return miner.extract_sft_pairs(agent=agent_filter)

    def _train_lora(self, pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Train using LoRA via the existing LoRATrainer."""
        try:
            from openjarvis.learning.training.lora import (
                HAS_TORCH,
                LoRATrainer,
                LoRATrainingConfig,
            )
        except ImportError:
            return {"status": "error", "reason": "training.lora not importable"}

        if not HAS_TORCH:
            return {"status": "error", "reason": "torch not available"}

        lora_config = LoRATrainingConfig(
            lora_rank=self.config.lora_rank,
            lora_alpha=self.config.lora_alpha,
            lora_dropout=self.config.lora_dropout,
            target_modules=self.target_module_list,
            num_epochs=self.config.num_epochs,
            batch_size=self.config.batch_size,
            learning_rate=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
            warmup_ratio=self.config.warmup_ratio,
            max_grad_norm=self.config.max_grad_norm,
            max_seq_length=self.config.max_seq_length,
            use_4bit=self.config.use_4bit,
            output_dir=self.config.checkpoint_dir,
            gradient_checkpointing=self.config.gradient_checkpointing,
        )

        try:
            trainer = LoRATrainer(lora_config, model_name=self.config.model_name)
            return trainer.train(pairs)
        except Exception as exc:
            logger.warning("SFT LoRA training failed: %s", exc)
            return {"status": "error", "reason": str(exc)}

    def _train_full(self, pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Full fine-tuning (no LoRA). Placeholder for future implementation."""
        return {
            "status": "error",
            "reason": "full fine-tuning not yet implemented; set use_lora=true",
        }


@LearningRegistry.register("sft")
class _SFTLearningPolicy(IntelligenceLearningPolicy):
    """Wrapper to register SFTTrainer in the LearningRegistry."""

    def __init__(self, **kwargs: object) -> None:
        pass

    def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
        from openjarvis.core.config import SFTConfig

        config = SFTConfig()
        trainer = SFTTrainer(config)
        return trainer.train(trace_store)


__all__ = ["SFTTrainer"]
