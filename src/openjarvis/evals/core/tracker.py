"""ResultTracker ABC for external experiment tracking."""

from __future__ import annotations

from abc import ABC, abstractmethod

from openjarvis.evals.core.types import EvalResult, RunConfig, RunSummary


class ResultTracker(ABC):
    """Abstract base class for experiment result trackers.

    Lifecycle: on_run_start -> on_result (per sample)
    -> on_summary -> on_run_end.
    """

    @abstractmethod
    def on_run_start(self, config: RunConfig) -> None:
        """Called once before evaluation begins."""

    @abstractmethod
    def on_result(self, result: EvalResult, config: RunConfig) -> None:
        """Called after each sample is evaluated."""

    @abstractmethod
    def on_summary(self, summary: RunSummary) -> None:
        """Called after all samples are evaluated with aggregate stats."""

    @abstractmethod
    def on_run_end(self) -> None:
        """Called at the very end of a run for cleanup."""


__all__ = ["ResultTracker"]
