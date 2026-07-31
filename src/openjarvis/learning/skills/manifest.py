"""Strict, immutable and hash-bound skill manifests.

The manifest is declarative.  It deliberately has no callable, source-code,
shell-command or approval field.  Runtime binding is performed against the
trusted :class:`ToolManifestCatalog`, never against names supplied by model
text or imported documents.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from openjarvis.learning.candidates.models import CandidateScope
from openjarvis.learning.evaluation.models import Digest, EvidenceType, Identifier
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tasks.types import ExecutionLane
from openjarvis.tools.manifest import ToolManifestCatalog

SKILL_MANIFEST_SCHEMA_VERSION = "1.0"

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
    re.compile(
        r"(?:api[_ -]?key|secret[_ -]?key|auth[_ -]?token|password|cookie)"
        r"\s*[=:]\s*['\"]?[^\s'\"]{8,}",
        re.IGNORECASE,
    ),
)
_EXECUTABLE_PATTERNS = (
    re.compile(r"\beval\s*\(", re.IGNORECASE),
    re.compile(r"\bexec\s*\(", re.IGNORECASE),
    re.compile(r"\bpickle\s*\.\s*(?:load|loads)\s*\(", re.IGNORECASE),
    re.compile(r"\bimport\s+pickle\b", re.IGNORECASE),
    re.compile(r"\b__import__\s*\(", re.IGNORECASE),
    re.compile(r"\b(?:powershell|cmd\.exe|bash|sh)\s+(?:-|/)", re.IGNORECASE),
    re.compile(r"\b(?:curl|wget)\s+", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\b", re.IGNORECASE),
    re.compile(r"\bremove-item\s+", re.IGNORECASE),
)
_AUTHORITY_PATTERNS = (
    re.compile(r"\bfull_access\b", re.IGNORECASE),
    re.compile(r"\balways\s+allow\b", re.IGNORECASE),
    re.compile(r"\bauto(?:matic(?:ally)?)?[- _]?approv", re.IGNORECASE),
    re.compile(r"\bapproval\s*[=:]\s*(?:true|granted|allow)", re.IGNORECASE),
)
_PRIVATE_PATTERNS = (
    re.compile(r"\bchain[- ]of[- ]thought\b", re.IGNORECASE),
    re.compile(r"\breasoning tokens?\b", re.IGNORECASE),
    re.compile(r"\bprivate chat\b", re.IGNORECASE),
    re.compile(r"\bfull prompt\b", re.IGNORECASE),
)
_URL_PATTERN = re.compile(r"(?:https?|ftp)://", re.IGNORECASE)
_SEMVER_PATTERN = (
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


class SkillManifestError(ValueError):
    """Raised when a manifest violates a trusted binding or hash contract."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


def _as_optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _as_utc(value)


def _safe_text(value: str) -> str:
    value = " ".join(value.strip().split())
    if not value:
        raise ValueError("text must not be empty")
    _reject_unsafe_string(value)
    return value


def _reject_unsafe_string(value: str) -> None:
    if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        raise ValueError("manifest contains secret-like material")
    if any(pattern.search(value) for pattern in _EXECUTABLE_PATTERNS):
        raise ValueError("manifest contains executable or shell content")
    if any(pattern.search(value) for pattern in _AUTHORITY_PATTERNS):
        raise ValueError("manifest attempts to grant authority or approval")
    if any(pattern.search(value) for pattern in _PRIVATE_PATTERNS):
        raise ValueError("manifest contains private reasoning or chat material")
    if _URL_PATTERN.search(value):
        raise ValueError("manifest contains a URL")
    if any(ord(character) < 32 for character in value):
        raise ValueError("manifest contains control characters")


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for key, child in value.items():
            result.extend(_walk_strings(key))
            result.extend(_walk_strings(child))
        return result
    if isinstance(value, (list, tuple, set)):
        result = []
        for child in value:
            result.extend(_walk_strings(child))
        return result
    return []


def canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def manifest_content_hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


SafeText = Annotated[
    str,
    Field(min_length=1, max_length=1024),
    AfterValidator(_safe_text),
]
SkillIdentifier = Annotated[
    str,
    Field(
        min_length=1,
        max_length=256,
        pattern=r"^[a-z0-9][a-z0-9._:-]*$",
    ),
]
SemanticVersion = Annotated[str, Field(pattern=_SEMVER_PATTERN, max_length=128)]


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SkillLifecycleStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    TESTING = "testing"
    VERIFICATION_FAILED = "verification_failed"
    VERIFIED = "verified"
    PROMOTION_PENDING = "promotion_pending"
    PROMOTED = "promoted"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"


class FailureBehavior(str, Enum):
    ABORT = "abort"
    RECORD_FAILURE = "record_failure"
    ROLLBACK = "rollback"


class VerificationKind(str, Enum):
    DECLARATIVE_POSTCONDITIONS = "declarative_postconditions"
    TOOL_VERIFIER = "tool_verifier"


class RollbackKind(str, Enum):
    NO_EFFECT = "no_effect"
    TOOL_MANAGED = "tool_managed"
    ACTIVATE_PREVIOUS_VERSION = "activate_previous_version"


class SkillIdempotencyPolicy(str, Enum):
    KEY_REQUIRED = "key_required"
    SAFE_RETRY = "safe_retry"
    NEVER_AFTER_UNKNOWN_EFFECT = "never_after_unknown_effect"


class MetricKind(str, Enum):
    COUNT = "count"
    VERIFIED_RATE = "verified_rate"


class ManifestValueType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


class ManifestSchemaField(StrictFrozenModel):
    field_id: Identifier
    value_type: ManifestValueType
    required: bool
    description: SafeText


class ManifestSchema(StrictFrozenModel):
    fields: tuple[ManifestSchemaField, ...] = ()
    additional_properties: bool = False

    @field_validator("additional_properties")
    @classmethod
    def _closed_schema(cls, value: bool) -> bool:
        if value:
            raise ValueError("skill schemas must reject additional properties")
        return value

    @field_validator("fields")
    @classmethod
    def _unique_fields(
        cls, values: tuple[ManifestSchemaField, ...]
    ) -> tuple[ManifestSchemaField, ...]:
        by_id = {value.field_id: value for value in values}
        if len(by_id) != len(values):
            raise ValueError("schema field IDs must be unique")
        return tuple(by_id[key] for key in sorted(by_id))


class SkillProvenance(StrictFrozenModel):
    provenance_id: Identifier
    source_kind: Identifier
    source_id: Identifier
    source_digest: Digest
    evidence_digest: Digest
    created_at: datetime = Field(default_factory=utc_now)

    _normalise_created_at = field_validator("created_at")(_as_utc)


class RetryPolicy(StrictFrozenModel):
    maximum_retries: int = Field(default=0, ge=0, le=1)
    after_unknown_effect: bool = False

    @field_validator("after_unknown_effect")
    @classmethod
    def _unknown_effect_is_never_retried(cls, value: bool) -> bool:
        if value:
            raise ValueError("unknown effects may never be retried")
        return value


class VerificationStrategy(StrictFrozenModel):
    kind: VerificationKind
    required_evidence_types: tuple[EvidenceType, ...]

    @field_validator("required_evidence_types")
    @classmethod
    def _evidence_required(
        cls, values: tuple[EvidenceType, ...]
    ) -> tuple[EvidenceType, ...]:
        values = tuple(sorted(set(values), key=lambda value: value.value))
        if not values:
            raise ValueError("verification requires evidence types")
        return values


class RollbackStrategy(StrictFrozenModel):
    kind: RollbackKind
    verification_reference_ids: tuple[Identifier, ...]

    @field_validator("verification_reference_ids")
    @classmethod
    def _references_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("rollback strategy requires verification references")
        return values


class SkillMetricDefinition(StrictFrozenModel):
    metric_id: Identifier
    kind: MetricKind
    qualifying_outcomes: tuple[Identifier, ...]

    @field_validator("qualifying_outcomes")
    @classmethod
    def _outcomes_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("metric definition requires qualifying outcomes")
        return values


class DeclarativeSkillStep(StrictFrozenModel):
    step_id: Identifier
    purpose: SafeText
    tool_id: Identifier
    input_binding_ids: tuple[Identifier, ...]
    expected_evidence_types: tuple[EvidenceType, ...]
    preconditions: tuple[SafeText, ...]
    postconditions: tuple[SafeText, ...]
    on_failure: FailureBehavior

    @field_validator("input_binding_ids", "preconditions", "postconditions")
    @classmethod
    def _normalise_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    @field_validator("expected_evidence_types")
    @classmethod
    def _normalise_evidence(
        cls, values: tuple[EvidenceType, ...]
    ) -> tuple[EvidenceType, ...]:
        values = tuple(sorted(set(values), key=lambda value: value.value))
        if not values:
            raise ValueError("every step requires expected evidence types")
        return values


class SkillManifestDraft(StrictFrozenModel):
    schema_version: str = Field(default=SKILL_MANIFEST_SCHEMA_VERSION)
    skill_id: SkillIdentifier
    name: SkillIdentifier
    semantic_version: SemanticVersion
    description: SafeText
    scope: CandidateScope
    status: SkillLifecycleStatus = SkillLifecycleStatus.DRAFT
    origin_candidate_id: Identifier
    origin_candidate_revision: int = Field(ge=1)
    provenance: tuple[SkillProvenance, ...]
    input_schema: ManifestSchema
    output_schema: ManifestSchema
    preconditions: tuple[SafeText, ...]
    postconditions: tuple[SafeText, ...]
    allowed_tool_ids: tuple[Identifier, ...]
    required_capabilities: tuple[Identifier, ...]
    maximum_risk_level: RiskLevel
    allowed_execution_lanes: tuple[ExecutionLane, ...]
    timeout_seconds: float = Field(gt=0, le=300)
    maximum_steps: int = Field(ge=1, le=64)
    maximum_call_depth: int = Field(ge=1, le=8)
    retry_policy: RetryPolicy
    idempotency_policy: SkillIdempotencyPolicy
    declarative_steps: tuple[DeclarativeSkillStep, ...]
    verification_strategy: VerificationStrategy
    rollback_strategy: RollbackStrategy
    positive_test_ids: tuple[Identifier, ...]
    negative_test_ids: tuple[Identifier, ...]
    policy_test_ids: tuple[Identifier, ...]
    known_limitations: tuple[SafeText, ...]
    success_metric_definition: SkillMetricDefinition
    failure_metric_definition: SkillMetricDefinition
    created_at: datetime = Field(default_factory=utc_now)
    promoted_at: datetime | None = None
    supersedes_version: SemanticVersion | None = None
    deprecated_at: datetime | None = None

    _normalise_created_at = field_validator("created_at")(_as_utc)
    _normalise_promoted_at = field_validator("promoted_at")(_as_optional_utc)
    _normalise_deprecated_at = field_validator("deprecated_at")(_as_optional_utc)

    @field_validator(
        "provenance",
        "preconditions",
        "postconditions",
        "allowed_tool_ids",
        "required_capabilities",
        "allowed_execution_lanes",
        "positive_test_ids",
        "negative_test_ids",
        "policy_test_ids",
        "known_limitations",
    )
    @classmethod
    def _unique_tuple(cls, values: tuple[Any, ...]) -> tuple[Any, ...]:
        keys = [
            value.value
            if isinstance(value, Enum)
            else canonical_json(value.model_dump(mode="json"))
            if isinstance(value, BaseModel)
            else str(value)
            for value in values
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("manifest tuple values must be unique")
        return tuple(
            value for _, value in sorted(zip(keys, values), key=lambda item: item[0])
        )

    @model_validator(mode="after")
    def _manifest_contract(self) -> Self:
        if self.schema_version != SKILL_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported skill manifest schema version")
        if not self.provenance:
            raise ValueError("manifest requires provenance")
        if not self.allowed_execution_lanes:
            raise ValueError("manifest requires an execution lane")
        if not self.declarative_steps:
            raise ValueError("manifest requires declarative steps")
        if len(self.declarative_steps) > self.maximum_steps:
            raise ValueError("declarative steps exceed maximum_steps")
        step_ids = [step.step_id for step in self.declarative_steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step IDs must be unique")
        step_tools = {step.tool_id for step in self.declarative_steps}
        if step_tools != set(self.allowed_tool_ids):
            raise ValueError("allowed tools must exactly match declarative step tools")
        input_ids = {field.field_id for field in self.input_schema.fields}
        for step in self.declarative_steps:
            unknown_bindings = set(step.input_binding_ids) - input_ids
            if unknown_bindings:
                raise ValueError("step references an unknown input binding")
        if (
            self.status
            in {
                SkillLifecycleStatus.PROMOTED,
                SkillLifecycleStatus.ACTIVE,
                SkillLifecycleStatus.DEPRECATED,
                SkillLifecycleStatus.ROLLED_BACK,
            }
            and self.promoted_at is None
        ):
            raise ValueError("promoted lifecycle states require promoted_at")
        if (
            self.status is SkillLifecycleStatus.DEPRECATED
            and self.deprecated_at is None
        ):
            raise ValueError("deprecated manifests require deprecated_at")
        if self.deprecated_at is not None and self.promoted_at is None:
            raise ValueError("deprecated_at requires promoted_at")
        for text in _walk_strings(self.model_dump(mode="json")):
            _reject_unsafe_string(text)
        return self

    def validate_tool_bindings(self, catalog: ToolManifestCatalog) -> None:
        """Bind exact tool IDs, capabilities, lanes and risk to trusted manifests."""

        actual_capabilities: set[str] = set()
        for tool_id in self.allowed_tool_ids:
            try:
                tool = catalog.get(tool_id)
            except Exception as exc:
                raise SkillManifestError(f"unknown tool binding: {tool_id}") from exc
            actual_capabilities.add(tool.capability)
            if int(tool.risk_level) > int(self.maximum_risk_level):
                raise SkillManifestError("skill risk is lower than a bound tool risk")
            unsupported = set(self.allowed_execution_lanes) - set(tool.allowed_lanes)
            if unsupported:
                raise SkillManifestError(
                    f"tool {tool_id} does not support every declared execution lane"
                )
        if actual_capabilities != set(self.required_capabilities):
            raise SkillManifestError(
                "required capabilities must exactly match trusted tool capabilities"
            )

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class SkillManifest(SkillManifestDraft):
    content_hash: Digest

    @classmethod
    def create(
        cls,
        draft: SkillManifestDraft | Mapping[str, Any] | None = None,
        **values: Any,
    ) -> SkillManifest:
        if draft is not None and values:
            raise TypeError("provide either draft or keyword values")
        validated = (
            draft
            if isinstance(draft, SkillManifestDraft)
            else SkillManifestDraft.model_validate(
                draft if draft is not None else values
            )
        )
        payload = validated.model_dump(mode="json")
        return cls.model_validate(
            {**payload, "content_hash": manifest_content_hash(payload)}
        )

    @model_validator(mode="after")
    def _content_hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"content_hash"})
        if manifest_content_hash(payload) != self.content_hash:
            raise ValueError("skill manifest content_hash mismatch")
        return self

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"content_hash"})


__all__ = [
    "DeclarativeSkillStep",
    "FailureBehavior",
    "ManifestSchema",
    "ManifestSchemaField",
    "ManifestValueType",
    "MetricKind",
    "RetryPolicy",
    "RollbackKind",
    "RollbackStrategy",
    "SKILL_MANIFEST_SCHEMA_VERSION",
    "SkillIdempotencyPolicy",
    "SkillLifecycleStatus",
    "SkillManifest",
    "SkillManifestDraft",
    "SkillManifestError",
    "SkillMetricDefinition",
    "SkillProvenance",
    "VerificationKind",
    "VerificationStrategy",
    "canonical_json",
    "manifest_content_hash",
    "utc_now",
]
