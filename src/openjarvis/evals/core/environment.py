"""Environment provider ABC for benchmarks requiring external environments."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple

from openjarvis.evals.core.types import EvalRecord


class EnvironmentProvider(ABC):
    """Manages an external environment for evaluation benchmarks.

    Provides lifecycle management (setup/reset/teardown) and
    environment-state validation for benchmarks that need
    Docker containers, ServiceNow instances, or other live systems.
    """

    @abstractmethod
    def setup(self) -> Dict[str, Any]:
        """Start the environment and return connection info.

        Returns a dict with environment-specific connection details
        (e.g., URLs, ports, credentials).
        """

    @abstractmethod
    def reset(self) -> None:
        """Reset environment state between tasks.

        Called between records within an episode to restore
        the environment to a known state.
        """

    @abstractmethod
    def validate(
        self,
        record: EvalRecord,
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check environment state against expected outcome.

        Args:
            record: The eval record containing the expected state in metadata.

        Returns:
            (is_correct, metadata) where is_correct indicates whether
            the environment is in the expected state.
        """

    @abstractmethod
    def teardown(self) -> None:
        """Stop the environment and release resources."""
