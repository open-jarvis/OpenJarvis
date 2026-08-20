"""Abstract base class for inference backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class InferenceBackend(ABC):
    """Base class for all inference backends used in evaluation."""

    backend_id: str
    # Default framework label used when an EvalResult is constructed in an
    # error path before the backend's generate_full() has returned a payload
    # to read ``framework`` from. Each subclass must override this so that
    # error-path results are tagged with the correct framework name.
    framework_name: str = "openjarvis"

    @property
    def framework_commit_value(self) -> str:
        """Default: empty (subclasses override). Used by runner.py error paths."""
        return ""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """Generate a response and return just the text content."""

    @abstractmethod
    def generate_full(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """Generate a response and return full details.

        Returns dict with keys: content, usage, model, latency_seconds, cost_usd.
        """

    def close(self) -> None:
        """Release resources."""


__all__ = ["InferenceBackend"]
