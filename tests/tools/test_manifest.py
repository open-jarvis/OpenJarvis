"""Phase-5 manifest and strict argument validation invariants."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from openjarvis.core.types import ToolCall, ToolResult
from openjarvis.tasks.policy import RiskLevel
from openjarvis.tasks.types import ExecutionLane
from openjarvis.tools._stubs import BaseTool, ToolExecutor, ToolSpec
from openjarvis.tools.manifest import (
    IdempotencyPolicy,
    ManifestValidationError,
    NetworkPolicy,
    SecretPolicy,
    SideEffectClass,
    ToolManifest,
    ToolManifestCatalog,
)


class EchoTool(BaseTool):
    tool_id = "echo"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="echo",
            description="Echo one bounded string.",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "maxLength": 20},
                },
                "required": ["text"],
            },
        )

    def execute(self, **params) -> ToolResult:
        return ToolResult(tool_name=self.tool_id, content=params["text"])


def test_manifest_contains_every_required_field() -> None:
    payload = EchoTool().manifest.model_dump(mode="json")
    assert set(payload) == {
        "tool_id",
        "name",
        "version",
        "description",
        "input_schema",
        "output_schema",
        "capability",
        "risk_level",
        "allowed_lanes",
        "supported_platforms",
        "timeout",
        "max_retries",
        "idempotency_policy",
        "side_effect_class",
        "verification_strategy",
        "undo_strategy",
        "required_approval",
        "allowed_roots",
        "network_policy",
        "secret_policy",
        "log_redaction_policy",
        "enabled",
        "degraded_reason",
    }
    assert payload["input_schema"]["additionalProperties"] is False


def test_unknown_parameter_is_rejected_before_execute() -> None:
    result = ToolExecutor([EchoTool()]).execute(
        ToolCall(
            id="call-1",
            name="echo",
            arguments='{"text":"safe","permission":"grant"}',
        )
    )
    assert result.success is False
    assert "unknown parameters" in result.content


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ("{}", "required"),
        ('{"text":3}', "expected string"),
        ('{"text":"this string is much too long"}', "too long"),
    ],
)
def test_required_type_and_limit_validation(arguments: str, message: str) -> None:
    result = ToolExecutor([EchoTool()]).execute(
        ToolCall(id="call-1", name="echo", arguments=arguments)
    )
    assert result.success is False
    assert message in result.content


def test_catalog_rejects_unknown_tool() -> None:
    catalog = ToolManifestCatalog.from_tools([EchoTool()])
    with pytest.raises(ManifestValidationError, match="unregistered tool"):
        catalog.get("model_invented_tool")


def test_manifest_rejects_level_four_execution() -> None:
    with pytest.raises(ValidationError, match="level-4 tools must be disabled"):
        ToolManifest(
            tool_id="payment.execute",
            name="payment.execute",
            description="Never executable in Phase 5.",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            capability="financial:execute",
            risk_level=RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL,
            allowed_lanes=(ExecutionLane.INTERACTIVE,),
            supported_platforms=("windows",),
            timeout=10,
            max_retries=0,
            idempotency_policy=IdempotencyPolicy.NEVER_AFTER_UNKNOWN_EFFECT,
            side_effect_class=SideEffectClass.FINANCIAL,
            verification_strategy="simulation_only",
            undo_strategy="none",
            required_approval=True,
            network_policy=NetworkPolicy.DENY,
            secret_policy=SecretPolicy.REJECT,
            log_redaction_policy="all",
            enabled=True,
        )


def test_validated_arguments_are_copied() -> None:
    args = {"text": "safe"}
    validated = EchoTool().manifest.validate_arguments(args)
    assert validated == args
    assert validated is not args
