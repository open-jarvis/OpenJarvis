"""Strict manifest and read-only legacy adapter tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from openjarvis.learning.candidates.models import CandidateScope
from openjarvis.learning.evaluation.models import EvidenceType
from openjarvis.learning.skills.legacy import LegacySkillAdapter
from openjarvis.learning.skills.manifest import (
    DeclarativeSkillStep,
    FailureBehavior,
    ManifestSchema,
    ManifestSchemaField,
    ManifestValueType,
    MetricKind,
    RetryPolicy,
    RollbackKind,
    RollbackStrategy,
    SkillIdempotencyPolicy,
    SkillLifecycleStatus,
    SkillManifest,
    SkillManifestDraft,
    SkillManifestError,
    SkillMetricDefinition,
    SkillProvenance,
    VerificationKind,
    VerificationStrategy,
)
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tasks.types import ExecutionLane
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.manifest import ToolManifestCatalog


class _ReadTool(BaseTool):
    tool_id = "file.read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="file.read",
            description="Read one synthetic fixture.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            required_capabilities=["file:read"],
        )

    def execute(self, **params):  # pragma: no cover - must never execute here
        raise AssertionError("manifest validation executed a tool")


def valid_draft(**updates) -> SkillManifestDraft:
    now = datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc)
    values = {
        "skill_id": "skill.synthetic-read",
        "name": "synthetic-read",
        "semantic_version": "1.0.0",
        "description": "Read a bounded synthetic fixture and verify its digest.",
        "scope": CandidateScope.PROJECT,
        "status": SkillLifecycleStatus.DRAFT,
        "origin_candidate_id": "candidate_fixture",
        "origin_candidate_revision": 2,
        "provenance": (
            SkillProvenance(
                provenance_id="provenance_fixture",
                source_kind="deterministic_test",
                source_id="fixture_source",
                source_digest="a" * 64,
                evidence_digest="b" * 64,
                created_at=now,
            ),
        ),
        "input_schema": ManifestSchema(
            fields=(
                ManifestSchemaField(
                    field_id="path",
                    value_type=ManifestValueType.STRING,
                    required=True,
                    description="Relative path inside the synthetic workspace.",
                ),
            )
        ),
        "output_schema": ManifestSchema(
            fields=(
                ManifestSchemaField(
                    field_id="digest",
                    value_type=ManifestValueType.STRING,
                    required=True,
                    description="Verified content digest.",
                ),
            )
        ),
        "preconditions": ("Synthetic workspace exists.",),
        "postconditions": ("Returned digest matches the fixture.",),
        "allowed_tool_ids": ("file.read",),
        "required_capabilities": ("file:read",),
        "maximum_risk_level": RiskLevel.READ_ONLY,
        "allowed_execution_lanes": (ExecutionLane.MODEL,),
        "timeout_seconds": 10,
        "maximum_steps": 1,
        "maximum_call_depth": 1,
        "retry_policy": RetryPolicy(),
        "idempotency_policy": SkillIdempotencyPolicy.KEY_REQUIRED,
        "declarative_steps": (
            DeclarativeSkillStep(
                step_id="read_fixture",
                purpose="Read the exact synthetic fixture.",
                tool_id="file.read",
                input_binding_ids=("path",),
                expected_evidence_types=(EvidenceType.TOOL_RESULT,),
                preconditions=("Path is inside the synthetic root.",),
                postconditions=("A digest is available.",),
                on_failure=FailureBehavior.ABORT,
            ),
        ),
        "verification_strategy": VerificationStrategy(
            kind=VerificationKind.TOOL_VERIFIER,
            required_evidence_types=(EvidenceType.VERIFICATION_RESULT,),
        ),
        "rollback_strategy": RollbackStrategy(
            kind=RollbackKind.NO_EFFECT,
            verification_reference_ids=("rollback_no_effect",),
        ),
        "positive_test_ids": ("test_positive",),
        "negative_test_ids": ("test_negative",),
        "policy_test_ids": ("test_policy",),
        "known_limitations": ("Only synthetic fixture roots are supported.",),
        "success_metric_definition": SkillMetricDefinition(
            metric_id="verified_successes",
            kind=MetricKind.COUNT,
            qualifying_outcomes=("completed", "completed_with_warning"),
        ),
        "failure_metric_definition": SkillMetricDefinition(
            metric_id="verified_failures",
            kind=MetricKind.COUNT,
            qualifying_outcomes=("failed", "verification_failed"),
        ),
        "created_at": now,
    }
    values.update(updates)
    return SkillManifestDraft.model_validate(values)


def test_strict_versioned_manifest_hash_and_tool_binding() -> None:
    manifest = SkillManifest.create(valid_draft())
    manifest.validate_tool_bindings(ToolManifestCatalog.from_tools([_ReadTool()]))
    assert manifest.semantic_version == "1.0.0"
    assert len(manifest.content_hash) == 64
    with pytest.raises(ValidationError, match="content_hash mismatch"):
        SkillManifest.model_validate(
            {**manifest.model_dump(mode="json"), "content_hash": "0" * 64}
        )


def test_unknown_manifest_field_is_rejected() -> None:
    payload = valid_draft().model_dump(mode="json")
    payload["permission"] = "grant"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SkillManifestDraft.model_validate(payload)


@pytest.mark.parametrize(
    "unsafe",
    [
        "sk-abcdefghijklmnopqrstuvwxyz012345",
        "eval(user_input)",
        "exec(user_input)",
        "pickle.loads(blob)",
        "powershell -Command unsafe",
        "https://hidden.invalid/payload",
        "full_access",
        "always allow",
        "chain-of-thought",
    ],
)
def test_manifest_rejects_unsafe_or_private_content(unsafe: str) -> None:
    with pytest.raises(ValidationError):
        valid_draft(description=unsafe)


def test_unbound_and_unknown_tools_are_rejected() -> None:
    with pytest.raises(ValidationError, match="exactly match"):
        valid_draft(allowed_tool_ids=("file.read", "invented.tool"))
    manifest = SkillManifest.create(valid_draft())
    with pytest.raises(SkillManifestError, match="unknown tool"):
        manifest.validate_tool_bindings(ToolManifestCatalog(()))


def test_capability_and_risk_cannot_be_escalated_or_lowered() -> None:
    manifest = SkillManifest.create(valid_draft(required_capabilities=("file:write",)))
    with pytest.raises(SkillManifestError, match="capabilities"):
        manifest.validate_tool_bindings(ToolManifestCatalog.from_tools([_ReadTool()]))


def test_manifest_is_immutable() -> None:
    manifest = SkillManifest.create(valid_draft())
    with pytest.raises(ValidationError):
        manifest.name = "changed"  # type: ignore[misc]


def test_legacy_adapter_is_read_only_and_quarantines_metadata(tmp_path: Path) -> None:
    fixture = tmp_path / "skill.toml"
    content = """
[skill]
name = "legacy-fixture"
version = "0.1.0"
description = "Untrusted fixture"
unknown_permission = "grant"

[[skill.steps]]
tool_name = "file.read"
arguments_template = "{}"
""".strip()
    fixture.write_text(content, encoding="utf-8")
    before = fixture.read_bytes()

    assessment = LegacySkillAdapter().inspect(fixture)

    assert assessment.quarantined is True
    assert assessment.draft is None
    assert "skill.unknown_permission" in assessment.unknown_fields
    assert "untrusted_executable_steps" in assessment.findings
    assert fixture.read_bytes() == before
    assert tuple(tmp_path.iterdir()) == (fixture,)


def test_legacy_adapter_rejects_unsupported_file(tmp_path: Path) -> None:
    fixture = tmp_path / "run.py"
    fixture.write_text("print('must not run')", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported"):
        LegacySkillAdapter().inspect(fixture)
