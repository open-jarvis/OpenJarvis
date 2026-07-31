"""Deterministic conflict detection that preserves every proposition."""

from __future__ import annotations

from itertools import combinations

from openjarvis.learning.candidates.models import (
    ConflictLink,
    ConflictPriority,
    ConflictType,
    FactContent,
    FailurePatternContent,
    LearningCandidate,
    RoutingRuleContent,
    SkillCandidateContent,
    SuccessfulSolutionContent,
    UserCorrectionContent,
)
from openjarvis.learning.candidates.signatures import stable_digest


def _relation(
    left: LearningCandidate,
    right: LearningCandidate,
) -> tuple[ConflictType, str] | None:
    left_content = left.structured_content
    right_content = right.structured_content
    if left.conflict_signature == right.conflict_signature:
        if isinstance(left_content, FactContent) and isinstance(
            right_content, FactContent
        ):
            if left_content.value != right_content.value:
                return ConflictType.FACT_VALUE, "different values for one fact"
        if isinstance(left_content, RoutingRuleContent) and isinstance(
            right_content, RoutingRuleContent
        ):
            if left_content.recommended_route != right_content.recommended_route:
                return ConflictType.ROUTING_ROUTE, "different routes for one condition"
        if isinstance(left_content, SkillCandidateContent) and isinstance(
            right_content, SkillCandidateContent
        ):
            if left.duplicate_signature != right.duplicate_signature:
                return ConflictType.SKILL_CONTRACT, "incompatible skill contracts"
        solution_and_failure = (
            isinstance(left_content, SuccessfulSolutionContent)
            and isinstance(right_content, FailurePatternContent)
        ) or (
            isinstance(left_content, FailurePatternContent)
            and isinstance(right_content, SuccessfulSolutionContent)
        )
        if solution_and_failure:
            return (
                ConflictType.SOLUTION_FAILURE,
                "success and failure evidence for one task type",
            )
        if left.risk_level != right.risk_level:
            return (
                ConflictType.SAFETY_BOUNDARY,
                "different risk boundaries for one proposition",
            )
    return None


def _correction_relation(
    left: LearningCandidate,
    right: LearningCandidate,
) -> tuple[LearningCandidate, LearningCandidate] | None:
    for correction, target in ((left, right), (right, left)):
        content = correction.structured_content
        if not isinstance(content, UserCorrectionContent):
            continue
        target_references = {
            target.candidate_id,
            target.duplicate_signature,
            target.conflict_signature,
        }
        if content.target_reference in target_references:
            return correction, target
    return None


def detect_conflicts(
    candidates: tuple[LearningCandidate, ...],
) -> tuple[ConflictLink, ...]:
    """Return stable links without selecting, deleting, or activating candidates."""

    links: list[ConflictLink] = []
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            candidate.duplicate_signature,
            candidate.content_hash,
            candidate.candidate_id,
        ),
    )
    for left, right in combinations(ordered, 2):
        if left.duplicate_signature == right.duplicate_signature:
            continue
        correction_relation = _correction_relation(left, right)
        if correction_relation is not None:
            correction, _target = correction_relation
            conflict_type = ConflictType.USER_CORRECTION
            reason = "explicit user correction targets another candidate"
            priority = ConflictPriority.USER_CORRECTION
            preferred_candidate_id = correction.candidate_id
        else:
            relation = _relation(left, right)
            if relation is None:
                continue
            conflict_type, reason = relation
            priority = ConflictPriority.NONE
            preferred_candidate_id = None

        duplicate_signatures = tuple(
            sorted((left.duplicate_signature, right.duplicate_signature))
        )
        conflict_signature = stable_digest(
            {
                "type": conflict_type.value,
                "candidate_duplicate_signatures": duplicate_signatures,
            }
        )
        links.append(
            ConflictLink(
                conflict_id=f"conflict_{conflict_signature[:24]}",
                conflict_type=conflict_type,
                conflict_signature=conflict_signature,
                candidate_ids=(left.candidate_id, right.candidate_id),
                candidate_duplicate_signatures=duplicate_signatures,
                priority=priority,
                preferred_candidate_id=preferred_candidate_id,
                reason=reason,
            )
        )
    return tuple(sorted(links, key=lambda link: link.conflict_id))


__all__ = ["detect_conflicts"]
