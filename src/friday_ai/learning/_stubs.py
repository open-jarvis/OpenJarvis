"""Learning primitive ABCs -- router policies, reward functions, learning policies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar, Dict

from friday_ai.core.registry import LearningRegistry  # noqa: F401

# Re-export from canonical location for backward compatibility
from friday_ai.core.types import RoutingContext  # noqa: F401

if TYPE_CHECKING:
    pass


class RouterPolicy(ABC):
    """Model selection policy (used by the learning system)."""

    @abstractmethod
    def select_model(self, context: "RoutingContext") -> str:
        """Select the best model key for the given routing context."""


class QueryAnalyzer(ABC):
    """Query analysis for routing contexts."""

    @abstractmethod
    def analyze(self, query: str, **kwargs: object) -> "RoutingContext":
        """Analyze a query and return a RoutingContext."""


class RewardFunction(ABC):
    """Compute a scalar reward for a routing decision."""

    @abstractmethod
    def compute(
        self,
        context: "RoutingContext",
        model_key: str,
        response: str,
        **kwargs: object,
    ) -> float:
        """Return reward in [0, 1]."""


class LearningPolicy(ABC):
    """Base for all learning policies. Targets one or more primitives."""

    target: ClassVar[str] = ""  # "intelligence" | "agent"

    @abstractmethod
    def update(self, trace_store: Any, **kwargs: object) -> Dict[str, Any]:
        """Analyze traces and return update actions."""


class IntelligenceLearningPolicy(LearningPolicy):
    """Updates intelligence (model routing) from traces."""

    target: ClassVar[str] = "intelligence"


class AgentLearningPolicy(LearningPolicy):
    """Updates agent logic from traces."""

    target: ClassVar[str] = "agent"


__all__ = [
    "AgentLearningPolicy",
    "IntelligenceLearningPolicy",
    "LearningPolicy",
    "LearningRegistry",
    "QueryAnalyzer",
    "RewardFunction",
    "RouterPolicy",
    "RoutingContext",
]
