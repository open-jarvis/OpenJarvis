"""Tests for orchestrator GRPO trainer."""

from __future__ import annotations

from openjarvis.learning.intelligence.orchestrator.grpo_trainer import (
    OrchestratorGRPOConfig,
)
from openjarvis.learning.intelligence.orchestrator.types import Episode


class TestOrchestratorGRPOConfig:
    def test_defaults(self):
        cfg = OrchestratorGRPOConfig()
        assert cfg.model_name == "Qwen/Qwen3-1.7B"
        assert cfg.num_epochs == 10
        assert cfg.batch_size == 16
        assert cfg.num_samples_per_prompt == 8
        assert cfg.kl_coef == 0.0001
        assert cfg.clip_ratio == 0.2
        assert cfg.gradient_checkpointing is True
        assert cfg.use_8bit_ref is True

    def test_custom_values(self):
        cfg = OrchestratorGRPOConfig(
            model_name="test-model",
            num_samples_per_prompt=4,
            kl_coef=0.01,
        )
        assert cfg.model_name == "test-model"
        assert cfg.num_samples_per_prompt == 4
        assert cfg.kl_coef == 0.01

    def test_default_tools(self):
        cfg = OrchestratorGRPOConfig()
        assert "calculator" in cfg.available_tools
        assert "think" in cfg.available_tools


class TestGroupAdvantageNormalization:
    """Test the math behind group-relative advantage normalization."""

    def test_uniform_rewards_zero_advantages(self):
        rewards = [0.5, 0.5, 0.5, 0.5]
        mean_r = sum(rewards) / len(rewards)
        std_r = (sum((r - mean_r) ** 2 for r in rewards) / len(rewards)) ** 0.5
        # All same → std=0 → advantages should be 0
        assert std_r < 1e-8
        advantages = [0.0] * len(rewards)
        assert all(a == 0.0 for a in advantages)

    def test_varied_rewards_normalized(self):
        rewards = [0.1, 0.3, 0.5, 0.7]
        mean_r = sum(rewards) / len(rewards)
        std_r = (sum((r - mean_r) ** 2 for r in rewards) / len(rewards)) ** 0.5
        advantages = [(r - mean_r) / std_r for r in rewards]
        # Mean of advantages should be ~0
        assert abs(sum(advantages) / len(advantages)) < 1e-6
        # Std should be ~1
        adv_mean = sum(advantages) / len(advantages)
        adv_std = (
            sum((a - adv_mean) ** 2 for a in advantages) / len(advantages)
        ) ** 0.5
        assert abs(adv_std - 1.0) < 1e-6

    def test_best_gets_positive_advantage(self):
        rewards = [0.1, 0.9, 0.3, 0.5]
        mean_r = sum(rewards) / len(rewards)
        std_r = (sum((r - mean_r) ** 2 for r in rewards) / len(rewards)) ** 0.5
        advantages = [(r - mean_r) / std_r for r in rewards]
        # Index 1 (reward=0.9) should have highest advantage
        assert advantages[1] == max(advantages)
        assert advantages[1] > 0


class TestRewardIntegration:
    def test_episode_reward(self):
        from openjarvis.learning.intelligence.orchestrator.reward import (
            MultiObjectiveReward,
            Normalizers,
            RewardWeights,
        )

        reward_fn = MultiObjectiveReward(RewardWeights(), Normalizers())
        ep = Episode(
            task_id="t",
            initial_prompt="q",
            correct=True,
            total_energy_joules=10.0,
            total_cost_usd=0.01,
            total_latency_seconds=1.0,
            max_power_watts=50.0,
        )
        r = reward_fn.compute(ep)
        assert isinstance(r, float)
        assert r > 0  # correct episode


class TestGRPORegistration:
    def test_registered_in_learning_registry(self):
        import openjarvis.learning.intelligence.orchestrator.grpo_trainer  # noqa: F401
        from openjarvis.core.registry import LearningRegistry

        assert LearningRegistry.contains("orchestrator_grpo")
