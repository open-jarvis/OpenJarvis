"""Pure candidate review-state transition rules."""

from __future__ import annotations

from openjarvis.learning.candidates.models import (
    CandidateState,
    LearningCandidate,
    QuarantineReason,
)
from openjarvis.learning.lifecycle.models import ActorType, TransitionRequest


class TransitionDeniedError(ValueError):
    """Raised when a requested review transition violates the closed graph."""


ALLOWED_TRANSITIONS = {
    CandidateState.PROPOSED: frozenset(
        {
            CandidateState.UNDER_REVIEW,
            CandidateState.REJECTED,
            CandidateState.QUARANTINED,
        }
    ),
    CandidateState.UNDER_REVIEW: frozenset(
        {CandidateState.REJECTED, CandidateState.QUARANTINED}
    ),
    CandidateState.QUARANTINED: frozenset(
        {CandidateState.UNDER_REVIEW, CandidateState.REJECTED}
    ),
    CandidateState.REJECTED: frozenset(),
}


def validate_transition(
    current: LearningCandidate,
    request: TransitionRequest,
    *,
    has_open_conflict: bool,
) -> None:
    if request.target_state not in ALLOWED_TRANSITIONS[current.state]:
        raise TransitionDeniedError(
            f"transition {current.state.value}->{request.target_state.value} is denied"
        )
    if request.target_state is not CandidateState.UNDER_REVIEW or (
        current.state is not CandidateState.QUARANTINED
    ):
        if request.quarantine_resolution_records:
            raise TransitionDeniedError(
                "resolution records are only valid for quarantine review"
            )
        return

    if request.actor_type not in {
        ActorType.USER,
        ActorType.SYSTEM_POLICY,
        ActorType.DETERMINISTIC_TEST,
    }:
        raise TransitionDeniedError("actor cannot resolve quarantine")
    existing = set(current.quarantine_reasons)
    resolved = {
        record.quarantine_reason for record in request.quarantine_resolution_records
    }
    if existing != resolved:
        raise TransitionDeniedError("every quarantine reason must be resolved exactly")
    if QuarantineReason.MANIPULATED_EVALUATION in existing:
        raise TransitionDeniedError("manipulated evaluations cannot be resolved")
    if has_open_conflict:
        raise TransitionDeniedError("open conflict links prevent quarantine resolution")


__all__ = ["ALLOWED_TRANSITIONS", "TransitionDeniedError", "validate_transition"]
