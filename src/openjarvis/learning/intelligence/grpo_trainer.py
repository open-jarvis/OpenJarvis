"""General-purpose GRPO trainer -- Group Relative Policy Optimization.

Fine-tunes any local model by sampling N responses per prompt,
computing group-relative advantages, and applying a clipped policy
gradient with KL penalty vs a frozen reference model.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Protocol, runtime_checkable

from openjarvis.core.config import GRPOConfig
from openjarvis.core.registry import LearningRegistry
from openjarvis.learning._stubs import IntelligenceLearningPolicy

logger = logging.getLogger(__name__)

# Optional imports
try:
    import torch

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False
    torch = None  # type: ignore[assignment]

try:
    from transformers import AutoModelForCausalLM, AutoTokenizer

    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False


@runtime_checkable
class RewardFn(Protocol):
    """Protocol for reward functions used by GRPOTrainer."""

    def score(self, prompt: str, response: str, ground_truth: str | None) -> float: ...


class DefaultRewardFn:
    """Default reward function using length-normalized response quality heuristics."""

    def score(self, prompt: str, response: str, ground_truth: str | None) -> float:
        """Score a response. Higher is better, range [0, 1]."""
        score = 0.5  # baseline

        # Length heuristic: prefer non-empty, not-too-long responses
        if not response.strip():
            return 0.0
        resp_len = len(response)
        if resp_len < 10:
            score -= 0.1
        elif resp_len > 5000:
            score -= 0.05

        # Ground truth matching
        if ground_truth is not None:
            gt_lower = ground_truth.strip().lower()
            resp_lower = response.strip().lower()
            if gt_lower == resp_lower:
                score += 0.4
            elif gt_lower in resp_lower:
                score += 0.2

        return max(0.0, min(1.0, score))


class GRPOTrainer:
    """General-purpose GRPO trainer.

    Parameters
    ----------
    config:
        GRPOConfig controlling model, sampling, and optimization params.
    reward_fn:
        Pluggable reward function. Defaults to ``DefaultRewardFn``.
    """

    def __init__(
        self,
        config: GRPOConfig,
        reward_fn: RewardFn | None = None,
    ) -> None:
        self.config = config
        self.reward_fn: RewardFn = reward_fn or DefaultRewardFn()

    def train(self, trace_store: Any) -> Dict[str, Any]:
        """End-to-end: mine prompts from traces, then train.

        Parameters
        ----------
        trace_store:
            Object with ``list_traces()`` returning trace objects.
        """
        prompts = self._mine_prompts(trace_store)
        return self.train_on_prompts(prompts)

    def train_on_prompts(
        self,
        prompts: List[str],
        ground_truths: List[str | None] | None = None,
    ) -> Dict[str, Any]:
        """Run GRPO training on a set of prompts.

        Parameters
        ----------
        prompts:
            List of prompt strings to train on.
        ground_truths:
            Optional parallel list of ground-truth answers for reward scoring.
        """
        if not prompts:
            return {"status": "skipped", "reason": "no training data"}

        if len(prompts) < self.config.min_prompts:
            return {
                "status": "skipped",
                "reason": (
                    f"only {len(prompts)} prompts, "
                    f"min_prompts={self.config.min_prompts}"
                ),
            }

        if not HAS_TORCH:
            return {"status": "error", "reason": "torch not available"}

        if not HAS_TRANSFORMERS:
            return {"status": "error", "reason": "transformers not available"}

        try:
            return self._run_grpo(prompts, ground_truths)
        except Exception as exc:
            logger.warning("GRPO training failed: %s", exc)
            return {"status": "error", "reason": str(exc)}

    def _mine_prompts(self, trace_store: Any) -> List[str]:
        """Extract unique prompts from the trace store."""
        from openjarvis.learning.training.data import TrainingDataMiner

        miner = TrainingDataMiner(trace_store, min_quality=0.5)
        agent_filter = self.config.agent_filter or None
        pairs = miner.extract_sft_pairs(agent=agent_filter)
        # Deduplicate prompts
        seen: set[str] = set()
        prompts: List[str] = []
        for pair in pairs:
            q = pair.get("input", "")
            if q and q not in seen:
                seen.add(q)
                prompts.append(q)
        return prompts

    def _run_grpo(
        self,
        prompts: List[str],
        ground_truths: List[str | None] | None,
    ) -> Dict[str, Any]:
        """Execute the GRPO training loop.

        1. Load policy model and frozen reference model
        2. For each epoch:
           a. For each prompt, sample N responses from policy
           b. Score responses with reward_fn
           c. Compute group-relative advantages
           d. Compute clipped policy gradient + KL penalty
           e. Update policy weights
        """
        if ground_truths is None:
            ground_truths = [None] * len(prompts)

        # Load models
        tokenizer = AutoTokenizer.from_pretrained(self.config.model_name)
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        policy_model = AutoModelForCausalLM.from_pretrained(
            self.config.model_name,
            torch_dtype=torch.bfloat16,
            device_map="auto",
        )

        if self.config.gradient_checkpointing and hasattr(
            policy_model, "gradient_checkpointing_enable"
        ):
            policy_model.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False}
            )

        # Frozen reference model
        ref_kwargs: Dict[str, Any] = {
            "torch_dtype": torch.bfloat16,
            "device_map": "auto",
        }
        if self.config.use_8bit_ref:
            try:
                from transformers import BitsAndBytesConfig

                ref_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_8bit=True
                )
            except ImportError:
                pass
        ref_model = AutoModelForCausalLM.from_pretrained(
            self.config.model_name, **ref_kwargs
        )
        ref_model.requires_grad_(False)

        optimizer = torch.optim.AdamW(
            policy_model.parameters(),
            lr=self.config.learning_rate,
        )

        total_steps = 0
        cumulative_loss = 0.0

        policy_model.train()

        for epoch in range(self.config.num_epochs):
            epoch_loss = 0.0
            epoch_steps = 0

            for i in range(0, len(prompts), self.config.batch_size):
                batch_prompts = prompts[i : i + self.config.batch_size]
                batch_gts = ground_truths[i : i + self.config.batch_size]

                loss = self._grpo_step(
                    policy_model,
                    ref_model,
                    tokenizer,
                    optimizer,
                    batch_prompts,
                    batch_gts,
                )
                epoch_loss += loss
                epoch_steps += 1
                total_steps += 1

            avg_epoch_loss = epoch_loss / epoch_steps if epoch_steps else 0.0
            logger.info(
                "GRPO epoch %d/%d  loss=%.4f",
                epoch + 1,
                self.config.num_epochs,
                avg_epoch_loss,
            )
            cumulative_loss += epoch_loss

        avg_loss = cumulative_loss / total_steps if total_steps else 0.0
        return {
            "status": "completed",
            "epochs": self.config.num_epochs,
            "total_steps": total_steps,
            "avg_loss": avg_loss,
            "prompts": len(prompts),
        }

    def _grpo_step(
        self,
        policy_model: Any,
        ref_model: Any,
        tokenizer: Any,
        optimizer: Any,
        prompts: List[str],
        ground_truths: List[str | None],
    ) -> float:
        """Execute one GRPO gradient step on a batch of prompts."""
        all_rewards: List[List[float]] = []
        all_log_probs: List[List[Any]] = []
        all_ref_log_probs: List[List[Any]] = []

        for prompt, gt in zip(prompts, ground_truths):
            rewards = []
            log_probs = []
            ref_lps = []

            for _ in range(self.config.num_samples_per_prompt):
                # Sample response from policy
                inputs = tokenizer(
                    prompt,
                    return_tensors="pt",
                    truncation=True,
                    max_length=self.config.max_seq_length,
                ).to(policy_model.device)

                with torch.no_grad():
                    gen_ids = policy_model.generate(
                        **inputs,
                        max_new_tokens=self.config.max_response_length,
                        temperature=self.config.temperature,
                        do_sample=True,
                        pad_token_id=tokenizer.pad_token_id,
                    )

                response_ids = gen_ids[0, inputs["input_ids"].shape[1] :]
                response = tokenizer.decode(response_ids, skip_special_tokens=True)

                # Score with reward function
                reward = self.reward_fn.score(prompt, response, gt)
                rewards.append(reward)

                # Compute log probabilities
                full_ids = gen_ids[0].unsqueeze(0)
                policy_logits = policy_model(full_ids).logits
                policy_lp = torch.nn.functional.log_softmax(policy_logits, dim=-1)
                token_lps = torch.gather(
                    policy_lp[:, :-1, :], 2, full_ids[:, 1:].unsqueeze(-1)
                ).squeeze(-1)
                log_probs.append(token_lps.sum())

                with torch.no_grad():
                    ref_logits = ref_model(full_ids.to(ref_model.device)).logits
                    ref_lp = torch.nn.functional.log_softmax(ref_logits, dim=-1)
                    ref_token_lps = torch.gather(
                        ref_lp[:, :-1, :],
                        2,
                        full_ids[:, 1:].to(ref_model.device).unsqueeze(-1),
                    ).squeeze(-1)
                    ref_lps.append(ref_token_lps.sum())

            all_rewards.append(rewards)
            all_log_probs.append(log_probs)
            all_ref_log_probs.append(ref_lps)

        # Compute group-relative advantages and loss
        total_loss = torch.tensor(0.0, device=policy_model.device, requires_grad=True)

        for rewards, log_probs, ref_lps in zip(
            all_rewards, all_log_probs, all_ref_log_probs
        ):
            r_tensor = torch.tensor(rewards, device=policy_model.device)
            mean_r = r_tensor.mean()
            std_r = r_tensor.std() + 1e-8
            advantages = (r_tensor - mean_r) / std_r

            for adv, lp, ref_lp in zip(advantages, log_probs, ref_lps):
                ratio = torch.exp(lp - lp.detach())  # importance ratio
                clipped = torch.clamp(
                    ratio,
                    1 - self.config.clip_ratio,
                    1 + self.config.clip_ratio,
                )
                policy_loss = -torch.min(ratio * adv, clipped * adv)
                kl = lp - ref_lp.to(policy_model.device)
                total_loss = total_loss + policy_loss + self.config.kl_coef * kl

        optimizer.zero_grad()
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(
            policy_model.parameters(), self.config.max_grad_norm
        )
        optimizer.step()

        return total_loss.item()


@LearningRegistry.register("grpo")
class _GRPOLearningPolicy(IntelligenceLearningPolicy):
    """Wrapper to register GRPOTrainer in the LearningRegistry."""

    def __init__(self, **kwargs: object) -> None:
        pass

    def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
        from openjarvis.core.config import GRPOConfig

        config = GRPOConfig()
        trainer = GRPOTrainer(config)
        return trainer.train(trace_store)


__all__ = ["DefaultRewardFn", "GRPOTrainer", "RewardFn"]
