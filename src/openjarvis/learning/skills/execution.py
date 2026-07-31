"""Canonical, version-pinned skill execution through ``ToolActionService``.

This module never resolves or calls tool functions.  It creates strict
``ToolProposal`` records and delegates policy, allow-once approval, lane
execution and postcondition verification to the central action service.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
import time
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.learning.evaluation.models import Digest, Identifier
from openjarvis.learning.lifecycle.models import ActorType
from openjarvis.learning.skills.manifest import (
    ManifestValueType,
    SkillIdempotencyPolicy,
    SkillIdentifier,
    SkillManifest,
)
from openjarvis.learning.skills.registry import (
    SkillRegistry,
    SkillRegistryError,
    _digest,
    _iso,
    _now,
)
from openjarvis.learning.skills.registry_models import SkillAuditEventType
from openjarvis.learning.store.repository import (
    LearningIntegrityError,
    LearningRecordNotFoundError,
)
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tasks.types import ExecutionLane
from openjarvis.tools.actions import (
    ActionStatus,
    ParameterSource,
    ToolAction,
    ToolProposal,
    VerificationStatus,
)
from openjarvis.tools.manifest import SideEffectClass

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
)


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a UTC offset")
    return value.astimezone(timezone.utc)


class ActionServiceProtocol(Protocol):
    def create(self, proposal: ToolProposal) -> ToolAction: ...

    async def execute(
        self, action_id: str, *, approved_once: bool = False
    ) -> ToolAction: ...

    async def approve(self, action_id: str, *, decision_id: str) -> ToolAction: ...

    def deny(self, action_id: str, *, decision_id: str) -> ToolAction: ...

    async def retry(self, action_id: str) -> ToolAction: ...


class TaskEventStoreProtocol(Protocol):
    def append_event(self, **values: Any) -> tuple[Any, bool]: ...


class TaskTimelineProtocol(Protocol):
    @property
    def store(self) -> TaskEventStoreProtocol: ...

    def project_committed(self, event: Any) -> None: ...


class SkillExecutionError(SkillRegistryError):
    """Canonical execution could not safely advance."""


class SkillApprovalRequired(SkillExecutionError):
    """Execution paused until one exact allow-once or deny decision exists."""

    def __init__(self, *, pin_id: str, step_id: str, action_id: str) -> None:
        super().__init__("skill action requires an explicit allow-once decision")
        self.pin_id = pin_id
        self.step_id = step_id
        self.action_id = action_id


class SkillExecutionOutcome(str, Enum):
    COMPLETED = "completed"
    COMPLETED_WITH_WARNING = "completed_with_warning"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"
    POLICY_DENIED = "policy_denied"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_TIMEOUT = "approval_timeout"
    VERIFICATION_FAILED = "verification_failed"
    CANCELED = "canceled"
    INTERRUPTED = "interrupted"


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class SkillTaskBudget(StrictFrozenModel):
    maximum_steps: int = Field(ge=1, le=64)
    maximum_runtime_seconds: float = Field(gt=0, le=3600)


class ApprovalDecision(StrictFrozenModel):
    allow_once: bool
    decision_id: Identifier


class SkillExecutionRequest(StrictFrozenModel):
    task_id: Identifier
    session_id: Identifier
    correlation_id: Identifier
    thread_id: Identifier
    turn_id: Identifier
    item_id: Identifier
    scope_key: Identifier
    inputs: dict[str, Any]
    execution_lane: ExecutionLane
    task_risk_level: RiskLevel
    untrusted_risk_level: RiskLevel = RiskLevel.READ_ONLY
    external_effect_risk_level: RiskLevel = RiskLevel.READ_ONLY
    budget: SkillTaskBudget
    call_stack: tuple[str, ...] = ()
    approval_decisions: dict[str, ApprovalDecision] = Field(default_factory=dict)
    idempotency_key: Identifier

    @field_validator("call_stack")
    @classmethod
    def _bounded_stack(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) > 8:
            raise ValueError("skill call stack exceeds global maximum depth")
        if len(values) != len(set(values)):
            raise ValueError("skill call stack contains a cycle")
        return values


class _PinPayload(StrictFrozenModel):
    pin_id: Identifier
    task_id: Identifier
    session_id: Identifier
    correlation_id: Identifier
    scope_key: Identifier
    scope_revision: int = Field(ge=1)
    skill_id: SkillIdentifier
    semantic_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    manifest_hash: Digest
    created_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)


class SkillExecutionPin(_PinPayload):
    pin_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillExecutionPin:
        payload = _PinPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "pin_hash": _hash(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"pin_hash"})
        if self.pin_hash != _hash(payload):
            raise ValueError("skill execution pin_hash mismatch")
        return self


class SkillStepExecution(StrictFrozenModel):
    step_id: Identifier
    tool_id: Identifier
    proposal_id: Identifier
    action_id: Identifier
    action_status: ActionStatus
    verification_status: VerificationStatus
    effective_risk_level: RiskLevel
    effect_known: bool
    evidence_reference_ids: tuple[Identifier, ...]

    @field_validator("evidence_reference_ids")
    @classmethod
    def _evidence_required(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(sorted(set(values)))
        if not values:
            raise ValueError("step execution requires evidence references")
        return values


class _ExecutionPayload(StrictFrozenModel):
    execution_id: Identifier
    pin_id: Identifier
    task_id: Identifier
    session_id: Identifier
    correlation_id: Identifier
    scope_key: Identifier
    skill_id: SkillIdentifier
    semantic_version: str
    manifest_hash: Digest
    outcome: SkillExecutionOutcome
    effect_known: bool
    steps: tuple[SkillStepExecution, ...]
    input_digest: Digest
    trace_evaluation_id: Identifier | None = None
    created_at: datetime
    completed_at: datetime

    _normalise_created_at = field_validator("created_at")(_utc)
    _normalise_completed_at = field_validator("completed_at")(_utc)

    @model_validator(mode="after")
    def _time_order(self) -> Self:
        if self.completed_at < self.created_at:
            raise ValueError("skill execution completion precedes creation")
        return self


class SkillExecutionRecord(_ExecutionPayload):
    record_hash: Digest

    @classmethod
    def create(cls, values: Mapping[str, Any]) -> SkillExecutionRecord:
        payload = _ExecutionPayload.model_validate(values).model_dump(mode="json")
        return cls.model_validate({**payload, "record_hash": _hash(payload)})

    @model_validator(mode="after")
    def _hash_matches(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"record_hash"})
        if self.record_hash != _hash(payload):
            raise ValueError("skill execution record_hash mismatch")
        return self


class CanonicalSkillExecutor:
    """Select active versions and execute their tools through one action service."""

    def __init__(
        self,
        registry: SkillRegistry,
        *,
        action_service: ActionServiceProtocol | None,
        task_service: TaskTimelineProtocol | None = None,
    ) -> None:
        self.registry = registry
        self.action_service = action_service
        self.task_service = task_service

    def pin_active(self, request: SkillExecutionRequest) -> SkillExecutionPin:
        """Persist the exact active version selected for a canonical task."""

        request_digest = _digest(
            {
                "operation": "skill.execution.pin",
                "task_id": request.task_id,
                "session_id": request.session_id,
                "correlation_id": request.correlation_id,
                "scope_key": request.scope_key,
            }
        )
        key = f"{request.idempotency_key}.pin"
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=key,
                operation="skill.execution.pin",
                request_digest=request_digest,
            )
            if replay is not None:
                return self._pin(connection, replay["pin_id"])
            row = connection.execute(
                """
                SELECT scope_key, active_skill_id, active_semantic_version,
                       active_manifest_hash, scope_revision
                FROM skill_scope_heads WHERE scope_key = ?
                """,
                (request.scope_key,),
            ).fetchone()
            if row is None:
                raise SkillExecutionError("scope has no active skill version")
            head = self.registry._head(
                connection,
                row["active_skill_id"],
                row["active_semantic_version"],
            )
            if head.lifecycle_state.value != "active":
                raise LearningIntegrityError(
                    "active scope points to a non-active skill"
                )
            if head.manifest_hash != row["active_manifest_hash"]:
                raise LearningIntegrityError("active scope manifest hash mismatch")
            pin = SkillExecutionPin.create(
                {
                    "pin_id": f"skill_pin_{uuid.uuid4().hex}",
                    "task_id": request.task_id,
                    "session_id": request.session_id,
                    "correlation_id": request.correlation_id,
                    "scope_key": request.scope_key,
                    "scope_revision": int(row["scope_revision"]),
                    "skill_id": row["active_skill_id"],
                    "semantic_version": row["active_semantic_version"],
                    "manifest_hash": row["active_manifest_hash"],
                    "created_at": _now(),
                }
            )
            connection.execute(
                """
                INSERT INTO skill_execution_pins(
                    pin_id, task_id, session_id, correlation_id, scope_key,
                    scope_revision, skill_id, semantic_version, manifest_hash,
                    pin_hash, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pin.pin_id,
                    pin.task_id,
                    pin.session_id,
                    pin.correlation_id,
                    pin.scope_key,
                    pin.scope_revision,
                    pin.skill_id,
                    pin.semantic_version,
                    pin.manifest_hash,
                    pin.pin_hash,
                    pin.model_dump_json(),
                    _iso(pin.created_at),
                ),
            )
            self.registry._complete_idempotency(
                connection,
                key=key,
                operation="skill.execution.pin",
                request_digest=request_digest,
                references={"pin_id": pin.pin_id},
            )
            return pin

    async def execute_active(
        self, request: SkillExecutionRequest
    ) -> SkillExecutionRecord:
        if self.action_service is None:
            raise SkillExecutionError("ToolActionService is required")
        pin = self.pin_active(request)
        return await self.execute_pinned(pin.pin_id, request)

    async def execute_pinned(
        self,
        pin_id: str,
        request: SkillExecutionRequest,
    ) -> SkillExecutionRecord:
        service = self.action_service
        if service is None:
            raise SkillExecutionError("ToolActionService is required")
        with self.registry.database.reader() as connection:
            pin = self._pin(connection, pin_id)
            manifest = self.registry._manifest(
                connection, pin.skill_id, pin.semantic_version
            )
        self._validate_pin_request(pin, request)
        self._validate_runtime(manifest, request)
        request_digest = _digest(
            {
                "operation": "skill.execution.run",
                "pin_hash": pin.pin_hash,
                "input_digest": _digest(request.inputs),
                "execution_lane": request.execution_lane.value,
                "task_risk": int(request.task_risk_level),
                "untrusted_risk": int(request.untrusted_risk_level),
                "external_effect_risk": int(request.external_effect_risk_level),
                "approval_decisions": {
                    key: value.model_dump(mode="json")
                    for key, value in sorted(request.approval_decisions.items())
                },
            }
        )
        key = f"{request.idempotency_key}.run"
        with self.registry.database.reader() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=key,
                operation="skill.execution.run",
                request_digest=request_digest,
            )
            if replay is not None:
                record = self._execution(connection, replay["execution_id"])
                self._project_timeline(record)
                return record

        started_at = _now()
        started_monotonic = time.monotonic()
        step_records: list[SkillStepExecution] = []
        outcome = SkillExecutionOutcome.COMPLETED
        effect_known = True
        for step_index, step in enumerate(manifest.declarative_steps):
            if step_index >= min(manifest.maximum_steps, request.budget.maximum_steps):
                outcome = SkillExecutionOutcome.PARTIAL
                break
            if (
                time.monotonic() - started_monotonic
                >= request.budget.maximum_runtime_seconds
            ):
                outcome = SkillExecutionOutcome.PARTIAL
                break
            tool = self.registry.tool_catalog.get(step.tool_id)
            effective_risk = self._effective_risk(manifest, tool, request)
            if effective_risk is RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL:
                outcome = SkillExecutionOutcome.POLICY_DENIED
                break
            arguments = {
                binding: request.inputs[binding] for binding in step.input_binding_ids
            }
            proposal = ToolProposal(
                proposal_id=(
                    "proposal_"
                    + _hash(
                        {
                            "pin_hash": pin.pin_hash,
                            "step_id": step.step_id,
                            "idempotency_key": request.idempotency_key,
                        }
                    )[:32]
                ),
                task_id=request.task_id,
                session_id=request.session_id,
                correlation_id=request.correlation_id,
                thread_id=request.thread_id,
                turn_id=request.turn_id,
                item_id=request.item_id,
                tool_id=step.tool_id,
                arguments=arguments,
                expected_result="; ".join(step.postconditions),
                expected_side_effect=tool.side_effect_class,
                risk_level=effective_risk,
                capability=tool.capability,
                target=f"skill:{pin.skill_id}:{step.step_id}",
                verification_plan="; ".join(step.postconditions),
                undo_plan=manifest.rollback_strategy.kind.value,
                idempotency_key=(
                    "skill_action_"
                    + _hash(
                        {
                            "pin_hash": pin.pin_hash,
                            "step_id": step.step_id,
                            "idempotency_key": request.idempotency_key,
                        }
                    )
                ),
                timeout_seconds=min(manifest.timeout_seconds, tool.timeout),
                rationale=step.purpose,
                parameter_sources={
                    binding: ParameterSource.TASK for binding in arguments
                },
            )
            action = service.create(proposal)
            decision = request.approval_decisions.get(step.step_id)
            if action.status is ActionStatus.WAITING_APPROVAL:
                if decision is None:
                    raise SkillApprovalRequired(
                        pin_id=pin.pin_id,
                        step_id=step.step_id,
                        action_id=action.action_id,
                    )
                if decision.allow_once:
                    action = await self._within_budget(
                        service.approve(
                            action.action_id, decision_id=decision.decision_id
                        ),
                        started_monotonic=started_monotonic,
                        budget=request.budget,
                    )
                else:
                    action = service.deny(
                        action.action_id, decision_id=decision.decision_id
                    )
            elif action.status is ActionStatus.VALIDATED:
                try:
                    action = await self._within_budget(
                        service.execute(action.action_id),
                        started_monotonic=started_monotonic,
                        budget=request.budget,
                    )
                except TimeoutError:
                    action = action.model_copy(
                        update={
                            "status": ActionStatus.FAILED,
                            "verification_status": VerificationStatus.UNKNOWN,
                            "effect_known": False,
                            "error": "skill task budget elapsed during action",
                        }
                    )
            if (
                action.status is ActionStatus.FAILED
                and action.effect_known
                and manifest.retry_policy.maximum_retries > 0
                and manifest.idempotency_policy is SkillIdempotencyPolicy.SAFE_RETRY
            ):
                try:
                    action = await self._within_budget(
                        service.retry(action.action_id),
                        started_monotonic=started_monotonic,
                        budget=request.budget,
                    )
                except TimeoutError:
                    action = action.model_copy(
                        update={
                            "status": ActionStatus.FAILED,
                            "verification_status": VerificationStatus.UNKNOWN,
                            "effect_known": False,
                            "error": "skill task budget elapsed during retry",
                        }
                    )
            step_record = self._step_record(step.step_id, effective_risk, action)
            step_records.append(step_record)
            effect_known = effect_known and action.effect_known
            if action.status is ActionStatus.DENIED:
                outcome = (
                    SkillExecutionOutcome.APPROVAL_DENIED
                    if action.approval_id
                    else SkillExecutionOutcome.POLICY_DENIED
                )
                break
            if action.status is ActionStatus.CANCELED:
                outcome = SkillExecutionOutcome.CANCELED
                break
            if (
                action.status is not ActionStatus.COMPLETED
                or action.verification_status is not VerificationStatus.PASSED
            ):
                if not action.effect_known:
                    outcome = SkillExecutionOutcome.UNKNOWN
                elif action.verification_status is VerificationStatus.FAILED:
                    outcome = SkillExecutionOutcome.VERIFICATION_FAILED
                else:
                    outcome = SkillExecutionOutcome.FAILED
                break

        completed_at = _now()
        record = SkillExecutionRecord.create(
            {
                "execution_id": f"skill_execution_{uuid.uuid4().hex}",
                "pin_id": pin.pin_id,
                "task_id": pin.task_id,
                "session_id": pin.session_id,
                "correlation_id": pin.correlation_id,
                "scope_key": pin.scope_key,
                "skill_id": pin.skill_id,
                "semantic_version": pin.semantic_version,
                "manifest_hash": pin.manifest_hash,
                "outcome": outcome,
                "effect_known": effect_known,
                "steps": tuple(step_records),
                "input_digest": _digest(request.inputs),
                "created_at": started_at,
                "completed_at": completed_at,
            }
        )
        persisted = self._persist_execution(
            record, key=key, request_digest=request_digest
        )
        self._project_timeline(persisted)
        return persisted

    @staticmethod
    async def _within_budget(awaitable, *, started_monotonic: float, budget):
        remaining = budget.maximum_runtime_seconds - (
            time.monotonic() - started_monotonic
        )
        if remaining <= 0:
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise TimeoutError("skill task budget elapsed")
        return await asyncio.wait_for(awaitable, timeout=remaining)

    def get_execution(self, execution_id: str) -> SkillExecutionRecord:
        with self.registry.database.reader() as connection:
            return self._execution(connection, execution_id)

    @staticmethod
    def _validate_pin_request(
        pin: SkillExecutionPin, request: SkillExecutionRequest
    ) -> None:
        if (
            pin.task_id != request.task_id
            or pin.session_id != request.session_id
            or pin.correlation_id != request.correlation_id
            or pin.scope_key != request.scope_key
        ):
            raise SkillExecutionError("execution request differs from version pin")

    def _validate_runtime(
        self, manifest: SkillManifest, request: SkillExecutionRequest
    ) -> None:
        manifest.validate_tool_bindings(self.registry.tool_catalog)
        reference = f"{manifest.skill_id}@{manifest.semantic_version}"
        if reference in request.call_stack:
            raise SkillExecutionError("skill call cycle detected")
        if len(request.call_stack) + 1 > manifest.maximum_call_depth:
            raise SkillExecutionError("skill maximum call depth exceeded")
        if request.execution_lane not in manifest.allowed_execution_lanes:
            raise SkillExecutionError("skill is not allowed in the requested lane")
        self._validate_inputs(manifest, request.inputs)

    @staticmethod
    def _validate_inputs(manifest: SkillManifest, inputs: Mapping[str, Any]) -> None:
        fields = {field.field_id: field for field in manifest.input_schema.fields}
        unknown = set(inputs) - set(fields)
        missing = {key for key, field in fields.items() if field.required} - set(inputs)
        if unknown:
            raise SkillExecutionError("skill input contains unknown fields")
        if missing:
            raise SkillExecutionError("skill input is missing required fields")
        checks = {
            ManifestValueType.STRING: lambda value: isinstance(value, str),
            ManifestValueType.INTEGER: lambda value: (
                isinstance(value, int) and not isinstance(value, bool)
            ),
            ManifestValueType.NUMBER: lambda value: (
                isinstance(value, (int, float)) and not isinstance(value, bool)
            ),
            ManifestValueType.BOOLEAN: lambda value: isinstance(value, bool),
            ManifestValueType.ARRAY: lambda value: isinstance(value, list),
            ManifestValueType.OBJECT: lambda value: isinstance(value, dict),
        }
        for key, value in inputs.items():
            if not checks[fields[key].value_type](value):
                raise SkillExecutionError(f"skill input type mismatch: {key}")
        for text in CanonicalSkillExecutor._strings(inputs):
            if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
                raise SkillExecutionError("skill input contains secret-like material")

    @staticmethod
    def _strings(value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, Mapping):
            return tuple(
                text
                for child in value.values()
                for text in CanonicalSkillExecutor._strings(child)
            )
        if isinstance(value, (list, tuple)):
            return tuple(
                text
                for child in value
                for text in CanonicalSkillExecutor._strings(child)
            )
        return ()

    @staticmethod
    def _effective_risk(manifest: SkillManifest, tool, request) -> RiskLevel:
        side_effect_risk = {
            SideEffectClass.NONE: RiskLevel.READ_ONLY,
            SideEffectClass.LOCAL_READ: RiskLevel.READ_ONLY,
            SideEffectClass.REVERSIBLE_LOCAL_WRITE: RiskLevel.REVERSIBLE_WORKSPACE,
            SideEffectClass.VISIBLE_PREPARATION: RiskLevel.EXTERNAL_PREPARATION,
            SideEffectClass.EXTERNAL_WRITE: RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
            SideEffectClass.DESTRUCTIVE: RiskLevel.DESTRUCTIVE_OR_SENSITIVE,
            SideEffectClass.FINANCIAL: RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL,
            SideEffectClass.SECURITY_CRITICAL: (
                RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL
            ),
        }[tool.side_effect_class]
        return RiskLevel(
            max(
                int(manifest.maximum_risk_level),
                int(tool.risk_level),
                int(request.task_risk_level),
                int(request.untrusted_risk_level),
                int(request.external_effect_risk_level),
                int(side_effect_risk),
            )
        )

    @staticmethod
    def _step_record(
        step_id: str, effective_risk: RiskLevel, action: ToolAction
    ) -> SkillStepExecution:
        references = [action.action_id, action.proposal_id]
        if action.tool_run_id:
            references.append(action.tool_run_id)
        return SkillStepExecution(
            step_id=step_id,
            tool_id=action.tool_id,
            proposal_id=action.proposal_id,
            action_id=action.action_id,
            action_status=action.status,
            verification_status=action.verification_status,
            effective_risk_level=effective_risk,
            effect_known=action.effect_known,
            evidence_reference_ids=tuple(references),
        )

    def _persist_execution(
        self,
        record: SkillExecutionRecord,
        *,
        key: str,
        request_digest: str,
    ) -> SkillExecutionRecord:
        with self.registry.database.transaction() as connection:
            replay = self.registry._check_idempotency(
                connection,
                key=key,
                operation="skill.execution.run",
                request_digest=request_digest,
            )
            if replay is not None:
                return self._execution(connection, replay["execution_id"])
            connection.execute(
                """
                INSERT INTO skill_execution_records(
                    execution_id, task_id, session_id, correlation_id,
                    scope_key, skill_id, semantic_version, manifest_hash,
                    outcome, effect_known, record_hash, payload_json,
                    created_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.execution_id,
                    record.task_id,
                    record.session_id,
                    record.correlation_id,
                    record.scope_key,
                    record.skill_id,
                    record.semantic_version,
                    record.manifest_hash,
                    record.outcome.value,
                    int(record.effect_known),
                    record.record_hash,
                    record.model_dump_json(),
                    _iso(record.created_at),
                    _iso(record.completed_at),
                ),
            )
            event_type = (
                SkillAuditEventType.EXECUTION_COMPLETED
                if record.outcome
                in {
                    SkillExecutionOutcome.COMPLETED,
                    SkillExecutionOutcome.COMPLETED_WITH_WARNING,
                }
                else SkillAuditEventType.EXECUTION_FAILED
            )
            for kind, timestamp in (
                (SkillAuditEventType.EXECUTION_STARTED, record.created_at),
                (event_type, record.completed_at),
            ):
                self.registry._append_event(
                    connection,
                    event_type=kind,
                    skill_id=record.skill_id,
                    semantic_version=record.semantic_version,
                    candidate_id=self.registry._head(
                        connection, record.skill_id, record.semantic_version
                    ).candidate_id,
                    candidate_revision=self.registry._head(
                        connection, record.skill_id, record.semantic_version
                    ).candidate_revision,
                    task_id=record.task_id,
                    session_id=record.session_id,
                    correlation_id=record.correlation_id,
                    actor_type=ActorType.SYSTEM_POLICY,
                    actor_id="canonical_skill_runtime",
                    reason_code=f"execution_{record.outcome.value}",
                    reference_ids=(record.execution_id, record.pin_id)
                    + tuple(step.action_id for step in record.steps),
                    created_at=timestamp,
                )
            self.registry._complete_idempotency(
                connection,
                key=key,
                operation="skill.execution.run",
                request_digest=request_digest,
                references={"execution_id": record.execution_id},
            )
            return record

    def _project_timeline(self, record: SkillExecutionRecord) -> None:
        service = self.task_service
        if service is None:
            return
        final_event = (
            "skill.execution_completed"
            if record.outcome
            in {
                SkillExecutionOutcome.COMPLETED,
                SkillExecutionOutcome.COMPLETED_WITH_WARNING,
            }
            else "skill.execution_failed"
        )
        references = sorted(
            {
                record.execution_id,
                record.pin_id,
                record.skill_id,
                record.semantic_version,
                *(step.action_id for step in record.steps),
            }
        )
        for suffix, event_type, occurred_at in (
            ("started", "skill.execution_started", record.created_at),
            ("finished", final_event, record.completed_at),
        ):
            event, created = service.store.append_event(
                task_id=record.task_id,
                source_event_id=(
                    f"phase7-skill-execution:{record.execution_id}:{suffix}"
                ),
                event_type=event_type,
                occurred_at=_iso(occurred_at),
                cause=f"canonical_skill_{record.outcome.value}",
                component="canonical_skill_runtime",
                payload={
                    "reference_ids": references,
                    "hashes": [record.manifest_hash, record.record_hash],
                    "effect_known": record.effect_known,
                    "metadata_only": True,
                },
            )
            if created:
                service.project_committed(event)

    @staticmethod
    def _pin(connection: sqlite3.Connection, pin_id: str) -> SkillExecutionPin:
        row = connection.execute(
            """
            SELECT pin_id, task_id, session_id, correlation_id, scope_key,
                   scope_revision, skill_id, semantic_version, manifest_hash,
                   pin_hash, payload_json, created_at
            FROM skill_execution_pins WHERE pin_id = ?
            """,
            (pin_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("skill execution pin not found")
        try:
            pin = SkillExecutionPin.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError(
                "skill execution pin integrity failure"
            ) from exc
        columns = {
            "pin_id": row["pin_id"],
            "task_id": row["task_id"],
            "session_id": row["session_id"],
            "correlation_id": row["correlation_id"],
            "scope_key": row["scope_key"],
            "scope_revision": int(row["scope_revision"]),
            "skill_id": row["skill_id"],
            "semantic_version": row["semantic_version"],
            "manifest_hash": row["manifest_hash"],
            "pin_hash": row["pin_hash"],
            "created_at": row["created_at"],
        }
        expected = pin.model_dump(mode="json")
        expected["created_at"] = _iso(pin.created_at)
        if columns != expected:
            raise LearningIntegrityError("skill execution pin index failure")
        return pin

    @staticmethod
    def _execution(
        connection: sqlite3.Connection, execution_id: str
    ) -> SkillExecutionRecord:
        row = connection.execute(
            """
            SELECT execution_id, task_id, session_id, correlation_id,
                   scope_key, skill_id, semantic_version, manifest_hash,
                   outcome, effect_known, record_hash, payload_json,
                   created_at, completed_at
            FROM skill_execution_records WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()
        if row is None:
            raise LearningRecordNotFoundError("skill execution not found")
        try:
            record = SkillExecutionRecord.model_validate_json(row["payload_json"])
        except Exception as exc:
            raise LearningIntegrityError("skill execution integrity failure") from exc
        if (
            record.execution_id != row["execution_id"]
            or record.task_id != row["task_id"]
            or record.session_id != row["session_id"]
            or record.correlation_id != row["correlation_id"]
            or record.scope_key != row["scope_key"]
            or record.skill_id != row["skill_id"]
            or record.semantic_version != row["semantic_version"]
            or record.manifest_hash != row["manifest_hash"]
            or record.outcome.value != row["outcome"]
            or int(record.effect_known) != int(row["effect_known"])
            or record.record_hash != row["record_hash"]
            or _iso(record.created_at) != row["created_at"]
            or _iso(record.completed_at) != row["completed_at"]
        ):
            raise LearningIntegrityError("skill execution index integrity failure")
        return record


__all__ = [
    "ActionServiceProtocol",
    "ApprovalDecision",
    "CanonicalSkillExecutor",
    "SkillApprovalRequired",
    "SkillExecutionError",
    "SkillExecutionOutcome",
    "SkillExecutionPin",
    "SkillExecutionRecord",
    "SkillExecutionRequest",
    "SkillStepExecution",
    "SkillTaskBudget",
]
