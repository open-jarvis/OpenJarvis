"""Versioned, strict security manifests for every executable tool.

The model-facing :class:`~openjarvis.tools._stubs.ToolSpec` remains a
compatibility description.  A ``ToolManifest`` is the trusted OpenJarvis
record used for validation and policy; model text and tool output never
participate in its construction.
"""

from __future__ import annotations

import platform
import re
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.tasks.policy import RiskLevel
from openjarvis.tasks.types import ExecutionLane


class SideEffectClass(str, Enum):
    NONE = "none"
    LOCAL_READ = "local_read"
    REVERSIBLE_LOCAL_WRITE = "reversible_local_write"
    VISIBLE_PREPARATION = "visible_preparation"
    EXTERNAL_WRITE = "external_write"
    DESTRUCTIVE = "destructive"
    FINANCIAL = "financial"
    SECURITY_CRITICAL = "security_critical"


class IdempotencyPolicy(str, Enum):
    SAFE_RETRY = "safe_retry"
    KEY_REQUIRED = "key_required"
    NEVER_AFTER_UNKNOWN_EFFECT = "never_retry_after_unknown_effect"


class NetworkPolicy(str, Enum):
    DENY = "deny"
    LOOPBACK_ONLY = "loopback_only"
    EXPLICIT_ALLOWLIST = "explicit_allowlist"


class SecretPolicy(str, Enum):
    REJECT = "reject"
    REDACT = "redact"
    EXPLICIT_REFERENCE_ONLY = "explicit_reference_only"


class ManifestValidationError(ValueError):
    """Raised when a tool or its arguments violate the trusted manifest."""


def _platform_name() -> str:
    value = platform.system().lower()
    return "darwin" if value == "macos" else value


def _normalise_object_schema(schema: Mapping[str, Any] | None) -> dict[str, Any]:
    value = dict(schema or {})
    value.setdefault("type", "object")
    value.setdefault("properties", {})
    value.setdefault("required", [])
    # OpenJarvis is strict even when an old ToolSpec omitted the keyword.
    value["additionalProperties"] = False
    return value


class ToolManifest(BaseModel):
    """Canonical, versioned policy contract for one tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str = Field(min_length=1, pattern=r"^[a-z0-9_.:-]+$")
    name: str = Field(min_length=1, pattern=r"^[a-z0-9_.:-]+$")
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    capability: str = Field(min_length=1)
    risk_level: RiskLevel
    allowed_lanes: tuple[ExecutionLane, ...]
    supported_platforms: tuple[str, ...]
    timeout: float = Field(gt=0, le=300)
    max_retries: int = Field(ge=0, le=1)
    idempotency_policy: IdempotencyPolicy
    side_effect_class: SideEffectClass
    verification_strategy: str = Field(min_length=1)
    undo_strategy: str = Field(min_length=1)
    required_approval: bool
    allowed_roots: tuple[str, ...] = ()
    network_policy: NetworkPolicy
    secret_policy: SecretPolicy
    log_redaction_policy: str = Field(min_length=1)
    enabled: bool = True
    degraded_reason: str = ""

    @field_validator("input_schema")
    @classmethod
    def _validate_input_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        value = _normalise_object_schema(value)
        if value.get("type") != "object":
            raise ValueError("tool input_schema must describe an object")
        properties = value.get("properties")
        required = value.get("required")
        if not isinstance(properties, dict) or not isinstance(required, list):
            raise ValueError("tool input_schema properties/required are invalid")
        unknown_required = set(required) - set(properties)
        if unknown_required:
            raise ValueError(
                "required fields missing from properties: "
                + ", ".join(sorted(unknown_required))
            )
        return value

    @field_validator("output_schema")
    @classmethod
    def _validate_output_schema(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("output_schema must be a non-empty object")
        return value

    @model_validator(mode="after")
    def _validate_policy_consistency(self) -> "ToolManifest":
        if not self.allowed_lanes:
            raise ValueError("at least one allowed lane is required")
        if not self.supported_platforms:
            raise ValueError("at least one supported platform is required")
        if self.risk_level is RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL:
            if self.enabled:
                raise ValueError("level-4 tools must be disabled in Phase 5")
            if not self.required_approval:
                raise ValueError("level-4 tools must require approval")
        if self.risk_level >= RiskLevel.DESTRUCTIVE_OR_SENSITIVE:
            if not self.required_approval:
                raise ValueError("level-3/4 tools must require approval")
        if not self.enabled and not self.degraded_reason:
            raise ValueError("disabled tools require degraded_reason")
        return self

    def validate_arguments(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        """Validate and copy arguments using the strict manifest schema."""

        if not isinstance(arguments, Mapping):
            raise ManifestValidationError("tool arguments must be an object")
        value = dict(arguments)
        _validate_schema_value(value, self.input_schema, path="$", strict=True)
        return value

    def supports_current_platform(self) -> bool:
        return _platform_name() in self.supported_platforms


_READ_ONLY_NAMES = {
    "browser_axtree",
    "browser_extract",
    "browser_navigate",
    "browser_screenshot",
    "calculator",
    "channel_list",
    "channel_status",
    "file_read",
    "file.list",
    "file.read",
    "file.search",
    "file.stat",
    "git_diff",
    "git.branch",
    "git.diff",
    "git.log",
    "git.status",
    "git_log",
    "git_status",
    "git.bundle.verify",
    "get_pending_actions",
    "knowledge_search",
    "knowledge_sql",
    "list_scheduled_tasks",
    "memory_retrieve",
    "memory_search",
    "retrieval",
    "think",
}
_REVERSIBLE_WRITE_NAMES = {
    "apply_patch",
    "file_write",
    "directory.create",
    "file.copy",
    "file.move",
    "file.patch",
    "file.write",
    "git_commit",
    "git.bundle.create",
    "git.commit",
    "git.worktree.create",
    "kg_add_entity",
    "kg_add_relation",
    "memory_index",
    "memory_manage",
    "memory_store",
    "queue_action",
}
_PREPARATION_NAMES = {"browser_click", "browser_type"}
_SENSITIVE_NAMES = {
    "agent_kill",
    "cancel_scheduled_task",
    "channel_send",
    "code_interpreter",
    "code_interpreter_docker",
    "docker_shell_exec",
    "execute_pending_actions",
    "file.delete",
    "git.restore",
    "git.worktree.remove",
    "repl",
    "schedule_task",
    "shell_exec",
    "shell.exec",
}
_CAPABILITY_BY_NAME = {
    "apply_patch": "file:write",
    "browser_axtree": "network:fetch",
    "browser_click": "network:fetch",
    "browser_extract": "network:fetch",
    "browser_navigate": "network:fetch",
    "browser_screenshot": "network:fetch",
    "browser_type": "network:fetch",
    "file_read": "file:read",
    "file.list": "file:read",
    "file.read": "file:read",
    "file.search": "file:read",
    "file.stat": "file:read",
    "file_write": "file:write",
    "directory.create": "file:write",
    "file.copy": "file:write",
    "file.delete": "file:write",
    "file.move": "file:write",
    "file.patch": "file:write",
    "file.write": "file:write",
    "git_commit": "file:write",
    "git_diff": "file:read",
    "git_log": "file:read",
    "git_status": "file:read",
    "git.branch": "file:read",
    "git.diff": "file:read",
    "git.log": "file:read",
    "git.status": "file:read",
    "git.bundle.verify": "file:read",
    "git.bundle.create": "file:write",
    "git.commit": "file:write",
    "git.restore": "file:write",
    "git.worktree.create": "file:write",
    "git.worktree.remove": "file:write",
}


def manifest_from_spec(tool_id: str, spec: Any) -> ToolManifest:
    """Build a conservative trusted manifest from a legacy ``ToolSpec``."""

    name = str(spec.name)
    capabilities = tuple(str(value) for value in spec.required_capabilities)
    capability = (
        capabilities[0]
        if capabilities
        else _CAPABILITY_BY_NAME.get(name, "tool:invoke")
    )

    if name in _READ_ONLY_NAMES:
        risk = RiskLevel.READ_ONLY
        side_effect = (
            SideEffectClass.LOCAL_READ
            if not name.startswith("browser_")
            else SideEffectClass.NONE
        )
    elif name in _REVERSIBLE_WRITE_NAMES:
        risk = RiskLevel.REVERSIBLE_WORKSPACE
        side_effect = SideEffectClass.REVERSIBLE_LOCAL_WRITE
    elif name in _PREPARATION_NAMES:
        risk = RiskLevel.EXTERNAL_PREPARATION
        side_effect = SideEffectClass.VISIBLE_PREPARATION
    elif name in _SENSITIVE_NAMES or capability in {
        "channel:send",
        "code:execute",
        "system:admin",
    }:
        risk = RiskLevel.DESTRUCTIVE_OR_SENSITIVE
        side_effect = SideEffectClass.EXTERNAL_WRITE
    elif capability.endswith(":write"):
        risk = RiskLevel.REVERSIBLE_WORKSPACE
        side_effect = SideEffectClass.REVERSIBLE_LOCAL_WRITE
    else:
        risk = RiskLevel.READ_ONLY
        side_effect = SideEffectClass.NONE

    browser = name.startswith("browser_")
    lane = ExecutionLane.INTERACTIVE if browser or risk >= 2 else ExecutionLane.MODEL
    network = (
        NetworkPolicy.EXPLICIT_ALLOWLIST
        if browser or capability == "network:fetch"
        else NetworkPolicy.DENY
    )
    retryable = risk is RiskLevel.READ_ONLY
    enabled = risk is not RiskLevel.FINANCIAL_OR_SECURITY_CRITICAL
    return ToolManifest(
        tool_id=str(tool_id),
        name=name,
        description=str(spec.description),
        input_schema=_normalise_object_schema(spec.parameters),
        output_schema={
            "type": "object",
            "properties": {
                "success": {"type": "boolean"},
                "content": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "required": ["success", "content", "metadata"],
            "additionalProperties": False,
        },
        capability=capability,
        risk_level=risk,
        allowed_lanes=(lane,),
        supported_platforms=("windows", "linux", "darwin"),
        timeout=float(spec.timeout_seconds or 30.0),
        max_retries=1 if retryable else 0,
        idempotency_policy=(
            IdempotencyPolicy.SAFE_RETRY
            if retryable
            else IdempotencyPolicy.KEY_REQUIRED
            if risk <= RiskLevel.REVERSIBLE_WORKSPACE
            else IdempotencyPolicy.NEVER_AFTER_UNKNOWN_EFFECT
        ),
        side_effect_class=side_effect,
        verification_strategy=(
            "observe_expected_state" if risk else "validate_result_shape"
        ),
        undo_strategy=(
            "restore_artifact_required"
            if side_effect is SideEffectClass.REVERSIBLE_LOCAL_WRITE
            else "not_applicable"
            if risk is RiskLevel.READ_ONLY
            else "manual_or_tool_specific"
        ),
        required_approval=(
            bool(spec.requires_confirmation)
            or risk >= RiskLevel.DESTRUCTIVE_OR_SENSITIVE
        ),
        allowed_roots=(),
        network_policy=network,
        secret_policy=SecretPolicy.REJECT,
        log_redaction_policy="credentials_and_sensitive_values",
        enabled=enabled,
        degraded_reason=(
            "level-4 execution disabled in Phase 5" if not enabled else ""
        ),
    )


class ToolManifestCatalog:
    """Immutable-by-convention manifest lookup built from trusted tools."""

    def __init__(self, manifests: tuple[ToolManifest, ...]) -> None:
        self._manifests: dict[str, ToolManifest] = {}
        for manifest in manifests:
            if manifest.tool_id in self._manifests:
                raise ManifestValidationError(f"duplicate manifest: {manifest.tool_id}")
            self._manifests[manifest.tool_id] = manifest

    @classmethod
    def from_tools(cls, tools: list[Any]) -> "ToolManifestCatalog":
        return cls(tuple(tool.manifest for tool in tools))

    def get(self, tool_id: str) -> ToolManifest:
        try:
            return self._manifests[tool_id]
        except KeyError as exc:
            raise ManifestValidationError(f"unregistered tool: {tool_id}") from exc

    def list(self) -> tuple[ToolManifest, ...]:
        return tuple(self._manifests.values())


def _validate_schema_value(
    value: Any,
    schema: Mapping[str, Any],
    *,
    path: str,
    strict: bool,
) -> None:
    expected = schema.get("type")
    valid = True
    if expected == "object":
        valid = isinstance(value, Mapping)
    elif expected == "array":
        valid = isinstance(value, list)
    elif expected == "string":
        valid = isinstance(value, str)
    elif expected == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif expected == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif expected == "boolean":
        valid = isinstance(value, bool)
    elif expected == "null":
        valid = value is None
    elif expected is None:
        valid = True
    else:
        raise ManifestValidationError(f"{path}: unsupported schema type {expected!r}")
    if not valid:
        raise ManifestValidationError(f"{path}: expected {expected}")

    if "enum" in schema and value not in schema["enum"]:
        raise ManifestValidationError(f"{path}: value is not in enum")

    if expected == "object":
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ManifestValidationError(f"{path}.{key}: required")
        if strict or schema.get("additionalProperties") is False:
            unknown = set(value) - set(properties)
            if unknown:
                raise ManifestValidationError(
                    f"{path}: unknown parameters: {', '.join(sorted(unknown))}"
                )
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is not None:
                _validate_schema_value(
                    child,
                    child_schema,
                    path=f"{path}.{key}",
                    strict=strict,
                )
    elif expected == "array":
        item_schema = schema.get("items")
        if item_schema:
            for index, child in enumerate(value):
                _validate_schema_value(
                    child,
                    item_schema,
                    path=f"{path}[{index}]",
                    strict=strict,
                )
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ManifestValidationError(f"{path}: too many items")
    elif expected == "string":
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise ManifestValidationError(f"{path}: string is too short")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise ManifestValidationError(f"{path}: string is too long")
        pattern_value = schema.get("pattern")
        if pattern_value and re.search(str(pattern_value), value) is None:
            raise ManifestValidationError(f"{path}: string does not match pattern")


__all__ = [
    "IdempotencyPolicy",
    "ManifestValidationError",
    "NetworkPolicy",
    "SecretPolicy",
    "SideEffectClass",
    "ToolManifest",
    "ToolManifestCatalog",
    "manifest_from_spec",
]
