"""Evidence-bound, deterministic extraction from completed trace evaluations."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from openjarvis.learning.candidates.conflicts import detect_conflicts
from openjarvis.learning.candidates.independence import (
    group_for_feedback,
    groups_for_evaluations,
    merge_groups,
)
from openjarvis.learning.candidates.models import (
    DEFAULT_EXTRACTOR_VERSION,
    CandidateConfidenceBasis,
    CandidateContent,
    CandidateOrigin,
    CandidateScope,
    CandidateState,
    CandidateType,
    DuplicateLink,
    DuplicateReason,
    EvaluationEnvelope,
    ExplicitFeedbackRecord,
    ExtractionMethod,
    ExtractionResult,
    FactFeedbackContent,
    FailurePatternContent,
    FeedbackType,
    IndependenceGroup,
    LearningCandidate,
    MetadataReference,
    PreferenceFeedbackContent,
    ProposedDestination,
    ProvenanceEntry,
    ProvenanceSourceKind,
    QuarantineReason,
    StructuredCandidateRequest,
    SuccessfulSolutionContent,
    UserCorrectionContent,
    utc_now,
)
from openjarvis.learning.candidates.quarantine import (
    reasons_from_evaluation,
    reasons_from_request,
    scan_content,
)
from openjarvis.learning.candidates.signatures import (
    conflict_signature,
    duplicate_signature,
)
from openjarvis.learning.evaluation.models import (
    ConfidenceLevel,
    EvaluationClass,
    EvidenceState,
    EvidenceType,
    EvidenceVerificationState,
    TraceEvaluation,
    TrustedBoundary,
    VerificationState,
)
from openjarvis.tasks.policy import RiskLevel

_SUCCESS_CLASSES = {
    EvaluationClass.COMPLETED,
    EvaluationClass.COMPLETED_WITH_WARNING,
}
_TECHNICAL_FAILURE_CLASSES = {
    EvaluationClass.VERIFICATION_FAILED,
    EvaluationClass.TOOL_FAILED,
    EvaluationClass.BROWSER_FAILED,
    EvaluationClass.CONFLICTING_EVIDENCE,
}
_CONFIDENCE_ORDER = {
    ConfidenceLevel.LOW: 0,
    ConfidenceLevel.MEDIUM: 1,
    ConfidenceLevel.HIGH: 2,
}


def _build_candidate(**payload: object) -> LearningCandidate:
    for field_name in (
        "source_evaluation_ids",
        "source_task_ids",
        "source_trace_ids",
        "source_evidence_ids",
    ):
        payload[field_name] = tuple(sorted(set(payload.get(field_name, ()))))
    provenance = payload.get("provenance", ())
    provenance_by_key = {
        (item.source_kind.value, item.source_id, item.source_digest): item
        for item in provenance
    }
    payload["provenance"] = tuple(
        provenance_by_key[key] for key in sorted(provenance_by_key)
    )
    confidence_basis = payload.get("confidence_basis", ())
    payload["confidence_basis"] = tuple(
        sorted(set(confidence_basis), key=lambda item: item.value)
    )
    groups = payload.get("independence_groups", ())
    groups_by_digest = {item.group_digest: item for item in groups}
    payload["independence_groups"] = tuple(
        groups_by_digest[key] for key in sorted(groups_by_digest)
    )
    payload["independence_count"] = len(payload["independence_groups"])
    for field_name in ("proposed_tests", "proposed_verification"):
        payload[field_name] = tuple(sorted(set(payload.get(field_name, ()))))
    quarantine_reasons = payload.get("quarantine_reasons", ())
    payload["quarantine_reasons"] = tuple(
        sorted(set(quarantine_reasons), key=lambda item: item.value)
    )
    draft = LearningCandidate.model_construct(
        **payload,
        content_hash="0" * 64,
    )
    return LearningCandidate(**payload, content_hash=draft.recompute_hash())


def _replace_candidate(
    candidate: LearningCandidate,
    **changes: object,
) -> LearningCandidate:
    payload = {
        field_name: getattr(candidate, field_name)
        for field_name in type(candidate).model_fields
        if field_name != "content_hash"
    }
    payload.update(changes)
    return _build_candidate(**payload)


def _build_result(**payload: object) -> ExtractionResult:
    draft = ExtractionResult.model_construct(**payload, run_hash="0" * 64)
    return ExtractionResult(**payload, run_hash=draft.recompute_hash())


def _is_verified_success(evaluation: TraceEvaluation) -> bool:
    tools = evaluation.tool_result_summary
    return bool(
        evaluation.evaluation_class in _SUCCESS_CLASSES
        and evaluation.verification_state is VerificationState.PASSED
        and evaluation.evidence_state is EvidenceState.SUFFICIENT
        and evaluation.confidence in {ConfidenceLevel.MEDIUM, ConfidenceLevel.HIGH}
        and tools.failed == 0
        and tools.denied == 0
        and tools.canceled == 0
        and tools.pending == 0
        and tools.unknown == 0
        and tools.unknown_effects == 0
    )


def _metadata_references(
    evaluation: TraceEvaluation,
    evidence_types: set[EvidenceType],
) -> tuple[MetadataReference, ...]:
    return tuple(
        MetadataReference(
            reference_id=reference.evidence_id,
            evidence_type=reference.evidence_type,
            digest=reference.digest,
        )
        for reference in evaluation.evidence_references
        if reference.verification_state is EvidenceVerificationState.VERIFIED
        and reference.evidence_type in evidence_types
    )


def _merge_metadata_references(
    references: Iterable[MetadataReference],
) -> tuple[MetadataReference, ...]:
    by_key = {
        (reference.reference_id, reference.evidence_type.value, reference.digest): (
            reference
        )
        for reference in references
    }
    return tuple(by_key[key] for key in sorted(by_key))


def _success_content(
    evaluation: TraceEvaluation, scope: CandidateScope
) -> SuccessfulSolutionContent:
    warnings = evaluation.warnings
    if (
        evaluation.evaluation_class is EvaluationClass.COMPLETED_WITH_WARNING
        and not warnings
    ):
        warnings = ("completed with a canonical warning",)
    return SuccessfulSolutionContent(
        task_type=evaluation.task_type,
        verified_preconditions=_metadata_references(
            evaluation,
            {EvidenceType.POLICY_RESULT, EvidenceType.APPROVAL_RESULT},
        ),
        verified_steps=_metadata_references(
            evaluation,
            {
                EvidenceType.TASK_STATE,
                EvidenceType.TOOL_RESULT,
                EvidenceType.BROWSER_RECOVERY_RESULT,
                EvidenceType.BUDGET_RESULT,
            },
        ),
        verified_postconditions=_metadata_references(
            evaluation,
            {
                EvidenceType.TASK_OUTCOME,
                EvidenceType.VERIFICATION_RESULT,
                EvidenceType.ARTIFACT_DIGEST,
            },
        ),
        allowed_scope=scope,
        limitations=warnings,
    )


def _failure_content(evaluation: TraceEvaluation) -> FailurePatternContent:
    category_text = evaluation.failure_category.value.replace("_", " ")
    class_text = evaluation.evaluation_class.value.replace("_", " ")
    return FailurePatternContent(
        failure_category=evaluation.failure_category,
        task_type=evaluation.task_type,
        trigger_conditions=(f"canonical class is {class_text}",),
        observed_symptoms=(f"canonical failure category is {category_text}",),
        canonical_causes=(f"classified from {category_text} metadata",),
        excluded_causes=("untrusted legacy success hints",),
        proposed_mitigation="Review the canonical failure evidence before retrying",
        verification_requirements=("re-run deterministic trace verification",),
    )


def _evaluation_provenance(
    evaluation: TraceEvaluation,
    extractor_version: str,
    *,
    extraction_method: ExtractionMethod = ExtractionMethod.DETERMINISTIC_RULE,
) -> ProvenanceEntry:
    return ProvenanceEntry(
        source_kind=ProvenanceSourceKind.DETERMINISTIC_TRACE_EVALUATION,
        source_id=evaluation.evaluation_id,
        source_digest=evaluation.evaluation_hash,
        source_evaluation_id=evaluation.evaluation_id,
        trusted_boundary=TrustedBoundary.CANONICAL_RUNTIME,
        extraction_method=extraction_method,
        extraction_version=extractor_version,
        created_at=evaluation.created_at,
    )


def _feedback_provenance(
    record: ExplicitFeedbackRecord,
    extractor_version: str,
) -> ProvenanceEntry:
    correction = record.feedback_type is FeedbackType.USER_CORRECTION
    return ProvenanceEntry(
        source_kind=(
            ProvenanceSourceKind.EXPLICIT_USER_CORRECTION
            if correction
            else ProvenanceSourceKind.EXPLICIT_USER_FEEDBACK
        ),
        source_id=record.feedback_id,
        source_digest=record.source_digest,
        source_evaluation_id=record.source_evaluation_id,
        trusted_boundary=TrustedBoundary.EXPLICIT_USER,
        extraction_method=(
            ExtractionMethod.EXPLICIT_USER_CORRECTION
            if correction
            else ExtractionMethod.EXPLICIT_USER_FEEDBACK
        ),
        extraction_version=extractor_version,
        created_at=record.created_at,
    )


class CandidateExtractor:
    """Pure candidate extraction; it has no model, network, executor, or store."""

    def __init__(self, *, extractor_version: str = DEFAULT_EXTRACTOR_VERSION) -> None:
        self.extractor_version = extractor_version

    def extract(
        self,
        evaluations: Iterable[EvaluationEnvelope],
        *,
        feedback_records: Iterable[ExplicitFeedbackRecord] = (),
        requests: Iterable[StructuredCandidateRequest] = (),
        created_at: datetime | None = None,
    ) -> ExtractionResult:
        envelopes = tuple(
            sorted(
                evaluations,
                key=lambda item: item.evaluation.evaluation_id,
            )
        )
        feedback = tuple(sorted(feedback_records, key=lambda item: item.feedback_id))
        typed_requests = tuple(sorted(requests, key=lambda item: item.request_id))
        evaluation_by_id = {item.evaluation.evaluation_id: item for item in envelopes}
        if len(evaluation_by_id) != len(envelopes):
            raise ValueError("evaluation_id must be unique within one extraction")
        for envelope in envelopes:
            evaluation = envelope.evaluation
            if evaluation.recompute_hash() != evaluation.evaluation_hash:
                raise ValueError(
                    f"manipulated evaluation rejected: {evaluation.evaluation_id}"
                )

        group_by_evaluation = groups_for_evaluations(envelopes)
        candidates: list[LearningCandidate] = []
        warnings: list[str] = []
        for envelope in envelopes:
            candidate = self._from_evaluation(
                envelope,
                group_by_evaluation[envelope.evaluation.evaluation_id],
            )
            if candidate is None:
                warnings.append(
                    "no automatic candidate for canonical class "
                    f"{envelope.evaluation.evaluation_class.value}"
                )
            else:
                candidates.append(candidate)
        candidates.extend(self._from_feedback(record) for record in feedback)
        candidates.extend(
            self._from_request(request, evaluation_by_id, group_by_evaluation)
            for request in typed_requests
        )

        merged, duplicate_links = self._deduplicate(tuple(candidates))
        conflict_links = detect_conflicts(merged)
        conflicted_ids = {
            candidate_id
            for link in conflict_links
            for candidate_id in link.candidate_ids
        }
        final_candidates = tuple(
            self._quarantine_for_conflict(candidate)
            if candidate.candidate_id in conflicted_ids
            else candidate
            for candidate in merged
        )
        result_created_at = created_at or utc_now()
        return _build_result(
            extractor_version=self.extractor_version,
            input_evaluation_ids=tuple(evaluation_by_id),
            candidates=final_candidates,
            duplicate_links=duplicate_links,
            conflict_links=conflict_links,
            quarantined_candidate_ids=tuple(
                candidate.candidate_id
                for candidate in final_candidates
                if candidate.state is CandidateState.QUARANTINED
            ),
            warnings=tuple(warnings),
            created_at=result_created_at,
        )

    def _from_evaluation(
        self,
        envelope: EvaluationEnvelope,
        independence_group: IndependenceGroup,
    ) -> LearningCandidate | None:
        evaluation = envelope.evaluation
        if _is_verified_success(evaluation):
            content: CandidateContent = _success_content(evaluation, envelope.scope)
            candidate_type = CandidateType.SUCCESSFUL_SOLUTION
            title = f"Verified solution for {evaluation.task_type}"
            confidence_basis = (CandidateConfidenceBasis.VERIFIED_TRACE_EVALUATION,)
            destination = ProposedDestination.LEARNING_REVIEW
        elif evaluation.evaluation_class in _TECHNICAL_FAILURE_CLASSES:
            content = _failure_content(evaluation)
            candidate_type = CandidateType.FAILURE_PATTERN
            title = f"Canonical failure pattern for {evaluation.task_type}"
            confidence_basis = (
                CandidateConfidenceBasis.CONFLICTING_EVIDENCE
                if evaluation.evaluation_class is EvaluationClass.CONFLICTING_EVIDENCE
                else CandidateConfidenceBasis.VERIFIED_TRACE_EVALUATION,
            )
            destination = ProposedDestination.LEARNING_REVIEW
        else:
            return None

        evaluation_reasons = reasons_from_evaluation(evaluation)
        content_reasons = scan_content(content, title)
        reasons = tuple(
            sorted(
                set(evaluation_reasons + content_reasons), key=lambda item: item.value
            )
        )
        return self._candidate(
            candidate_type=candidate_type,
            title=title,
            content=content,
            scope=envelope.scope,
            project=envelope.project,
            origin=CandidateOrigin.AUTOMATIC_TRACE_EVALUATION,
            evaluations=(evaluation,),
            provenance=(_evaluation_provenance(evaluation, self.extractor_version),),
            confidence=evaluation.confidence,
            confidence_basis=confidence_basis,
            independence_groups=(independence_group,),
            proposed_tests=("synthetic regression for the canonical task type",),
            proposed_verification=("deterministic trace evaluation",),
            proposed_destination=destination,
            quarantine_reasons=reasons,
        )

    def _from_feedback(self, record: ExplicitFeedbackRecord) -> LearningCandidate:
        if isinstance(record.content, FactFeedbackContent):
            content: CandidateContent = record.content.fact
            candidate_type = CandidateType.FACT
            title = f"Confirmed fact about {content.subject}"
            basis = CandidateConfidenceBasis.EXPLICIT_USER_CONFIRMATION
            origin = CandidateOrigin.EXPLICIT_USER_FEEDBACK
        elif isinstance(record.content, PreferenceFeedbackContent):
            content = record.content.preference
            candidate_type = CandidateType.PREFERENCE
            title = f"Confirmed preference for {content.subject}"
            basis = CandidateConfidenceBasis.EXPLICIT_USER_CONFIRMATION
            origin = CandidateOrigin.EXPLICIT_USER_FEEDBACK
        else:
            content = record.content.correction
            candidate_type = CandidateType.USER_CORRECTION
            title = f"User correction for {content.target_reference}"
            basis = CandidateConfidenceBasis.EXPLICIT_USER_CORRECTION
            origin = CandidateOrigin.EXPLICIT_USER_CORRECTION
        reasons = scan_content(content, title)
        return self._candidate(
            candidate_type=candidate_type,
            title=title,
            content=content,
            scope=(
                content.correction_scope
                if isinstance(content, UserCorrectionContent)
                else getattr(content, "scope", CandidateScope.USER)
            ),
            project=record.project,
            origin=origin,
            evaluations=(),
            source_evaluation_ids=(
                (record.source_evaluation_id,) if record.source_evaluation_id else ()
            ),
            source_task_ids=((record.task_id,) if record.task_id else ()),
            source_trace_ids=((record.trace_id,) if record.trace_id else ()),
            provenance=(_feedback_provenance(record, self.extractor_version),),
            confidence=ConfidenceLevel.HIGH,
            confidence_basis=(basis,),
            independence_groups=(group_for_feedback(record),),
            proposed_tests=("review the explicit feedback contract",),
            proposed_verification=("explicit user review",),
            proposed_destination=ProposedDestination.MEMORY_CANDIDATE,
            quarantine_reasons=reasons,
        )

    def _from_request(
        self,
        request: StructuredCandidateRequest,
        evaluation_by_id: dict[str, EvaluationEnvelope],
        group_by_evaluation: dict[str, IndependenceGroup],
    ) -> LearningCandidate:
        linked = tuple(
            evaluation_by_id[evaluation_id].evaluation
            for evaluation_id in request.source_evaluation_ids
            if evaluation_id in evaluation_by_id
        )
        reasons = set(reasons_from_request(request))
        missing = set(request.source_evaluation_ids) - set(evaluation_by_id)
        if not request.source_evaluation_ids or missing:
            reasons.add(QuarantineReason.MISSING_EVALUATION)
            reasons.add(QuarantineReason.UNKNOWN_PROVENANCE)
        if request.candidate_type is CandidateType.SKILL and (
            not linked or not all(_is_verified_success(item) for item in linked)
        ):
            reasons.add(QuarantineReason.UNKNOWN_PROVENANCE)
        if request.candidate_type is CandidateType.SUCCESSFUL_SOLUTION and (
            not linked or not all(_is_verified_success(item) for item in linked)
        ):
            reasons.add(QuarantineReason.UNKNOWN_PROVENANCE)
        if request.candidate_type is CandidateType.FAILURE_PATTERN and (
            not linked
            or not all(
                item.evaluation_class in _TECHNICAL_FAILURE_CLASSES for item in linked
            )
        ):
            reasons.add(QuarantineReason.UNKNOWN_PROVENANCE)
        groups = merge_groups(
            tuple(
                group_by_evaluation[evaluation_id]
                for evaluation_id in request.source_evaluation_ids
                if evaluation_id in group_by_evaluation
            )
        )
        confidence = min(
            (item.confidence for item in linked),
            key=lambda value: _CONFIDENCE_ORDER[value],
            default=ConfidenceLevel.LOW,
        )
        provenance = tuple(
            _evaluation_provenance(
                item,
                self.extractor_version,
                extraction_method=ExtractionMethod.DECLARATIVE_METADATA,
            )
            for item in linked
        )
        content_risk = request.minimum_required_risk_level
        if hasattr(request.content, "maximum_risk_level"):
            content_risk = request.content.maximum_risk_level
        elif hasattr(request.content, "expected_risk"):
            content_risk = request.content.expected_risk
        return self._candidate(
            candidate_type=request.candidate_type,
            title=request.title,
            content=request.content,
            scope=request.scope,
            project=request.project,
            origin=CandidateOrigin.STRUCTURED_METADATA,
            evaluations=linked,
            provenance=provenance,
            confidence=confidence,
            confidence_basis=(
                CandidateConfidenceBasis.QUARANTINE_SIGNAL
                if reasons
                else CandidateConfidenceBasis.VERIFIED_TRACE_EVALUATION,
            ),
            independence_groups=groups,
            risk_level=RiskLevel(content_risk),
            proposed_tests=request.proposed_tests,
            proposed_verification=request.proposed_verification,
            proposed_destination=request.proposed_destination,
            quarantine_reasons=tuple(sorted(reasons, key=lambda item: item.value)),
        )

    def _candidate(
        self,
        *,
        candidate_type: CandidateType,
        title: str,
        content: CandidateContent,
        scope: CandidateScope,
        project: str,
        origin: CandidateOrigin,
        evaluations: tuple[TraceEvaluation, ...],
        provenance: tuple[ProvenanceEntry, ...],
        confidence: ConfidenceLevel,
        confidence_basis: tuple[CandidateConfidenceBasis, ...],
        independence_groups: tuple[IndependenceGroup, ...],
        proposed_tests: tuple[str, ...],
        proposed_verification: tuple[str, ...],
        proposed_destination: ProposedDestination,
        quarantine_reasons: tuple[QuarantineReason, ...],
        risk_level: RiskLevel = RiskLevel.READ_ONLY,
        source_evaluation_ids: tuple[str, ...] | None = None,
        source_task_ids: tuple[str, ...] | None = None,
        source_trace_ids: tuple[str, ...] | None = None,
    ) -> LearningCandidate:
        evaluation_ids = source_evaluation_ids or tuple(
            item.evaluation_id for item in evaluations
        )
        task_ids = source_task_ids or tuple(item.task_id for item in evaluations)
        trace_ids = source_trace_ids or tuple(item.trace_id for item in evaluations)
        evidence_ids = tuple(
            reference.evidence_id
            for evaluation in evaluations
            for reference in evaluation.evidence_references
        )
        signature = duplicate_signature(
            candidate_type=candidate_type,
            scope=scope,
            project=project,
            content=content,
            proposed_destination=proposed_destination,
            risk_level=risk_level,
        )
        conflict = conflict_signature(
            candidate_type=candidate_type,
            scope=scope,
            project=project,
            content=content,
        )
        return _build_candidate(
            candidate_type=candidate_type,
            title=title,
            structured_content=content,
            scope=scope,
            project=project,
            origin=origin,
            source_evaluation_ids=evaluation_ids,
            source_task_ids=task_ids,
            source_trace_ids=trace_ids,
            source_evidence_ids=evidence_ids,
            provenance=provenance,
            confidence=confidence,
            confidence_basis=confidence_basis,
            independence_count=len(independence_groups),
            independence_groups=independence_groups,
            duplicate_signature=signature,
            conflict_signature=conflict,
            risk_level=risk_level,
            required_review=True,
            proposed_tests=proposed_tests,
            proposed_verification=proposed_verification,
            proposed_destination=proposed_destination,
            state=(
                CandidateState.QUARANTINED
                if quarantine_reasons
                else CandidateState.PROPOSED
            ),
            quarantine_reasons=quarantine_reasons,
        )

    def _deduplicate(
        self,
        candidates: tuple[LearningCandidate, ...],
    ) -> tuple[tuple[LearningCandidate, ...], tuple[DuplicateLink, ...]]:
        grouped: dict[str, list[LearningCandidate]] = defaultdict(list)
        for candidate in candidates:
            grouped[candidate.duplicate_signature].append(candidate)
        merged_candidates: list[LearningCandidate] = []
        links: list[DuplicateLink] = []
        for signature in sorted(grouped):
            members = sorted(grouped[signature], key=lambda item: item.content_hash)
            canonical = self._merge_duplicates(tuple(members))
            merged_candidates.append(canonical)
            if len(members) > 1:
                evaluation_sets = [set(item.source_evaluation_ids) for item in members]
                task_sets = [set(item.source_task_ids) for item in members]
                if any(
                    left & right
                    for index, left in enumerate(evaluation_sets)
                    for right in evaluation_sets[index + 1 :]
                ):
                    reason = DuplicateReason.SAME_EVALUATION
                elif any(
                    left & right
                    for index, left in enumerate(task_sets)
                    for right in task_sets[index + 1 :]
                ):
                    reason = DuplicateReason.SAME_TASK_LINEAGE
                else:
                    reason = DuplicateReason.SAME_SEMANTIC_CONTENT
                links.append(
                    DuplicateLink(
                        link_id=f"duplicate_{signature[:24]}",
                        duplicate_signature=signature,
                        canonical_candidate_id=canonical.candidate_id,
                        duplicate_source_evaluation_ids=tuple(
                            evaluation_id
                            for item in members
                            for evaluation_id in item.source_evaluation_ids
                        ),
                        reason=reason,
                    )
                )
        return tuple(merged_candidates), tuple(links)

    def _merge_duplicates(
        self,
        members: tuple[LearningCandidate, ...],
    ) -> LearningCandidate:
        canonical = members[0]
        reasons = tuple(
            reason for member in members for reason in member.quarantine_reasons
        )
        groups = merge_groups(
            tuple(group for member in members for group in member.independence_groups)
        )
        confidence = max(
            (member.confidence for member in members),
            key=lambda value: _CONFIDENCE_ORDER[value],
        )
        content = canonical.structured_content
        if isinstance(content, SuccessfulSolutionContent):
            all_successes = [
                member.structured_content
                for member in members
                if isinstance(member.structured_content, SuccessfulSolutionContent)
            ]
            content = SuccessfulSolutionContent(
                task_type=content.task_type,
                verified_preconditions=_merge_metadata_references(
                    reference
                    for item in all_successes
                    for reference in item.verified_preconditions
                ),
                verified_steps=_merge_metadata_references(
                    reference
                    for item in all_successes
                    for reference in item.verified_steps
                ),
                verified_postconditions=_merge_metadata_references(
                    reference
                    for item in all_successes
                    for reference in item.verified_postconditions
                ),
                allowed_scope=content.allowed_scope,
                limitations=tuple(
                    limitation
                    for item in all_successes
                    for limitation in item.limitations
                ),
            )
        return _replace_candidate(
            canonical,
            structured_content=content,
            source_evaluation_ids=tuple(
                value for member in members for value in member.source_evaluation_ids
            ),
            source_task_ids=tuple(
                value for member in members for value in member.source_task_ids
            ),
            source_trace_ids=tuple(
                value for member in members for value in member.source_trace_ids
            ),
            source_evidence_ids=tuple(
                value for member in members for value in member.source_evidence_ids
            ),
            provenance=tuple(
                value for member in members for value in member.provenance
            ),
            confidence=confidence,
            confidence_basis=tuple(
                value for member in members for value in member.confidence_basis
            ),
            independence_count=len(groups),
            independence_groups=groups,
            proposed_tests=tuple(
                value for member in members for value in member.proposed_tests
            ),
            proposed_verification=tuple(
                value for member in members for value in member.proposed_verification
            ),
            state=(CandidateState.QUARANTINED if reasons else CandidateState.PROPOSED),
            quarantine_reasons=reasons,
        )

    def _quarantine_for_conflict(
        self,
        candidate: LearningCandidate,
    ) -> LearningCandidate:
        reasons = tuple(
            sorted(
                set(
                    candidate.quarantine_reasons
                    + (QuarantineReason.CONFLICTING_EVIDENCE,)
                ),
                key=lambda item: item.value,
            )
        )
        return _replace_candidate(
            candidate,
            state=CandidateState.QUARANTINED,
            quarantine_reasons=reasons,
        )


__all__ = ["CandidateExtractor"]
