"""GRPO (Group Relative Policy Optimization) trainer for orchestrator.

Adapted from IPW's ``trainer.py``.  GRPO is simpler than PPO because it
doesn't require a separate critic model — instead, it uses
*group-relative advantages*: for each problem, sample N candidate
trajectories, compute rewards, normalise within the group, and update
the policy to increase the probability of better solutions.

**Trajectory-level GRPO over the unified tool-use rollout.** Generation
flows through :func:`run_unified_rollout` (the SAME faithful
``<tool_call>`` multi-turn loop our SFT data is built from), NOT the old
single-turn ``THOUGHT/TOOL/INPUT`` environment path. The policy *is* the
orchestrator: each turn we tokenize ``system+user`` with the model's chat
template, generate ONE assistant turn, parse any
``<tool_call>{...}</tool_call>``, and record the exact
``(input_ids, generated_ids)`` for that turn. Once a rollout finishes, the
recorded turns are stitched into one trajectory token sequence with an
*assistant mask* (1 only on policy-generated tokens) so the policy gradient
is computed solely over the tokens the model actually authored, under both
the current policy (with grad) and the frozen reference (no grad).

All ``torch``/``transformers`` imports are guarded so the module can be
imported without GPU dependencies; the rollout + log-prob paths are
monkeypatchable so ``_grpo_step``/``_train_epoch`` are CPU-smoke-testable
with fakes (``policy.model is None``).
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
    # ``num_samples_per_prompt`` is the GRPO *group size*: N trajectories
    # sampled per prompt for group-relative advantages.
    num_samples_per_prompt: int = 8
    temperature: float = 1.0
    kl_coef: float = 0.0001
    clip_ratio: float = 0.2

    # Data / batching
    # How many prompts to pool from the GRPO dataset (cached on the trainer).
    grpo_max_prompts: int = 20000
    # How many prompts go into one ``_grpo_step`` (a batch / step). With
    # group_size N this is prompts_per_step * N trajectories per step.
    prompts_per_step: int = 256

    # Cost-aware reward (r=+1/-1, R -= lam * cost / cost_max). ``lam`` is swept.
    lam: float = 0.0
    cost_max: float = 0.10

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
    # Optional local OSS model endpoints, mapping full model id (e.g.
    # "Qwen/Qwen3.5-9B") -> vLLM base_url. Passed to ``orchestrator_catalog``
    # so the local-model tools dispatch to a served endpoint; omitted when
    # unset (tool still listed, just unbacked).
    local_endpoints: Dict[str, str] = field(default_factory=dict)

    # Checkpoint
    checkpoint_dir: str = "checkpoints/orchestrator_grpo"
    save_every_n_epochs: int = 1
    keep_last_n: int = 3

    # Memory
    gradient_checkpointing: bool = True
    use_8bit_ref: bool = True
    use_8bit_optimizer: bool = False


@dataclass
class RolloutRecord:
    """One sampled unified-rollout trajectory, with the tokens + assistant mask
    needed to compute its policy log-prob.

    ``token_ids`` is the full stitched trajectory (prompt / observation tokens
    interleaved with policy-generated tokens over turns). ``assistant_mask``
    is parallel: 1 only on policy-generated positions. ``advantage`` is filled
    in after group-relative normalisation.
    """

    final_answer: str
    cost_usd: float
    token_ids: List[int] = field(default_factory=list)
    assistant_mask: List[int] = field(default_factory=list)
    advantage: float = 0.0


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

        # Cost-aware reward (r=+1/-1, R -= lam * cost / cost_max). ``lam``
        # is swept across runs to trace the accuracy/cost Pareto frontier.
        from openjarvis.learning.intelligence.orchestrator.reward import (
            CostAwareReward,
        )

        self._reward = CostAwareReward(lam=config.lam, cost_max=config.cost_max)

        # Lazily-loaded, cached GRPO prompt pool (list[Task]).
        self._prompts: List[Any] | None = None
        # Lazily-built, cached unified tool catalog (list[ExpertTool]).
        self._tool_catalog: Optional[List[Any]] = None

        if HAS_TORCH and torch is not None:
            self.device = _select_torch_device()

        self._init_model()
        self._init_optimizer()

    # -- Data ----------------------------------------------------------------

    def _load_prompts(self) -> List[Any]:
        """Load (and cache) the GRPO prompt pool — a ``list[Task]``."""
        if self._prompts is None:
            from openjarvis.learning.intelligence.orchestrator.sft_data.datasets import (  # noqa: E501
                load_grpo_prompts,
            )

            self._prompts = load_grpo_prompts(n=self.config.grpo_max_prompts)
        return self._prompts

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
        """Iterate the GRPO prompt pool in chunks and run ``_grpo_step``.

        Prompts are loaded once via :meth:`_load_prompts` (cached on the
        trainer) and chunked into batches of ``config.prompts_per_step``.
        Each chunk is one ``_grpo_step`` call (group_size trajectories per
        prompt). Real model work happens inside ``_grpo_step`` and is
        guarded there; ``_train_epoch`` itself does no torch work, so it
        can be smoke-tested on CPU by monkeypatching ``_grpo_step``.
        """
        if HAS_TORCH and self.policy.model is not None:
            self.policy.model.train()

        prompts = self._load_prompts()
        step_size = max(int(self.config.prompts_per_step), 1)

        total_loss = 0.0
        total_reward = 0.0
        total_accuracy = 0.0
        n_prompts = 0
        num_batches = 0

        for start in range(0, len(prompts), step_size):
            chunk = prompts[start : start + step_size]
            if not chunk:
                continue
            metrics = self._grpo_step(chunk)
            loss = float(metrics.get("loss", 0.0))
            reward = float(metrics.get("reward", 0.0))
            accuracy = float(metrics.get("accuracy", 0.0))
            n = int(metrics.get("n_prompts", len(chunk)))

            total_loss += loss * n
            total_reward += reward * n
            total_accuracy += accuracy * n
            n_prompts += n
            num_batches += 1
            self.global_step += 1

        denom = n_prompts if n_prompts > 0 else 1
        return {
            "epoch": epoch,
            "loss": total_loss / denom,
            "reward": total_reward / denom,
            "accuracy": total_accuracy / denom,
            "n_prompts": n_prompts,
            "n_batches": num_batches,
        }

    # -- Tool catalog --------------------------------------------------------

    def _tools(self) -> List[Any]:
        """The orchestrator's unified tool catalog (cached).

        Two model classes (cloud frontier + local OSS) plus the basic tools,
        exactly what the rollout / SFT data condition on. ``local_endpoints``
        wires the local-model tools to their served vLLM endpoints.
        """
        if getattr(self, "_tool_catalog", None) is None:
            from openjarvis.agents.hybrid.expert_registry import (
                orchestrator_catalog,
            )

            self._tool_catalog = orchestrator_catalog(
                local_endpoints=dict(self.config.local_endpoints) or None,
            )
        return self._tool_catalog

    # -- Rollout / trajectory collection -------------------------------------

    def _rollout_group(self, task: Any) -> List["RolloutRecord"]:
        """Sample ``group_size`` rollouts for one task through the unified loop.

        Each rollout is driven by a *policy* ``call_orchestrator`` (the HF
        model being trained generating one assistant turn at a time) and the
        real :func:`make_dispatch` tool executor. Per turn we capture the exact
        ``(input_ids, generated_ids)`` so the trajectory token sequence +
        assistant mask can be rebuilt for the log-prob pass.

        Returns one :class:`RolloutRecord` per sampled rollout. Overridable /
        monkeypatchable in tests so ``_grpo_step`` runs with fakes when
        ``policy.model is None``.
        """
        from openjarvis.agents.hybrid.toolorchestra.rollout import (
            build_system_prompt,
            run_unified_rollout,
        )
        from openjarvis.agents.hybrid.toolorchestra.unified import make_dispatch
        from openjarvis.agents.hybrid.expert_registry import build_tool_specs

        tools = self._tools()
        system = build_system_prompt(build_tool_specs(tools))
        dispatch = make_dispatch({})

        records: List[RolloutRecord] = []
        for _ in range(self.config.num_samples_per_prompt):
            turn_buffer: List[Tuple[List[int], List[int]]] = []
            call_orchestrator = self._make_policy_caller(turn_buffer)
            rollout = run_unified_rollout(
                task.instruction,
                tools,
                call_orchestrator=call_orchestrator,
                dispatch=dispatch,
                max_turns=self.config.max_turns,
                system=system,
            )
            token_ids, assistant_mask = self._stitch_trajectory(turn_buffer)
            records.append(
                RolloutRecord(
                    final_answer=rollout.final_answer,
                    cost_usd=float(rollout.cost_usd),
                    token_ids=token_ids,
                    assistant_mask=assistant_mask,
                )
            )
        return records

    def _make_policy_caller(self, turn_buffer):
        """Build a policy-driven ``call_orchestrator(system, user, specs)``.

        Tokenizes ``system+user`` with the model's chat template, generates ONE
        assistant turn with the current policy, parses any
        ``<tool_call>{...}</tool_call>``, appends the per-turn
        ``(input_ids, generated_ids)`` to ``turn_buffer`` (for the later
        log-prob pass), and returns
        ``(text, tool_calls, prompt_tokens, completion_tokens)`` as the unified
        rollout expects.
        """
        from openjarvis.agents.hybrid.toolorchestra.parsing import (
            _parse_rl_tool_call,
        )

        tok = self.policy.tokenizer

        def call_orchestrator(system: str, user: str, specs):
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            input_ids = tok.apply_chat_template(
                messages, add_generation_prompt=True, tokenize=True
            )
            inputs = {
                "input_ids": torch.tensor([input_ids], device=self.device),
            }
            input_len = len(input_ids)
            max_new = min(self.config.max_response_length, 32000 - input_len - 100)
            max_new = max(min(max_new, 2048), 16)

            with torch.no_grad():
                out = self.policy.model.generate(
                    **inputs,
                    max_new_tokens=max_new,
                    temperature=self.config.temperature,
                    do_sample=True,
                )
            gen_ids = out[0][input_len:].tolist()
            text = tok.decode(gen_ids, skip_special_tokens=True)

            # Record exact tokens for the trajectory log-prob pass.
            turn_buffer.append((list(input_ids), list(gen_ids)))

            parsed = _parse_rl_tool_call(text, None)
            tool_calls = (
                [(parsed["name"], parsed["arguments"])] if parsed else []
            )
            return text, tool_calls, int(input_len), int(len(gen_ids))

        return call_orchestrator

    def _stitch_trajectory(
        self, turn_buffer: List[Tuple[List[int], List[int]]]
    ) -> Tuple[List[int], List[int]]:
        """Concatenate per-turn tokens into one trajectory + assistant mask.

        For turn ``i`` the buffer holds ``(prompt_ids_i, gen_ids_i)`` where
        ``prompt_ids_i`` already contains all prior turns' assistant text and
        the tool observations re-rendered into the chat by the rollout loop
        (the rollout rebuilds ``user`` each turn from the running context). So
        the faithful trajectory token stream is, for each turn, the *new*
        prefix tokens (mask 0 — prompt / observation / chat-template tokens)
        followed by the generated assistant tokens (mask 1).

        We reconstruct it by diffing successive prompts: turn ``i`` contributes
        the prompt tokens that weren't already emitted, then its generated
        tokens. This keeps the assistant mask exact (1 only on policy-generated
        positions) without re-tokenizing the whole transcript.
        """
        token_ids: List[int] = []
        mask: List[int] = []
        emitted = 0  # length of token_ids already produced
        for prompt_ids, gen_ids in turn_buffer:
            # New prompt-side tokens for this turn (everything past what we've
            # already emitted). These are observation / chat-template tokens →
            # mask 0 (not policy-authored).
            new_prompt = prompt_ids[emitted:] if len(prompt_ids) > emitted else []
            token_ids.extend(new_prompt)
            mask.extend([0] * len(new_prompt))
            # Generated assistant tokens → mask 1.
            token_ids.extend(gen_ids)
            mask.extend([1] * len(gen_ids))
            emitted = len(token_ids)
        return token_ids, mask

    def _grpo_step(self, tasks: List[Any]) -> Dict[str, float]:
        """Perform one GRPO training step over a batch of ``Task`` objects.

        For each task:
        1. Sample N candidate trajectories (``group_size`` =
           ``num_samples_per_prompt``) through the unified tool-use rollout —
           the SAME ``<tool_call>`` multi-turn path the SFT data uses, driven
           by the *policy* as orchestrator (see :meth:`_rollout_group`).
        2. Verify each rollout's ``final_answer`` against the gold answer
           (:func:`verify_answer`) and score with :class:`CostAwareReward`
           over an :class:`Episode` carrying ``.correct`` and
           ``.total_cost_usd``.
        3. Normalise advantages within the group (mean/std).
        4. Compute the trajectory-level clipped policy gradient + KL penalty.
           The trajectory log-prob is the sum of per-token log-probs over the
           *assistant-masked* positions (:meth:`_trajectory_logprob`).
        5. Backward + clip + step.

        Returns a metrics dict with ``loss``, ``reward``, ``accuracy``,
        and ``n_prompts``.
        """
        if self.policy.model is None or not HAS_TORCH:
            raise RuntimeError("Cannot train without PyTorch and model.")

        self.policy.model.train()

        from openjarvis.learning.intelligence.orchestrator.sft_data.verify import (
            verify_answer,
        )
        from openjarvis.learning.intelligence.orchestrator.types import (
            Episode,
        )

        reward_fn = self._reward

        # (token_ids, assistant_mask, advantage) per trajectory, plus running
        # reward / accuracy stats.
        traj_records: list[RolloutRecord] = []
        all_advantages: list[float] = []
        all_rewards: list[float] = []
        all_correct: list[float] = []

        for task in tasks:
            records = self._rollout_group(task)
            group_rewards: list[float] = []

            for rec in records:
                correct = verify_answer(task, rec.final_answer)
                episode = Episode(
                    task_id=getattr(task, "task_id", ""),
                    initial_prompt=task.instruction,
                    ground_truth=getattr(task, "answer", ""),
                    final_answer=rec.final_answer,
                    correct=bool(correct),
                    total_cost_usd=rec.cost_usd,
                )
                reward = reward_fn.compute(episode)
                group_rewards.append(reward)
                all_correct.append(1.0 if correct else 0.0)

            # Group-relative advantages (mean/std within the group).
            mean_r = sum(group_rewards) / len(group_rewards)
            std_r = (
                sum((r - mean_r) ** 2 for r in group_rewards) / len(group_rewards)
            ) ** 0.5
            if std_r > 1e-8:
                advantages = [(r - mean_r) / std_r for r in group_rewards]
            else:
                advantages = [0.0] * len(group_rewards)

            for rec, adv, rew in zip(records, advantages, group_rewards):
                rec.advantage = adv
                traj_records.append(rec)
                all_advantages.append(adv)
                all_rewards.append(rew)

        # Trajectory-level policy gradient loss.
        total_loss = torch.tensor(0.0, device=self.device, requires_grad=True)

        for rec in traj_records:
            if not rec.token_ids or sum(rec.assistant_mask) == 0:
                continue
            current_lp = self._trajectory_logprob(
                rec.token_ids, rec.assistant_mask, ref=False
            )
            with torch.no_grad():
                ref_lp = self._trajectory_logprob(
                    rec.token_ids, rec.assistant_mask, ref=True
                )

            log_ratio = current_lp - ref_lp
            ratio = torch.exp(log_ratio)
            ratio = torch.clamp(ratio, min=0.01, max=100.0)

            clip = self.config.clip_ratio
            clipped = torch.clamp(ratio, 1 - clip, 1 + clip)

            policy_loss = -torch.min(ratio * rec.advantage, clipped * rec.advantage)
            kl = (ratio - 1) - log_ratio
            total_loss = total_loss + policy_loss + self.config.kl_coef * kl

        n_prompts = len(tasks)
        avg_reward = sum(all_rewards) / len(all_rewards) if all_rewards else 0.0
        avg_acc = sum(all_correct) / len(all_correct) if all_correct else 0.0

        n_traj = max(len(traj_records), 1)
        avg_loss = total_loss / n_traj
        loss_val = avg_loss.item()

        if torch.isnan(avg_loss) or torch.isinf(avg_loss):
            return {
                "loss": 0.0,
                "reward": float(avg_reward),
                "accuracy": float(avg_acc),
                "n_prompts": n_prompts,
            }

        self.optimizer.zero_grad()
        avg_loss.backward()

        # Check for NaN gradients
        for param in self.policy.model.parameters():
            if param.grad is not None and torch.isnan(param.grad).any():
                self.optimizer.zero_grad()
                return {
                    "loss": float(loss_val),
                    "reward": float(avg_reward),
                    "accuracy": float(avg_acc),
                    "n_prompts": n_prompts,
                }

        torch.nn.utils.clip_grad_norm_(
            self.policy.model.parameters(), self.config.max_grad_norm
        )
        self.optimizer.step()

        return {
            "loss": float(loss_val),
            "reward": float(avg_reward),
            "accuracy": float(avg_acc),
            "n_prompts": n_prompts,
        }

    # -- Trajectory log-prob -------------------------------------------------

    def _trajectory_logprob(
        self,
        token_ids: List[int],
        assistant_mask: List[int],
        *,
        ref: bool,
    ) -> "torch.Tensor":
        """Sum of per-token log-probs over the assistant-masked positions.

        ``token_ids`` is the full trajectory (prompt + observation + assistant
        tokens interleaved over turns); ``assistant_mask[i] == 1`` iff token
        ``i`` was generated by the policy. We run the model once over the whole
        sequence and accumulate ``log p(token_{i} | token_{<i})`` only where the
        *predicted* token (position ``i``) is masked 1.

        ``ref=True`` → frozen reference model, no grad; else current policy with
        grad. Mirrors the single-turn log-prob math the old code used, lifted to
        the masked multi-turn trajectory.
        """
        model = self.ref_policy.model if ref else self.policy.model
        ids = torch.tensor([token_ids], device=self.device)

        if ref:
            ctx = torch.no_grad()
        else:
            ctx = torch.enable_grad()
        with ctx:
            logits = model(input_ids=ids).logits

        lps = []
        # Predict token i from logits at position i-1; include it iff token i is
        # an assistant-generated token.
        for i in range(1, len(token_ids)):
            if assistant_mask[i] != 1:
                continue
            lp = F.log_softmax(logits[0, i - 1, :], dim=-1)[token_ids[i]]
            lps.append(lp)

        if not lps:
            return torch.tensor(0.0, device=self.device)
        return torch.stack(lps).sum()

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
    "RolloutRecord",
]
