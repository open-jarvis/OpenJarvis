"""Narrow application service for explicit candidate review actions."""

from __future__ import annotations

from openjarvis.learning.lifecycle.models import TransitionOutcome, TransitionRequest
from openjarvis.learning.store.repository import LearningRepository


class CandidateLifecycleService:
    """Apply one validated transition through the transactional repository."""

    def __init__(self, repository: LearningRepository) -> None:
        self.repository = repository

    def transition(self, request: TransitionRequest) -> TransitionOutcome:
        return self.repository.transition(request)


__all__ = ["CandidateLifecycleService"]
