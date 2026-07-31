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
        {
            CandidateState.TESTING,
            CandidateState.REJECTED,
            CandidateState.QUARANTINED,
        }
    ),
    CandidateState.TESTING: frozenset(
        {
            CandidateState.VERIFIED,
            CandidateState.VERIFICATION_FAILED,
            CandidateState.QUARANTINED,
        }
    ),
    CandidateState.VERIFICATION_FAILED: frozenset(
        {
            CandidateState.UNDER_REVIEW,
            CandidateState.REJECTED,
            CandidateState.QUARANTINED,
        }
    ),
    CandidateState.VERIFIED: frozenset(
        {CandidateState.PROMOTION_PENDING, CandidateState.QUARANTINED}
    ),
    CandidateState.PROMOTION_PENDING: frozenset(
        {
            CandidateState.PROMOTED,
            CandidateState.REJECTED,
            CandidateState.QUARANTINED,
        }
    ),
    CandidateState.PROMOTED: frozenset(
        {CandidateState.ACTIVE, CandidateState.DEPRECATED, CandidateState.QUARANTINED}
    ),
    CandidateState.ACTIVE: frozenset(
        {
            CandidateState.DEPRECATED,
            CandidateState.ROLLED_BACK,
            CandidateState.QUARANTINED,
        }
    ),
    # A deprecated skill stays unselectable.  The controlled rollback service is
    # the sole caller allowed to reactivate it, and must atomically persist the
    # rollback, activation, healthcheck, evidence and scope-CAS records.
    CandidateState.DEPRECATED: frozenset({CandidateState.ACTIVE}),
    CandidateState.ROLLED_BACK: frozenset(),
    CandidateState.QUARANTINED: frozenset(
        {
            CandidateState.UNDER_REVIEW,
            CandidateState.REJECTED,
            CandidateState.DEPRECATED,
        }
    ),
    CandidateState.REJECTED: frozenset(),
}


def validate_transition(
    current: LearningCandidate,
    request: TransitionRequest,
    *,
    has_open_conflict: bool,
    skill_lifecycle_authorized: bool = False,
    resolving_conflict: bool = False,
) -> None:
    privileged_targets = {
        CandidateState.TESTING,
        CandidateState.VERIFICATION_FAILED,
        CandidateState.VERIFIED,
        CandidateState.PROMOTION_PENDING,
        CandidateState.PROMOTED,
        CandidateState.ACTIVE,
        CandidateState.DEPRECATED,
        CandidateState.ROLLED_BACK,
    }
    privileged_sources = {
        CandidateState.TESTING,
        CandidateState.VERIFICATION_FAILED,
        CandidateState.VERIFIED,
        CandidateState.PROMOTION_PENDING,
        CandidateState.PROMOTED,
        CandidateState.ACTIVE,
    }
    if request.target_state in privileged_targets and not skill_lifecycle_authorized:
        raise TransitionDeniedError(
            "skill lifecycle transition requires the controlled skill service"
        )
    if current.state in privileged_sources and not skill_lifecycle_authorized:
        raise TransitionDeniedError(
            "skill lifecycle source requires the controlled skill service"
        )
    if request.target_state in privileged_targets:
        if request.skill_lifecycle_record_id is None:
            raise TransitionDeniedError("skill lifecycle record is required")
        if not request.evidence_reference_ids:
            raise TransitionDeniedError("skill lifecycle evidence is required")
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
    if has_open_conflict and not resolving_conflict:
        raise TransitionDeniedError("open conflict links prevent quarantine resolution")


__all__ = ["ALLOWED_TRANSITIONS", "TransitionDeniedError", "validate_transition"]
