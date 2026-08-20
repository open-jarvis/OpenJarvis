"""GRPO (Group Relative Policy Optimization) trainer for orchestrator.

Adapted from IPW's ``trainer.py``.  GRPO is simpler than PPO because it
doesn't require a separate critic model — instead, it uses
*group-relative advantages*: for each problem, sample N candidate
trajectories, compute rewards, normalise within the group, and update
the policy to increase the probability of better solutions.

All ``torch``/``transformers`` imports are guarded so the module can be
imported without GPU dependencies.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

# Optional imports -----------------------------------------------------------
try:
    import torch
    import torch.nn.functional as F

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None  # type: ignore[assignment]
    F = None  # type: ignore[assignment]

from openjarvis.core.registry import LearningRegistry
from openjarvis.learning._stubs import IntelligenceLearningPolicy

logger = logging.getLogger(__name__)


def _select_torch_device():
    """Select the best available PyTorch device (cuda > mps > cpu)."""
    if not HAS_TORCH or torch is None:
        return None
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorGRPOConfig:
    """Configuration for orchestrator GRPO training."""

    # Model
    model_name: str = "Qwen/Qwen3-1.7B"
    max_prompt_length: int = 24000
    max_response_length: int = 8768

    # Training
    num_epochs: int = 10
    batch_size: int = 16
    learning_rate: float = 1e-6
    max_grad_norm: float = 1.0

    # GRPO specific
    num_samples_per_prompt: int = 8
    temperature: float = 1.0
    kl_coef: float = 0.0001
    clip_ratio: float = 0.2

    # Environment
    available_tools: List[str] = field(
        default_factory=lambda: [
            "calculator",
            "think",
            "code_interpreter",
            "web_search",
        ]
    )
    max_turns: int = 10

    # Checkpoint
    checkpoint_dir: str = "checkpoints/orchestrator_grpo"
    save_every_n_epochs: int = 1
    keep_last_n: int = 3

    # Memory
    gradient_checkpointing: bool = True
    use_8bit_ref: bool = True
    use_8bit_optimizer: bool = False


# ---------------------------------------------------------------------------
# Trainer
# ---------------------------------------------------------------------------


class OrchestratorGRPOTrainer:
    """GRPO trainer for orchestrator policy.

    ``torch`` must be installed to call :meth:`train`.
    """

    def __init__(self, config: OrchestratorGRPOConfig) -> None:
        self.config = config
        self.device = None
        self.global_step = 0

        if HAS_TORCH and torch is not None:
            self.device = _select_torch_device()

        self._init_model()
        self._init_optimizer()

    # -- Initialisation ------------------------------------------------------

    def _init_model(self) -> None:
        from openjarvis.learning.intelligence.orchestrator.policy_model import (
            OrchestratorPolicyModel,
        )

        if not HAS_TORCH:
            self.policy: Any = OrchestratorPolicyModel()
            self.ref_policy: Any = OrchestratorPolicyModel()
            return

        device_str = str(self.device) if self.device else None

        self.policy = OrchestratorPolicyModel.from_pretrained(
            self.config.model_name,
            gradient_checkpointing=self.config.gradient_checkpointing,
            device=device_str,
        )
        if self.policy.model is not None:
            self.policy.model.train()

        self.ref_policy = OrchestratorPolicyModel.from_pretrained(
            self.config.model_name,
            load_in_8bit=self.config.use_8bit_ref,
            device=device_str,
        )
        if self.ref_policy.model is not None:
            self.ref_policy.model.eval()
            for param in self.ref_policy.model.parameters():
                param.requires_grad = False

    def _init_optimizer(self) -> None:
        if not HAS_TORCH or self.policy.model is None:
            self.optimizer: Any = None
            return

        if self.config.use_8bit_optimizer:
            try:
                import bitsandbytes as bnb

                self.optimizer = bnb.optim.AdamW8bit(
                    self.policy.model.parameters(),
                    lr=self.config.learning_rate,
                )
                return
            except ImportError as exc:
                logger.debug("FP8 not available for GRPO: %s", exc)

        self.optimizer = torch.optim.AdamW(
            self.policy.model.parameters(),
            lr=self.config.learning_rate,
        )

    # -- Training loop -------------------------------------------------------

    def train(self) -> None:
        """Run the GRPO training loop."""
        if not HAS_TORCH:
            raise RuntimeError(
                "PyTorch is required for training. "
                "Install with: pip install torch transformers"
            )

        for epoch in range(self.config.num_epochs):
            self._train_epoch(epoch)

            if (epoch + 1) % self.config.save_every_n_epochs == 0:
                self._save_checkpoint(epoch)

    def _train_epoch(self, epoch: int) -> Dict[str, float]:
        if self.policy.model is None:
            return {"epoch": epoch, "loss": 0.0, "reward": 0.0}

        self.policy.model.train()
        total_loss = 0.0
        total_reward = 0.0
        num_batches = 0

        # In a real implementation, iterate over a task dataset.
        # Here we provide the skeleton; actual data loading is
        # trainer-specific.
        self.global_step += 1
        num_batches = max(num_batches, 1)

        avg_loss = total_loss / num_batches if num_batches > 0 else 0.0
        avg_reward = total_reward / num_batches if num_batches > 0 else 0.0
        return {"epoch": epoch, "loss": avg_loss, "reward": avg_reward}

    def _grpo_step(
        self,
        prompts: List[str],
        ground_truths: List[str],
    ) -> tuple:
        """Perform one GRPO training step.

        For each prompt:
        1. Generate N candidate trajectories.
        2. Compute reward for each.
        3. Normalise advantages within the group.
        4. Compute clipped policy gradient + KL penalty.
        5. Backward + clip + step.

        Returns ``(loss_value, avg_reward)``.
        """
        if self.policy.model is None or not HAS_TORCH:
            raise RuntimeError("Cannot train without PyTorch and model.")

        self.policy.model.train()

        all_prompts: list[str] = []
        all_responses: list[str] = []
        all_advantages: list[float] = []
        all_rewards: list[float] = []

        from openjarvis.learning.intelligence.orchestrator.reward import (
            MultiObjectiveReward,
            Normalizers,
            RewardWeights,
        )
        from openjarvis.learning.intelligence.orchestrator.types import (
            Episode,
        )

        reward_fn = MultiObjectiveReward(RewardWeights(), Normalizers())

        for prompt, gt in zip(prompts, ground_truths):
            group_rewards: list[float] = []
            group_responses: list[str] = []

            for _ in range(self.config.num_samples_per_prompt):
                response, _log_probs = self._generate_with_log_probs(prompt)

                # Build a minimal episode for reward computation
                episode = Episode(
                    task_id="grpo",
                    initial_prompt=prompt,
                    ground_truth=gt,
                    final_answer=response,
                    correct=(response.strip() == gt.strip()),
                )
                reward = reward_fn.compute(episode)

                group_rewards.append(reward)
                group_responses.append(response)

            # Group-relative advantages
            mean_r = sum(group_rewards) / len(group_rewards)
            std_r = (
                sum((r - mean_r) ** 2 for r in group_rewards) / len(group_rewards)
            ) ** 0.5
            if std_r > 1e-8:
                advantages = [(r - mean_r) / std_r for r in group_rewards]
            else:
                advantages = [0.0] * len(group_rewards)

            for resp, adv, rew in zip(group_responses, advantages, group_rewards):
                all_prompts.append(prompt)
                all_responses.append(resp)
                all_advantages.append(adv)
                all_rewards.append(rew)

        # Policy gradient loss
        total_loss = torch.tensor(0.0, device=self.device, requires_grad=True)

        for prompt, response, advantage in zip(
            all_prompts, all_responses, all_advantages
        ):
            current_lp = self._compute_log_probs(prompt, response)
            with torch.no_grad():
                ref_lp = self._compute_log_probs_ref(prompt, response)

            log_ratio = current_lp - ref_lp
            ratio = torch.exp(log_ratio)
            ratio = torch.clamp(ratio, min=0.01, max=100.0)

            clip = self.config.clip_ratio
            clipped = torch.clamp(ratio, 1 - clip, 1 + clip)

            policy_loss = -torch.min(ratio * advantage, clipped * advantage)
            kl = (ratio - 1) - log_ratio
            total_loss = total_loss + policy_loss + self.config.kl_coef * kl

        avg_loss = total_loss / max(len(all_prompts), 1)
        loss_val = avg_loss.item()

        if torch.isnan(avg_loss) or torch.isinf(avg_loss):
            avg_reward = sum(all_rewards) / len(all_rewards) if all_rewards else 0.0
            return 0.0, float(avg_reward)

        self.optimizer.zero_grad()
        avg_loss.backward()

        # Check for NaN gradients
        for param in self.policy.model.parameters():
            if param.grad is not None and torch.isnan(param.grad).any():
                self.optimizer.zero_grad()
                avg_reward = sum(all_rewards) / len(all_rewards) if all_rewards else 0.0
                return float(loss_val), float(avg_reward)

        torch.nn.utils.clip_grad_norm_(
            self.policy.model.parameters(), self.config.max_grad_norm
        )
        self.optimizer.step()

        avg_reward = sum(all_rewards) / len(all_rewards) if all_rewards else 0.0
        return float(loss_val), float(avg_reward)

    # -- Generation / log-prob helpers ---------------------------------------

    def _generate_with_log_probs(self, prompt: str) -> "tuple[str, Any]":
        """Generate a response and return ``(text, log_probs)``."""
        inputs = self.policy.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=min(self.config.max_prompt_length, 16000),
        ).to(self.device)

        input_len = inputs.input_ids.shape[1]
        max_new = min(self.config.max_response_length, 32000 - input_len - 100)
        max_new = max(min(max_new, 2048), 128)

        with torch.no_grad():
            outputs = self.policy.model.generate(
                **inputs,
                max_new_tokens=max_new,
                temperature=self.config.temperature,
                do_sample=True,
                output_scores=True,
                return_dict_in_generate=True,
            )

        generated_ids = outputs.sequences[0][input_len:]
        if len(generated_ids) == 0:
            return "", torch.tensor(0.0, device=self.device)

        text = self.policy.tokenizer.decode(generated_ids, skip_special_tokens=True)

        log_probs = []
        for token_id, logits in zip(generated_ids, outputs.scores):
            probs = F.softmax(logits[0], dim=-1)
            tid = token_id.item()
            if 0 <= tid < probs.shape[0]:
                log_probs.append(torch.log(probs[tid] + 1e-10))

        total_lp = (
            torch.stack(log_probs).sum()
            if log_probs
            else torch.tensor(0.0, device=self.device)
        )
        return text, total_lp

    def _compute_log_probs(self, prompt: str, response: str) -> "torch.Tensor":
        """Log-probs of *response* given *prompt* under current policy."""
        full = prompt + response
        inputs = self.policy.tokenizer(full, return_tensors="pt", truncation=True).to(
            self.device
        )
        prompt_inputs = self.policy.tokenizer(
            prompt, return_tensors="pt", truncation=True
        ).to(self.device)

        with torch.enable_grad():
            logits = self.policy.model(**inputs).logits

        start = len(prompt_inputs.input_ids[0])
        end = len(inputs.input_ids[0])

        lps = []
        for i in range(start, end - 1):
            lp = F.log_softmax(logits[0, i, :], dim=-1)[inputs.input_ids[0, i + 1]]
            lps.append(lp)

        return torch.stack(lps).sum() if lps else torch.tensor(0.0)

    def _compute_log_probs_ref(self, prompt: str, response: str) -> "torch.Tensor":
        """Log-probs under the frozen reference policy (no grad)."""
        full = prompt + response
        inputs = self.ref_policy.tokenizer(
            full, return_tensors="pt", truncation=True
        ).to(self.device)
        prompt_inputs = self.ref_policy.tokenizer(
            prompt, return_tensors="pt", truncation=True
        ).to(self.device)

        with torch.no_grad():
            logits = self.ref_policy.model(**inputs).logits

        start = len(prompt_inputs.input_ids[0])
        end = len(inputs.input_ids[0])

        lps = []
        for i in range(start, end - 1):
            lp = F.log_softmax(logits[0, i, :], dim=-1)[inputs.input_ids[0, i + 1]]
            lps.append(lp)

        return torch.stack(lps).sum() if lps else torch.tensor(0.0)

    # -- Checkpointing -------------------------------------------------------

    def _save_checkpoint(self, epoch: int) -> None:
        checkpoint_dir = Path(self.config.checkpoint_dir)
        checkpoint_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_path = checkpoint_dir / f"epoch_{epoch + 1}"
        if self.policy.model is not None:
            self.policy.save(str(checkpoint_path))

            state_path = checkpoint_path / "training_state.json"
            state = {
                "epoch": epoch,
                "global_step": self.global_step,
                "config": asdict(self.config),
            }
            with open(state_path, "w") as f:
                json.dump(state, f, indent=2)

        self._cleanup_old_checkpoints()

    def _cleanup_old_checkpoints(self) -> None:
        checkpoint_dir = Path(self.config.checkpoint_dir)
        if not checkpoint_dir.exists():
            return

        checkpoints = sorted(
            [
                d
                for d in checkpoint_dir.iterdir()
                if d.is_dir() and d.name.startswith("epoch_")
            ],
            key=lambda x: int(x.name.split("_")[1]),
            reverse=True,
        )

        for old in checkpoints[self.config.keep_last_n :]:
            shutil.rmtree(old)


# ---------------------------------------------------------------------------
# Registry wrapper
# ---------------------------------------------------------------------------


def _ensure_registered() -> None:
    if LearningRegistry.contains("orchestrator_grpo"):
        return

    @LearningRegistry.register("orchestrator_grpo")
    class OrchestratorGRPOPolicy(IntelligenceLearningPolicy):
        """Wrapper that registers the GRPO trainer as a learning policy."""

        def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
            config = OrchestratorGRPOConfig(
                **{
                    k: v
                    for k, v in kwargs.items()
                    if k in OrchestratorGRPOConfig.__dataclass_fields__
                }
            )
            trainer = OrchestratorGRPOTrainer(config)
            trainer.train()
            return {"status": "grpo_training_complete"}


_ensure_registered()


__all__ = [
    "OrchestratorGRPOConfig",
    "OrchestratorGRPOTrainer",
]
