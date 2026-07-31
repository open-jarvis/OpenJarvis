"""Strict, immutable domain models for evidence-backed learning candidates."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from openjarvis.learning.evaluation.models import (
    ConfidenceLevel,
    Digest,
    EvaluationClass,
    EvidenceType,
    FailureCategory,
    Identifier,
    TraceEvaluation,
    TrustedBoundary,
)
from openjarvis.tasks.policy import RiskLevel

CANDIDATE_SCHEMA_VERSION = "1.0"
DEFAULT_EXTRACTOR_VERSION = "1.0.0"

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
    re.compile(
        r"(?:api_key|secret_key|auth_token|password)\s*[=:]\s*['\"][^'\"]{8,}",
        re.IGNORECASE,
    ),
)
_FORBIDDEN_CODE_PATTERNS = (
    re.compile(r"\beval\s*\(", re.IGNORECASE),
    re.compile(r"\bexec\s*\(", re.IGNORECASE),
    re.compile(r"\bpickle\s*\.\s*(?:load|loads)\s*\(", re.IGNORECASE),
    re.compile(r"\bimport\s+pickle\b", re.IGNORECASE),
    re.compile(r"\b__import__\s*\(", re.IGNORECASE),
    re.compile(r"\bimportlib\s*\.\s*import_module\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:powershell|cmd\.exe|bash|sh)\s+(?:-|/)", re.IGNORECASE),
    re.compile(r"\b(?:curl|wget)\s+", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bremove-item\s+", re.IGNORECASE),
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


def _safe_text(value: str) -> str:
    value = " ".join(value.strip().split())
    if not value:
        raise ValueError("text must not be empty")
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        raise ValueError("text contains secret-like material")
    if any(pattern.search(value) for pattern in _FORBIDDEN_CODE_PATTERNS):
        raise ValueError("text contains forbidden executable code")
    if any(ord(character) < 32 for character in value):
        raise ValueError("text contains control characters")
    return value


ShortText = Annotated[
    str,
    Field(min_length=1, max_length=256),
    AfterValidator(_safe_text),
]
SummaryText = Annotated[
    str,
    Field(min_length=1, max_length=1024),
    AfterValidator(_safe_text),
]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class CandidateType(str, Enum):
    FACT = "fact"
    USER_CORRECTION = "user_correction"
    PREFERENCE = "preference"
    FAILURE_PATTERN = "failure_pattern"
    SUCCESSFUL_SOLUTION = "successful_solution"
    ROUTING_RULE = "routing_rule"
    SKILL = "skill"
    TEST_CASE = "test_case"
    DOCUMENTATION_IMPROVEMENT = "documentation_improvement"
    CODE_IMPROVEMENT_PROPOSAL = "code_improvement_proposal"


class CandidateState(str, Enum):
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class CandidateScope(str, Enum):
    TASK = "task"
    SESSION = "session"
    PROJECT = "project"
    USER = "user"
    GLOBAL = "global"


class CandidateOrigin(str, Enum):
    AUTOMATIC_TRACE_EVALUATION = "automatic_trace_evaluation"
    EXPLICIT_USER_FEEDBACK = "explicit_user_feedback"
    EXPLICIT_USER_CORRECTION = "explicit_user_correction"
    STRUCTURED_METADATA = "structured_metadata"
    DETERMINISTIC_TEST = "deterministic_test"


class ProposedDestination(str, Enum):
    LEARNING_REVIEW = "learning_review"
    SKILL_REGISTRY = "skill_registry"
    ROUTING_SHADOW = "routing_shadow"
    MEMORY_CANDIDATE = "memory_candidate"
    TEST_SUITE = "test_suite"
    DOCUMENTATION = "documentation"
    CODE_REVIEW = "code_review"


class CandidateConfidenceBasis(str, Enum):
    VERIFIED_TRACE_EVALUATION = "verified_trace_evaluation"
    EXPLICIT_USER_CONFIRMATION = "explicit_user_confirmation"
    EXPLICIT_USER_CORRECTION = "explicit_user_correction"
    INDEPENDENT_CANONICAL_SOURCES = "independent_canonical_sources"
    INCOMPLETE_CANONICAL_EVIDENCE = "incomplete_canonical_evidence"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    QUARANTINE_SIGNAL = "quarantine_signal"


class ProvenanceSourceKind(str, Enum):
    DETERMINISTIC_TRACE_EVALUATION = "deterministic_trace_evaluation"
    EXPLICIT_USER_FEEDBACK = "explicit_user_feedback"
    EXPLICIT_USER_CORRECTION = "explicit_user_correction"
    DETERMINISTIC_TEST_RESULT = "deterministic_test_result"
    POLICY_RECORD = "policy_record"
    VERIFICATION_RECORD = "verification_record"


class ExtractionMethod(str, Enum):
    DETERMINISTIC_RULE = "deterministic_rule"
    EXPLICIT_USER_FEEDBACK = "explicit_user_feedback"
    EXPLICIT_USER_CORRECTION = "explicit_user_correction"
    DECLARATIVE_METADATA = "declarative_metadata"


class UntrustedSourceKind(str, Enum):
    RAW_MODEL_ANSWER = "raw_model_answer"
    MODEL_JUDGE_SCORE = "model_judge_score"
    RAW_WEBPAGE = "raw_webpage"
    RAW_DOCUMENT = "raw_document"
    RAW_TOOL_OUTPUT = "raw_tool_output"
    IMPORTED_SKILL_TEXT = "imported_skill_text"
    LEGACY_TRACE_SUCCESS = "legacy_trace_success"
    OPTIMIZER_RECOMMENDATION = "optimizer_recommendation"


class QuarantineReason(str, Enum):
    PROMPT_INJECTION = "prompt_injection"
    SECRET = "secret"
    FORBIDDEN_CODE = "forbidden_code"
    BASE64_CODE = "base64_code"
    UNKNOWN_PROVENANCE = "unknown_provenance"
    MISSING_EVALUATION = "missing_evaluation"
    MANIPULATED_EVALUATION = "manipulated_evaluation"
    LEGACY_ONLY = "legacy_only"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    CAPABILITY_ESCALATION = "capability_escalation"
    RISK_LEVEL_LOWERING = "risk_level_lowering"
    APPROVAL_INSTRUCTION = "approval_instruction"
    FULL_ACCESS = "full_access"
    HIDDEN_EXTERNAL_URL = "hidden_external_url"
    RAW_PRIVATE_PAYLOAD = "raw_private_payload"
    CHAIN_OF_THOUGHT = "chain_of_thought"


class SecuritySignal(str, Enum):
    CAPABILITY_ESCALATION = "capability_escalation"
    RISK_LEVEL_LOWERING = "risk_level_lowering"
    RAW_PRIVATE_PAYLOAD = "raw_private_payload"
    CHAIN_OF_THOUGHT = "chain_of_thought"


class RouteRecommendation(str, Enum):
    PYTHON_SDK = "python_sdk"
    APP_SERVER = "app_server"
    READ_ONLY_ANALYSIS = "read_only_analysis"
    TOOL_TASK = "tool_task"
    MEMORY_FIRST = "memory_first"
    BROWSER_REQUIRED = "browser_required"
    DESKTOP_REQUIRED = "desktop_required"
    VERIFIED_SKILL = "verified_skill"
    HUMAN_CLARIFICATION = "human_clarification"
    REJECT = "reject"


class ValueType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class FactValidity(str, Enum):
    CURRENT = "current"
    UNTIL_REVOKED = "until_revoked"
    BOUNDED = "bounded"
    UNKNOWN = "unknown"


class RollbackExpectation(str, Enum):
    NO_EFFECT = "no_effect"
    REVERSIBLE = "reversible"
    PREPARATION_ONLY = "preparation_only"


class FeedbackType(str, Enum):
    FACT_CONFIRMATION = "fact_confirmation"
    PREFERENCE = "preference"
    USER_CORRECTION = "user_correction"


class IndependenceAnchorKind(str, Enum):
    INPUT_DIGEST = "input_digest"
    TASK_LINEAGE = "task_lineage"
    THREAD_LINEAGE = "thread_lineage"
    TRACE_REPLAY = "trace_replay"
    USER_FEEDBACK = "user_feedback"


class ConflictType(str, Enum):
    FACT_VALUE = "fact_value"
    ROUTING_ROUTE = "routing_route"
    SKILL_CONTRACT = "skill_contract"
    SOLUTION_FAILURE = "solution_failure"
    USER_CORRECTION = "user_correction"
    SAFETY_BOUNDARY = "safety_boundary"


class ConflictPriority(str, Enum):
    NONE = "none"
    USER_CORRECTION = "user_correction"


class DuplicateReason(str, Enum):
    SAME_EVALUATION = "same_evaluation"
    SAME_TASK_LINEAGE = "same_task_lineage"
    SAME_SEMANTIC_CONTENT = "same_semantic_content"


class MetadataReference(StrictFrozenModel):
    reference_id: Identifier
    evidence_type: EvidenceType
    digest: Digest


class SchemaFieldProposal(StrictFrozenModel):
    name: Identifier
    value_type: ValueType
    required: bool
    description: ShortText


class SchemaProposal(StrictFrozenModel):
    fields: tuple[SchemaFieldProposal, ...] = ()
    additional_properties: Literal[False] = False

    @field_validator("fields")
    @classmethod
    def _sort_fields(
        cls,
        values: tuple[SchemaFieldProposal, ...],
    ) -> tuple[SchemaFieldProposal, ...]:
        names = [value.name for value in values]
        if len(names) != len(set(names)):
            raise ValueError("schema field names must be unique")
        return tuple(sorted(values, key=lambda value: value.name))


class DeclarativeSkillStep(StrictFrozenModel):
    step_id: Identifier
    tool_id: Identifier
    purpose: ShortText
    input_binding_ids: tuple[Identifier, ...] = ()
    expected_evidence_types: tuple[EvidenceType, ...] = ()

    @field_validator("input_binding_ids")
    @classmethod
    def _sort_bindings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("expected_evidence_types")
    @classmethod
    def _sort_evidence_types(
        cls,
        values: tuple[EvidenceType, ...],
    ) -> tuple[EvidenceType, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))


class FactContent(StrictFrozenModel):
    kind: Literal[CandidateType.FACT] = CandidateType.FACT
    subject: ShortText
    predicate: ShortText
    value: SummaryText
    scope: CandidateScope
    validity: FactValidity
    explicit_user_confirmation_required: bool


class UserCorrectionContent(StrictFrozenModel):
    kind: Literal[CandidateType.USER_CORRECTION] = CandidateType.USER_CORRECTION
    target_reference: Identifier
    previous_value_digest: Digest
    corrected_value: SummaryText
    correction_scope: CandidateScope
    explicit_user_source: Literal[True] = True


class PreferenceContent(StrictFrozenModel):
    kind: Literal[CandidateType.PREFERENCE] = CandidateType.PREFERENCE
    subject: ShortText
    preference: SummaryText
    context: ShortText
    explicit_user_confirmation: Literal[True] = True


class FailurePatternContent(StrictFrozenModel):
    kind: Literal[CandidateType.FAILURE_PATTERN] = CandidateType.FAILURE_PATTERN
    failure_category: FailureCategory
    task_type: Identifier
    trigger_conditions: tuple[ShortText, ...]
    observed_symptoms: tuple[ShortText, ...]
    canonical_causes: tuple[ShortText, ...]
    excluded_causes: tuple[ShortText, ...]
    proposed_mitigation: SummaryText
    verification_requirements: tuple[ShortText, ...]

    @field_validator(
        "trigger_conditions",
        "observed_symptoms",
        "canonical_causes",
        "excluded_causes",
        "verification_requirements",
    )
    @classmethod
    def _sort_texts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class SuccessfulSolutionContent(StrictFrozenModel):
    kind: Literal[CandidateType.SUCCESSFUL_SOLUTION] = CandidateType.SUCCESSFUL_SOLUTION
    task_type: Identifier
    verified_preconditions: tuple[MetadataReference, ...]
    verified_steps: tuple[MetadataReference, ...]
    verified_postconditions: tuple[MetadataReference, ...]
    allowed_scope: CandidateScope
    limitations: tuple[ShortText, ...] = ()

    @field_validator(
        "verified_preconditions",
        "verified_steps",
        "verified_postconditions",
    )
    @classmethod
    def _sort_references(
        cls,
        values: tuple[MetadataReference, ...],
    ) -> tuple[MetadataReference, ...]:
        by_key = {
            (value.reference_id, value.evidence_type.value, value.digest): value
            for value in values
        }
        return tuple(by_key[key] for key in sorted(by_key))

    @field_validator("limitations")
    @classmethod
    def _sort_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class RoutingRuleContent(StrictFrozenModel):
    kind: Literal[CandidateType.ROUTING_RULE] = CandidateType.ROUTING_RULE
    condition_key: Identifier
    recommended_route: RouteRecommendation
    alternatives: tuple[RouteRecommendation, ...] = ()
    expected_risk: RiskLevel
    known_limitations: tuple[ShortText, ...] = ()
    shadow_mode: Literal[True] = True

    @field_validator("alternatives")
    @classmethod
    def _sort_alternatives(
        cls,
        values: tuple[RouteRecommendation, ...],
    ) -> tuple[RouteRecommendation, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))

    @field_validator("known_limitations")
    @classmethod
    def _sort_limitations(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class SkillCandidateContent(StrictFrozenModel):
    kind: Literal[CandidateType.SKILL] = CandidateType.SKILL
    proposed_name: Identifier
    purpose: SummaryText
    input_schema_proposal: SchemaProposal
    output_schema_proposal: SchemaProposal
    preconditions: tuple[ShortText, ...]
    postconditions: tuple[ShortText, ...]
    allowed_tool_ids: tuple[Identifier, ...]
    maximum_risk_level: RiskLevel
    proposed_steps: tuple[DeclarativeSkillStep, ...]
    negative_cases: tuple[ShortText, ...]
    rollback_expectation: RollbackExpectation

    @field_validator("allowed_tool_ids")
    @classmethod
    def _sort_tools(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("preconditions", "postconditions", "negative_cases")
    @classmethod
    def _sort_texts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class TestCaseContent(StrictFrozenModel):
    kind: Literal[CandidateType.TEST_CASE] = CandidateType.TEST_CASE
    fixture_id: Identifier
    task_type: Identifier
    expected_evaluation_class: EvaluationClass
    evidence_requirements: tuple[EvidenceType, ...]
    negative_case: bool

    @field_validator("evidence_requirements")
    @classmethod
    def _sort_evidence(
        cls,
        values: tuple[EvidenceType, ...],
    ) -> tuple[EvidenceType, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))


class DocumentationImprovementContent(StrictFrozenModel):
    kind: Literal[CandidateType.DOCUMENTATION_IMPROVEMENT] = (
        CandidateType.DOCUMENTATION_IMPROVEMENT
    )
    target_document_id: Identifier
    issue_summary: SummaryText
    proposed_change_summary: SummaryText
    verification_requirements: tuple[ShortText, ...]

    @field_validator("verification_requirements")
    @classmethod
    def _sort_verification(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class CodeImprovementProposalContent(StrictFrozenModel):
    kind: Literal[CandidateType.CODE_IMPROVEMENT_PROPOSAL] = (
        CandidateType.CODE_IMPROVEMENT_PROPOSAL
    )
    component_id: Identifier
    problem_statement: SummaryText
    expected_safety_boundaries: tuple[ShortText, ...]
    proposed_tests: tuple[ShortText, ...]
    expected_behavior: SummaryText
    contains_patch: Literal[False] = False

    @field_validator("expected_safety_boundaries", "proposed_tests")
    @classmethod
    def _sort_texts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


CandidateContent = Annotated[
    FactContent
    | UserCorrectionContent
    | PreferenceContent
    | FailurePatternContent
    | SuccessfulSolutionContent
    | RoutingRuleContent
    | SkillCandidateContent
    | TestCaseContent
    | DocumentationImprovementContent
    | CodeImprovementProposalContent,
    Field(discriminator="kind"),
]


class ProvenanceEntry(StrictFrozenModel):
    provenance_id: Identifier = Field(default_factory=lambda: new_id("provenance"))
    source_kind: ProvenanceSourceKind
    source_id: Identifier
    source_digest: Digest
    source_evaluation_id: Identifier | None = None
    trusted_boundary: TrustedBoundary
    extraction_method: ExtractionMethod
    extraction_version: Annotated[
        str,
        Field(pattern=r"^[0-9A-Za-z][0-9A-Za-z._+-]*$", max_length=64),
    ]
    created_at: datetime = Field(default_factory=utc_now)

    _normalize_created_at = field_validator("created_at")(_as_utc)

    @model_validator(mode="after")
    def _source_contract(self) -> ProvenanceEntry:
        evaluation_sources = {
            ProvenanceSourceKind.DETERMINISTIC_TRACE_EVALUATION,
            ProvenanceSourceKind.POLICY_RECORD,
            ProvenanceSourceKind.VERIFICATION_RECORD,
        }
        user_sources = {
            ProvenanceSourceKind.EXPLICIT_USER_FEEDBACK,
            ProvenanceSourceKind.EXPLICIT_USER_CORRECTION,
        }
        if self.source_kind in evaluation_sources:
            if self.source_evaluation_id is None:
                raise ValueError("evaluation provenance requires evaluation_id")
            if self.trusted_boundary is not TrustedBoundary.CANONICAL_RUNTIME:
                raise ValueError("evaluation provenance must be canonical runtime")
        if self.source_kind in user_sources and (
            self.trusted_boundary is not TrustedBoundary.EXPLICIT_USER
        ):
            raise ValueError("user provenance must use explicit_user boundary")
        return self


class EvaluationLineage(StrictFrozenModel):
    root_task_id: Identifier | None = None
    retry_of_task_id: Identifier | None = None
    parent_task_id: Identifier | None = None
    thread_id: Identifier | None = None
    replay_of_trace_id: Identifier | None = None


class EvaluationEnvelope(StrictFrozenModel):
    evaluation: TraceEvaluation
    scope: CandidateScope = CandidateScope.PROJECT
    project: Identifier
    lineage: EvaluationLineage = Field(default_factory=EvaluationLineage)


class IndependenceGroup(StrictFrozenModel):
    group_digest: Digest
    anchor_kind: IndependenceAnchorKind
    anchor_digest: Digest
    source_evaluation_ids: tuple[Identifier, ...] = ()
    source_task_ids: tuple[Identifier, ...] = ()
    source_trace_ids: tuple[Identifier, ...] = ()
    source_feedback_ids: tuple[Identifier, ...] = ()

    @field_validator(
        "source_evaluation_ids",
        "source_task_ids",
        "source_trace_ids",
        "source_feedback_ids",
    )
    @classmethod
    def _sort_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class FactFeedbackContent(StrictFrozenModel):
    kind: Literal[FeedbackType.FACT_CONFIRMATION] = FeedbackType.FACT_CONFIRMATION
    fact: FactContent

    @model_validator(mode="after")
    def _confirmed(self) -> FactFeedbackContent:
        if self.fact.explicit_user_confirmation_required:
            raise ValueError("confirmed fact cannot still require confirmation")
        return self


class PreferenceFeedbackContent(StrictFrozenModel):
    kind: Literal[FeedbackType.PREFERENCE] = FeedbackType.PREFERENCE
    preference: PreferenceContent


class CorrectionFeedbackContent(StrictFrozenModel):
    kind: Literal[FeedbackType.USER_CORRECTION] = FeedbackType.USER_CORRECTION
    correction: UserCorrectionContent


FeedbackContent = Annotated[
    FactFeedbackContent | PreferenceFeedbackContent | CorrectionFeedbackContent,
    Field(discriminator="kind"),
]


class ExplicitFeedbackRecord(StrictFrozenModel):
    feedback_id: Identifier
    feedback_type: FeedbackType
    user_source_id: Identifier
    feedback_group_id: Identifier
    project: Identifier
    content: FeedbackContent
    source_digest: Digest
    source_evaluation_id: Identifier | None = None
    task_id: Identifier | None = None
    session_id: Identifier | None = None
    trace_id: Identifier | None = None
    explicit: Literal[True] = True
    created_at: datetime

    _normalize_created_at = field_validator("created_at")(_as_utc)

    @model_validator(mode="after")
    def _matching_type(self) -> ExplicitFeedbackRecord:
        if self.content.kind is not self.feedback_type:
            raise ValueError("feedback_type does not match content")
        return self


class StructuredCandidateRequest(StrictFrozenModel):
    request_id: Identifier
    candidate_type: CandidateType
    title: ShortText
    content: CandidateContent
    scope: CandidateScope
    project: Identifier
    source_evaluation_ids: tuple[Identifier, ...]
    proposed_tests: tuple[ShortText, ...]
    proposed_verification: tuple[ShortText, ...]
    proposed_destination: ProposedDestination
    minimum_required_risk_level: RiskLevel = RiskLevel.READ_ONLY
    security_signals: tuple[SecuritySignal, ...] = ()
    untrusted_sources: tuple[UntrustedSourceKind, ...] = ()

    @field_validator("source_evaluation_ids")
    @classmethod
    def _sort_evaluation_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("proposed_tests", "proposed_verification")
    @classmethod
    def _sort_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("security_signals")
    @classmethod
    def _sort_security_signals(
        cls,
        values: tuple[SecuritySignal, ...],
    ) -> tuple[SecuritySignal, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))

    @field_validator("untrusted_sources")
    @classmethod
    def _sort_untrusted_sources(
        cls,
        values: tuple[UntrustedSourceKind, ...],
    ) -> tuple[UntrustedSourceKind, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))

    @model_validator(mode="after")
    def _matching_type(self) -> StructuredCandidateRequest:
        if self.content.kind is not self.candidate_type:
            raise ValueError("candidate_type does not match content")
        if self.candidate_type in {
            CandidateType.FACT,
            CandidateType.PREFERENCE,
            CandidateType.USER_CORRECTION,
        }:
            raise ValueError(
                "facts, preferences, and corrections require explicit feedback"
            )
        if self.candidate_type is CandidateType.SKILL and (
            self.proposed_destination is not ProposedDestination.SKILL_REGISTRY
        ):
            raise ValueError("skill requests must target skill_registry")
        if self.candidate_type is CandidateType.ROUTING_RULE and (
            self.proposed_destination is not ProposedDestination.ROUTING_SHADOW
        ):
            raise ValueError("routing requests must target routing_shadow")
        return self


class LearningCandidate(StrictFrozenModel):
    schema_version: Literal["1.0"] = CANDIDATE_SCHEMA_VERSION
    candidate_id: Identifier = Field(default_factory=lambda: new_id("candidate"))
    revision: int = Field(default=1, ge=1)
    candidate_type: CandidateType
    title: ShortText
    structured_content: CandidateContent
    scope: CandidateScope
    project: Identifier
    origin: CandidateOrigin
    source_evaluation_ids: tuple[Identifier, ...]
    source_task_ids: tuple[Identifier, ...]
    source_trace_ids: tuple[Identifier, ...]
    source_evidence_ids: tuple[Identifier, ...]
    provenance: tuple[ProvenanceEntry, ...]
    confidence: ConfidenceLevel
    confidence_basis: tuple[CandidateConfidenceBasis, ...]
    independence_count: int = Field(ge=0)
    independence_groups: tuple[IndependenceGroup, ...]
    duplicate_signature: Digest
    conflict_signature: Digest
    risk_level: RiskLevel
    required_review: bool
    proposed_tests: tuple[ShortText, ...]
    proposed_verification: tuple[ShortText, ...]
    proposed_destination: ProposedDestination
    state: CandidateState
    quarantine_reasons: tuple[QuarantineReason, ...] = ()
    rejection_reason: ShortText | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    content_hash: Digest

    _normalize_created_at = field_validator("created_at")(_as_utc)
    _normalize_updated_at = field_validator("updated_at")(_as_utc)

    @field_validator(
        "source_evaluation_ids",
        "source_task_ids",
        "source_trace_ids",
        "source_evidence_ids",
    )
    @classmethod
    def _sort_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("provenance")
    @classmethod
    def _sort_provenance(
        cls,
        values: tuple[ProvenanceEntry, ...],
    ) -> tuple[ProvenanceEntry, ...]:
        by_key = {
            (value.source_kind.value, value.source_id, value.source_digest): value
            for value in values
        }
        return tuple(by_key[key] for key in sorted(by_key))

    @field_validator("confidence_basis")
    @classmethod
    def _sort_confidence_basis(
        cls,
        values: tuple[CandidateConfidenceBasis, ...],
    ) -> tuple[CandidateConfidenceBasis, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))

    @field_validator("independence_groups")
    @classmethod
    def _sort_independence_groups(
        cls,
        values: tuple[IndependenceGroup, ...],
    ) -> tuple[IndependenceGroup, ...]:
        by_digest = {value.group_digest: value for value in values}
        return tuple(by_digest[key] for key in sorted(by_digest))

    @field_validator("proposed_tests", "proposed_verification")
    @classmethod
    def _sort_text(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("quarantine_reasons")
    @classmethod
    def _sort_quarantine_reasons(
        cls,
        values: tuple[QuarantineReason, ...],
    ) -> tuple[QuarantineReason, ...]:
        return tuple(sorted(set(values), key=lambda value: value.value))

    @model_validator(mode="after")
    def _candidate_contract(self) -> LearningCandidate:
        if self.structured_content.kind is not self.candidate_type:
            raise ValueError("candidate_type does not match structured_content")
        if self.independence_count != len(self.independence_groups):
            raise ValueError("independence_count must match independence_groups")
        if self.state is CandidateState.QUARANTINED and not self.quarantine_reasons:
            raise ValueError("quarantined candidates require quarantine_reasons")
        if self.state is not CandidateState.QUARANTINED and self.quarantine_reasons:
            raise ValueError("only quarantined candidates may have quarantine_reasons")
        if self.state is CandidateState.REJECTED and self.rejection_reason is None:
            raise ValueError("rejected candidates require rejection_reason")
        if self.state is not CandidateState.REJECTED and self.rejection_reason:
            raise ValueError("rejection_reason is only valid for rejected candidates")
        if (
            self.revision == 1
            and self.origin is CandidateOrigin.AUTOMATIC_TRACE_EVALUATION
            and self.state
            not in {
                CandidateState.PROPOSED,
                CandidateState.QUARANTINED,
            }
        ):
            raise ValueError("automatic revision 1 may only propose or quarantine")
        if self.content_hash != self.recompute_hash():
            raise ValueError("content_hash does not match candidate payload")
        return self

    def semantic_payload(self) -> dict[str, object]:
        payload = self.model_dump(
            mode="json",
            exclude={
                "candidate_id",
                "revision",
                "created_at",
                "updated_at",
                "content_hash",
            },
        )
        payload["provenance"] = [
            entry.model_dump(
                mode="json",
                exclude={"provenance_id", "created_at"},
            )
            for entry in self.provenance
        ]
        return payload

    def recompute_hash(self) -> str:
        serialized = json.dumps(
            self.semantic_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class DuplicateLink(StrictFrozenModel):
    link_id: Identifier
    duplicate_signature: Digest
    canonical_candidate_id: Identifier
    duplicate_source_evaluation_ids: tuple[Identifier, ...]
    reason: DuplicateReason

    @field_validator("duplicate_source_evaluation_ids")
    @classmethod
    def _sort_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))


class ConflictLink(StrictFrozenModel):
    conflict_id: Identifier
    conflict_type: ConflictType
    conflict_signature: Digest
    candidate_ids: tuple[Identifier, Identifier]
    candidate_duplicate_signatures: tuple[Digest, Digest]
    priority: ConflictPriority
    preferred_candidate_id: Identifier | None = None
    reason: ShortText

    @field_validator("candidate_ids", "candidate_duplicate_signatures")
    @classmethod
    def _sort_pair(cls, values: tuple[str, str]) -> tuple[str, str]:
        if values[0] == values[1]:
            raise ValueError("conflict requires two different references")
        return tuple(sorted(values))  # type: ignore[return-value]

    @model_validator(mode="after")
    def _priority_contract(self) -> ConflictLink:
        if self.priority is ConflictPriority.USER_CORRECTION:
            if self.preferred_candidate_id not in self.candidate_ids:
                raise ValueError("preferred correction must reference one candidate")
        elif self.preferred_candidate_id is not None:
            raise ValueError("preferred_candidate_id requires explicit priority")
        return self


class ExtractionResult(StrictFrozenModel):
    schema_version: Literal["1.0"] = CANDIDATE_SCHEMA_VERSION
    run_id: Identifier = Field(default_factory=lambda: new_id("extraction"))
    extractor_version: Annotated[
        str,
        Field(pattern=r"^[0-9A-Za-z][0-9A-Za-z._+-]*$", max_length=64),
    ]
    input_evaluation_ids: tuple[Identifier, ...]
    candidates: tuple[LearningCandidate, ...]
    duplicate_links: tuple[DuplicateLink, ...]
    conflict_links: tuple[ConflictLink, ...]
    quarantined_candidate_ids: tuple[Identifier, ...]
    warnings: tuple[ShortText, ...]
    created_at: datetime = Field(default_factory=utc_now)
    run_hash: Digest

    _normalize_created_at = field_validator("created_at")(_as_utc)

    @field_validator("input_evaluation_ids", "quarantined_candidate_ids")
    @classmethod
    def _sort_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("candidates")
    @classmethod
    def _sort_candidates(
        cls,
        values: tuple[LearningCandidate, ...],
    ) -> tuple[LearningCandidate, ...]:
        return tuple(
            sorted(
                values,
                key=lambda value: (
                    value.duplicate_signature,
                    value.content_hash,
                    value.candidate_id,
                ),
            )
        )

    @field_validator("duplicate_links")
    @classmethod
    def _sort_duplicate_links(
        cls,
        values: tuple[DuplicateLink, ...],
    ) -> tuple[DuplicateLink, ...]:
        return tuple(sorted(values, key=lambda value: value.link_id))

    @field_validator("conflict_links")
    @classmethod
    def _sort_conflict_links(
        cls,
        values: tuple[ConflictLink, ...],
    ) -> tuple[ConflictLink, ...]:
        return tuple(sorted(values, key=lambda value: value.conflict_id))

    @field_validator("warnings")
    @classmethod
    def _sort_warnings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    def semantic_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "extractor_version": self.extractor_version,
            "input_evaluation_ids": list(self.input_evaluation_ids),
            "candidate_hashes": sorted(
                candidate.content_hash for candidate in self.candidates
            ),
            "duplicate_links": [
                {
                    "duplicate_signature": link.duplicate_signature,
                    "duplicate_source_evaluation_ids": list(
                        link.duplicate_source_evaluation_ids
                    ),
                    "reason": link.reason.value,
                }
                for link in self.duplicate_links
            ],
            "conflict_links": [
                {
                    "conflict_type": link.conflict_type.value,
                    "conflict_signature": link.conflict_signature,
                    "candidate_duplicate_signatures": list(
                        link.candidate_duplicate_signatures
                    ),
                    "priority": link.priority.value,
                }
                for link in self.conflict_links
            ],
            "warnings": list(self.warnings),
        }

    def recompute_hash(self) -> str:
        serialized = json.dumps(
            self.semantic_payload(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @model_validator(mode="after")
    def _run_hash_matches(self) -> ExtractionResult:
        if self.run_hash != self.recompute_hash():
            raise ValueError("run_hash does not match extraction payload")
        expected_quarantine = {
            candidate.candidate_id
            for candidate in self.candidates
            if candidate.state is CandidateState.QUARANTINED
        }
        if set(self.quarantined_candidate_ids) != expected_quarantine:
            raise ValueError("quarantined_candidate_ids do not match candidates")
        return self


__all__ = [
    "CANDIDATE_SCHEMA_VERSION",
    "DEFAULT_EXTRACTOR_VERSION",
    "CandidateConfidenceBasis",
    "CandidateContent",
    "CandidateOrigin",
    "CandidateScope",
    "CandidateState",
    "CandidateType",
    "CodeImprovementProposalContent",
    "ConflictLink",
    "ConflictPriority",
    "ConflictType",
    "CorrectionFeedbackContent",
    "DeclarativeSkillStep",
    "DocumentationImprovementContent",
    "DuplicateLink",
    "DuplicateReason",
    "EvaluationEnvelope",
    "EvaluationLineage",
    "ExplicitFeedbackRecord",
    "ExtractionMethod",
    "ExtractionResult",
    "FactContent",
    "FactFeedbackContent",
    "FactValidity",
    "FailurePatternContent",
    "FeedbackContent",
    "FeedbackType",
    "IndependenceAnchorKind",
    "IndependenceGroup",
    "LearningCandidate",
    "MetadataReference",
    "PreferenceContent",
    "PreferenceFeedbackContent",
    "ProposedDestination",
    "ProvenanceEntry",
    "ProvenanceSourceKind",
    "QuarantineReason",
    "RollbackExpectation",
    "RouteRecommendation",
    "RoutingRuleContent",
    "SchemaFieldProposal",
    "SchemaProposal",
    "SecuritySignal",
    "ShortText",
    "SkillCandidateContent",
    "StructuredCandidateRequest",
    "SuccessfulSolutionContent",
    "SummaryText",
    "TestCaseContent",
    "UntrustedSourceKind",
    "UserCorrectionContent",
    "ValueType",
    "new_id",
    "utc_now",
]
