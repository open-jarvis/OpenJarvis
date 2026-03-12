"""Learning primitive — router policies, reward functions, and trace-driven learning."""

from __future__ import annotations

from openjarvis.learning._stubs import (
    QueryAnalyzer,
    RewardFunction,
    RouterPolicy,
    RoutingContext,
)
from openjarvis.learning.agent_evolver import AgentConfigEvolver
from openjarvis.learning.routing.heuristic_reward import HeuristicRewardFunction
from openjarvis.learning.learning_orchestrator import LearningOrchestrator
from openjarvis.learning.optimize.llm_optimizer import LLMOptimizer
from openjarvis.learning.optimize.optimizer import OptimizationEngine
from openjarvis.learning.optimize.store import OptimizationStore
from openjarvis.learning.routing.router import (
    HeuristicRouter,
    build_routing_context,
)
from openjarvis.learning.training.data import TrainingDataMiner
from openjarvis.learning.training.lora import HAS_TORCH, LoRATrainer, LoRATrainingConfig


def ensure_registered() -> None:
    """Ensure all learning policies are registered in RouterPolicyRegistry.

    Imported lazily to avoid circular imports with the intelligence primitive.
    """
    from openjarvis.learning.routing.heuristic_policy import (
        ensure_registered as _reg_heuristic,
    )

    _reg_heuristic()

    try:
        from openjarvis.learning.grpo_policy import (
            ensure_registered as _reg_grpo,
        )

        _reg_grpo()
    except ImportError:
        pass

    try:
        from openjarvis.learning.bandit_router import (
            ensure_registered as _reg_bandit,
        )

        _reg_bandit()
    except ImportError:
        pass

    from openjarvis.learning.trace_policy import (
        ensure_registered as _reg_trace,
    )

    _reg_trace()

    try:
        import openjarvis.learning.sft_policy  # noqa: F401
    except ImportError:
        pass

    try:
        import openjarvis.learning.agent_advisor  # noqa: F401
    except ImportError:
        pass

    try:
        import openjarvis.learning.icl_updater  # noqa: F401
    except ImportError:
        pass

    # Orchestrator-native SFT & GRPO training
    try:
        import openjarvis.learning.orchestrator  # noqa: F401
    except ImportError:
        pass


__all__ = [
    "AgentConfigEvolver",
    "HAS_TORCH",
    "HeuristicRewardFunction",
    "HeuristicRouter",
    "LLMOptimizer",
    "LearningOrchestrator",
    "LoRATrainer",
    "LoRATrainingConfig",
    "OptimizationEngine",
    "OptimizationStore",
    "QueryAnalyzer",
    "RewardFunction",
    "RouterPolicy",
    "RoutingContext",
    "TrainingDataMiner",
    "build_routing_context",
    "ensure_registered",
]
