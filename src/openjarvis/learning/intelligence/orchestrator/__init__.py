"""Orchestrator training infrastructure — SFT and GRPO pipelines.

Provides structured-mode training for the OrchestratorAgent with:

- **Episode types**: Action, Observation, Episode, EpisodeState
- **Reward**: Multi-objective reward balancing accuracy, cost, energy, latency, power
- **Prompt registry**: Canonical system prompts for structured mode
- **Policy model**: HuggingFace LM wrapper for action prediction
- **Environment**: RL environment using OpenJarvis ToolExecutor
- **SFT trainer**: Supervised fine-tuning on successful trajectories
- **GRPO trainer**: Group Relative Policy Optimization

Importing this module triggers registration of ``orchestrator_sft`` and
``orchestrator_grpo`` in :class:`~openjarvis.core.registry.LearningRegistry`.
"""

from openjarvis.learning.intelligence.orchestrator.environment import (
    OrchestratorEnvironment,
)
from openjarvis.learning.intelligence.orchestrator.grpo_trainer import (
    OrchestratorGRPOConfig,
    OrchestratorGRPOTrainer,
)
from openjarvis.learning.intelligence.orchestrator.policy_model import (
    OrchestratorPolicyModel,
)
from openjarvis.learning.intelligence.orchestrator.prompt_registry import (
    TOOL_DESCRIPTIONS,
    build_system_prompt,
)
from openjarvis.learning.intelligence.orchestrator.reward import (
    AdaptiveRewardWeights,
    MultiObjectiveReward,
    Normalizers,
    RewardWeights,
)
from openjarvis.learning.intelligence.orchestrator.sft_trainer import (
    OrchestratorSFTConfig,
    OrchestratorSFTDataset,
    OrchestratorSFTTrainer,
    _select_torch_device,
)
from openjarvis.learning.intelligence.orchestrator.types import (
    Episode,
    EpisodeState,
    EpisodeStep,
    OrchestratorAction,
    OrchestratorObservation,
    PolicyOutput,
    extract_answer,
    grade_answer,
    normalize_number,
)

__all__ = [
    # Types
    "Episode",
    "EpisodeState",
    "EpisodeStep",
    "OrchestratorAction",
    "OrchestratorObservation",
    "PolicyOutput",
    "extract_answer",
    "grade_answer",
    "normalize_number",
    # Reward
    "AdaptiveRewardWeights",
    "MultiObjectiveReward",
    "Normalizers",
    "RewardWeights",
    # Prompt
    "TOOL_DESCRIPTIONS",
    "build_system_prompt",
    # Policy
    "OrchestratorPolicyModel",
    # Environment
    "OrchestratorEnvironment",
    # SFT
    "OrchestratorSFTConfig",
    "OrchestratorSFTDataset",
    "OrchestratorSFTTrainer",
    # Device selection
    "_select_torch_device",
    # GRPO
    "OrchestratorGRPOConfig",
    "OrchestratorGRPOTrainer",
]
