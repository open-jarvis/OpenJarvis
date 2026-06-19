"""Offline (no-GPU) tests for OrchestratorGRPOTrainer._train_epoch.

We never touch torch/model/network: ``load_grpo_prompts`` is monkeypatched
to return a handful of fake Tasks, and ``_grpo_step`` is monkeypatched to
return canned metrics. The test asserts ``_train_epoch`` chunks the prompt
pool correctly and aggregates per-chunk metrics.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import openjarvis.learning.intelligence.orchestrator.policy_model as policy_model_mod
import openjarvis.learning.intelligence.orchestrator.sft_data.datasets as datasets
from openjarvis.learning.intelligence.orchestrator.grpo_trainer import (
    OrchestratorGRPOConfig,
    OrchestratorGRPOTrainer,
    RolloutRecord,
)
from openjarvis.learning.intelligence.orchestrator.policy_model import (
    OrchestratorPolicyModel,
)


@dataclass
class FakeTask:
    task_id: str
    question: str
    answer: str
    domain: str = "math"

    @property
    def instruction(self) -> str:
        return self.question


def _make_tasks(n: int):
    return [
        FakeTask(task_id=f"t{i}", question=f"q{i}", answer=str(i))
        for i in range(n)
    ]


def _build_trainer(monkeypatch, n_prompts: int, prompts_per_step: int):
    """Build a trainer with no real model and patched data loading.

    ``from_pretrained`` is stubbed to a model-less policy so construction
    touches no GPU / network even when torch happens to be installed.
    """
    tasks = _make_tasks(n_prompts)
    monkeypatch.setattr(datasets, "load_grpo_prompts", lambda *a, **k: tasks)
    monkeypatch.setattr(
        policy_model_mod.OrchestratorPolicyModel,
        "from_pretrained",
        classmethod(lambda cls, *a, **k: OrchestratorPolicyModel(model=None)),
    )

    cfg = OrchestratorGRPOConfig(
        grpo_max_prompts=n_prompts,
        prompts_per_step=prompts_per_step,
        num_samples_per_prompt=2,
    )
    trainer = OrchestratorGRPOTrainer(cfg)
    return trainer, tasks


def test_train_epoch_chunks_and_aggregates(monkeypatch):
    trainer, tasks = _build_trainer(monkeypatch, n_prompts=10, prompts_per_step=4)

    calls = []

    def fake_step(chunk):
        calls.append(len(chunk))
        return {
            "loss": 1.0,
            "reward": 0.5,
            "accuracy": 1.0,
            "n_prompts": len(chunk),
        }

    monkeypatch.setattr(trainer, "_grpo_step", fake_step)

    metrics = trainer._train_epoch(epoch=0)

    # 10 prompts / 4 per step => chunks of [4, 4, 2]
    assert calls == [4, 4, 2]
    assert metrics["n_batches"] == 3
    assert metrics["n_prompts"] == 10
    # Weighted means: all chunks report the same per-prompt values.
    assert abs(metrics["loss"] - 1.0) < 1e-9
    assert abs(metrics["reward"] - 0.5) < 1e-9
    assert abs(metrics["accuracy"] - 1.0) < 1e-9
    assert metrics["epoch"] == 0


def test_train_epoch_exact_division(monkeypatch):
    trainer, _ = _build_trainer(monkeypatch, n_prompts=8, prompts_per_step=4)
    chunks = []
    monkeypatch.setattr(
        trainer,
        "_grpo_step",
        lambda chunk: (
            chunks.append(len(chunk)),
            {"loss": 0.0, "reward": 0.0, "accuracy": 0.0, "n_prompts": len(chunk)},
        )[1],
    )
    metrics = trainer._train_epoch(epoch=2)
    assert chunks == [4, 4]
    assert metrics["n_batches"] == 2
    assert metrics["n_prompts"] == 8
    assert metrics["epoch"] == 2


def test_train_epoch_weighted_mean(monkeypatch):
    trainer, _ = _build_trainer(monkeypatch, n_prompts=6, prompts_per_step=4)

    # First chunk (4 prompts) reward=1.0, second chunk (2 prompts) reward=0.0
    seq = iter([1.0, 0.0])

    def fake_step(chunk):
        return {
            "loss": 0.0,
            "reward": next(seq),
            "accuracy": 0.0,
            "n_prompts": len(chunk),
        }

    monkeypatch.setattr(trainer, "_grpo_step", fake_step)
    metrics = trainer._train_epoch(epoch=0)
    # weighted: (1.0*4 + 0.0*2) / 6 = 0.6667
    assert abs(metrics["reward"] - (4.0 / 6.0)) < 1e-9


def test_prompts_cached(monkeypatch):
    trainer, _ = _build_trainer(monkeypatch, n_prompts=4, prompts_per_step=4)
    n_loads = {"count": 0}

    orig = datasets.load_grpo_prompts

    def counting(*a, **k):
        n_loads["count"] += 1
        return orig(*a, **k)

    monkeypatch.setattr(datasets, "load_grpo_prompts", counting)
    monkeypatch.setattr(
        trainer,
        "_grpo_step",
        lambda chunk: {"loss": 0.0, "reward": 0.0, "accuracy": 0.0, "n_prompts": len(chunk)},
    )
    trainer._train_epoch(epoch=0)
    trainer._train_epoch(epoch=1)
    # Loaded once, cached on the trainer thereafter.
    assert n_loads["count"] == 1


def test_train_epoch_no_model_still_iterates(monkeypatch):
    """Even with policy.model None (no GPU), epoch iterates via _grpo_step."""
    trainer, _ = _build_trainer(monkeypatch, n_prompts=5, prompts_per_step=2)
    assert trainer.policy.model is None  # CPU/no-torch stub
    called = {"n": 0}

    def fake_step(chunk):
        called["n"] += 1
        return {"loss": 0.0, "reward": 0.0, "accuracy": 0.0, "n_prompts": len(chunk)}

    monkeypatch.setattr(trainer, "_grpo_step", fake_step)
    metrics = trainer._train_epoch(epoch=0)
    assert called["n"] == 3  # [2, 2, 1]
    assert metrics["n_prompts"] == 5


# ---------------------------------------------------------------------------
# _grpo_step over the unified rollout (offline, fake model + patched paths)
# ---------------------------------------------------------------------------


torch = pytest.importorskip("torch")


class _FakeModel:
    """Stand-in for the HF policy/ref model: trainable enough to backprop.

    ``parameters()`` returns no params so the NaN-grad scan and
    ``clip_grad_norm_`` are no-ops; ``train()`` is a no-op. The real
    log-prob / generation paths are monkeypatched, so the model is never
    actually called.
    """

    def parameters(self):
        return iter(())

    def train(self):
        return self


class _FakeOptimizer:
    def zero_grad(self):
        pass

    def step(self):
        pass


def _build_step_trainer(monkeypatch, *, group_size=4):
    """Trainer wired for a CPU ``_grpo_step`` run: fake model + optimizer,
    device='cpu', and the rollout/logprob paths left for the test to patch.
    """
    tasks = _make_tasks(3)
    monkeypatch.setattr(datasets, "load_grpo_prompts", lambda *a, **k: tasks)
    monkeypatch.setattr(
        policy_model_mod.OrchestratorPolicyModel,
        "from_pretrained",
        classmethod(lambda cls, *a, **k: OrchestratorPolicyModel(model=None)),
    )
    cfg = OrchestratorGRPOConfig(
        grpo_max_prompts=3,
        prompts_per_step=3,
        num_samples_per_prompt=group_size,
    )
    trainer = OrchestratorGRPOTrainer(cfg)
    # Make it look like a real (CPU) training setup.
    trainer.policy.model = _FakeModel()
    trainer.ref_policy.model = _FakeModel()
    trainer.optimizer = _FakeOptimizer()
    trainer.device = torch.device("cpu")
    return trainer, tasks


def test_grpo_step_uses_unified_rollout_not_old_env(monkeypatch):
    """_grpo_step samples groups via the policy rollout caller, normalises
    advantages within the group, and never touches the old
    THOUGHT/TOOL/INPUT environment path."""

    # Tripwire: the old environment generation path must NOT be invoked.
    import openjarvis.learning.intelligence.orchestrator.policy_model as pm

    def _boom(*a, **k):  # pragma: no cover - only fires on regression
        raise AssertionError(
            "GRPO generation hit the old THOUGHT/TOOL/INPUT path "
            "(policy_model._parse_output / predict_action)"
        )

    monkeypatch.setattr(pm.OrchestratorPolicyModel, "_parse_output", _boom)
    monkeypatch.setattr(pm.OrchestratorPolicyModel, "predict_action", _boom)
    monkeypatch.setattr(pm.OrchestratorPolicyModel, "_build_prompt", _boom)

    trainer, tasks = _build_step_trainer(monkeypatch, group_size=4)

    # verify_answer: even-indexed rollouts correct, odd incorrect -> spread of
    # rewards inside each group so std > 0 and advantages get normalised.
    import openjarvis.learning.intelligence.orchestrator.sft_data.verify as verify_mod

    seen_answers = []

    def fake_verify(task, pred):
        seen_answers.append(pred)
        return pred.endswith("correct")

    monkeypatch.setattr(verify_mod, "verify_answer", fake_verify)

    def fake_rollout_group(task):
        recs = []
        for i in range(trainer.config.num_samples_per_prompt):
            ans = f"ans-{i}-correct" if i % 2 == 0 else f"ans-{i}-wrong"
            recs.append(
                RolloutRecord(
                    final_answer=ans,
                    cost_usd=0.01 * (i + 1),
                    token_ids=[1, 2, 3, 4],
                    assistant_mask=[0, 1, 0, 1],
                )
            )
        return recs

    monkeypatch.setattr(trainer, "_rollout_group", fake_rollout_group)

    def fake_logprob(token_ids, assistant_mask, *, ref):
        # token_ids/mask flow through unchanged from the records.
        assert token_ids == [1, 2, 3, 4]
        assert assistant_mask == [0, 1, 0, 1]
        # Distinct, grad-bearing values for current vs ref so the ratio is
        # finite and backward() builds a real graph.
        base = -1.0 if ref else -0.9
        return torch.tensor(base, requires_grad=not ref)

    monkeypatch.setattr(trainer, "_trajectory_logprob", fake_logprob)

    metrics = trainer._grpo_step(tasks)

    # Metrics aggregate over the 3 tasks.
    assert metrics["n_prompts"] == 3
    # Half of each group is correct -> accuracy 0.5.
    assert abs(metrics["accuracy"] - 0.5) < 1e-9
    assert "loss" in metrics and "reward" in metrics
    # The unified-rollout caller produced our canned answers (proves we went
    # through the rollout path, not the old env).
    assert any(a.endswith("correct") for a in seen_answers)
    assert any(a.endswith("wrong") for a in seen_answers)


def test_grpo_step_group_normalised_advantages(monkeypatch):
    """Advantages within a group are mean-0 / std-1 (group-relative)."""
    trainer, tasks = _build_step_trainer(monkeypatch, group_size=4)

    import openjarvis.learning.intelligence.orchestrator.sft_data.verify as verify_mod

    monkeypatch.setattr(
        verify_mod, "verify_answer", lambda task, pred: pred == "good"
    )

    all_groups = []

    def fake_rollout_group(task):
        # 2 correct, 2 wrong, varied costs -> non-degenerate reward spread.
        answers = ["good", "good", "bad", "bad"]
        recs = [
            RolloutRecord(
                final_answer=answers[i],
                cost_usd=0.0,
                token_ids=[5, 6, 7],
                assistant_mask=[0, 1, 1],
            )
            for i in range(4)
        ]
        all_groups.append(recs)
        return recs

    monkeypatch.setattr(trainer, "_rollout_group", fake_rollout_group)

    def fake_logprob(token_ids, assistant_mask, *, ref):
        return torch.tensor(0.0, requires_grad=not ref)

    monkeypatch.setattr(trainer, "_trajectory_logprob", fake_logprob)

    trainer._grpo_step(tasks)

    # 3 tasks, each a group of 4. Read the advantages _grpo_step stamped onto
    # each record; every group must be group-normalised (mean ~0, std ~1).
    assert len(all_groups) == 3
    for recs in all_groups:
        group = [r.advantage for r in recs]
        assert len(group) == 4
        mean = sum(group) / 4
        assert abs(mean) < 1e-6
        var = sum((x - mean) ** 2 for x in group) / 4
        assert abs(var - 1.0) < 1e-6


def test_stitch_trajectory_assistant_mask():
    """Stitching per-turn (prompt_ids, gen_ids) yields a correct mask: 1 only
    on the policy-generated tokens, growing prompts diffed across turns."""
    trainer = OrchestratorGRPOTrainer.__new__(OrchestratorGRPOTrainer)
    # Turn 1: prompt [10,11], gen [20,21]. Turn 2 prompt is the full prior
    # transcript [10,11,20,21] + a new observation token [12], gen [22].
    turn_buffer = [
        ([10, 11], [20, 21]),
        ([10, 11, 20, 21, 12], [22]),
    ]
    token_ids, mask = trainer._stitch_trajectory(turn_buffer)
    # Turn1: new prompt [10,11] mask0, gen [20,21] mask1.
    # Turn2: new prompt [12] mask0 (the [10,11,20,21] already emitted), gen [22] mask1.
    assert token_ids == [10, 11, 20, 21, 12, 22]
    assert mask == [0, 0, 1, 1, 0, 1]


def test_trajectory_logprob_masks_to_assistant_positions(monkeypatch):
    """_trajectory_logprob sums log-probs only over assistant-masked tokens,
    using logits at position i-1 to predict token i."""
    trainer = OrchestratorGRPOTrainer.__new__(OrchestratorGRPOTrainer)
    trainer.device = torch.device("cpu")

    token_ids = [3, 7, 5, 9]
    assistant_mask = [0, 1, 0, 1]  # tokens at idx 1 and 3 are assistant

    vocab = 10
    seq = len(token_ids)
    # Deterministic logits so the expected sum is computable.
    logits = torch.zeros(1, seq, vocab)
    for i in range(seq):
        logits[0, i, :] = torch.arange(vocab, dtype=torch.float32) * 0.1 * (i + 1)

    class _LogitModel:
        def __call__(self, input_ids=None):
            class _Out:
                pass

            o = _Out()
            o.logits = logits
            return o

        def parameters(self):
            return iter(())

    trainer.policy = OrchestratorPolicyModel(model=_LogitModel())
    trainer.ref_policy = OrchestratorPolicyModel(model=_LogitModel())

    out = trainer._trajectory_logprob(token_ids, assistant_mask, ref=True)

    # Expected: log_softmax(logits[i-1])[token_i] summed over masked i in {1,3}.
    expected = 0.0
    for i in range(1, seq):
        if assistant_mask[i] != 1:
            continue
        lp = torch.log_softmax(logits[0, i - 1, :], dim=-1)[token_ids[i]]
        expected += lp.item()
    assert abs(out.item() - expected) < 1e-5
