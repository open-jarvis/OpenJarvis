"""Shared types and safety invariants for Codex backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping


class CodexBackendKind(str, Enum):
    """Supported Codex transport implementations."""

    PYTHON_SDK = "python_sdk"
    APP_SERVER = "app_server"
    CLI_FALLBACK = "cli_fallback"


class ApprovalMode(str, Enum):
    """Approval policies understood by the OpenJarvis Codex layer."""

    DENY_ALL = "deny_all"
    BROKERED = "brokered"
    # Retained for configuration compatibility only. Phase 3 never permits
    # model-based auto review to authorize a Codex action.
    AUTO_REVIEW = "auto_review"


class SandboxMode(str, Enum):
    """Filesystem policies exposed by the OpenJarvis Codex layer."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    FULL_ACCESS = "full_access"


class CodexEventType(str, Enum):
    """Stable event taxonomy emitted by every Codex backend."""

    THREAD_STARTED = "thread.started"
    THREAD_RESUMED = "thread.resumed"
    THREAD_CLOSED = "thread.closed"
    TURN_STARTED = "turn.started"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"
    TURN_INTERRUPTED = "turn.interrupted"
    ITEM_STARTED = "item.started"
    ITEM_DELTA = "item.delta"
    ITEM_COMPLETED = "item.completed"
    PLAN_UPDATED = "plan.updated"
    COMMAND_STARTED = "command.started"
    COMMAND_OUTPUT = "command.output"
    COMMAND_COMPLETED = "command.completed"
    FILE_CHANGE_PROPOSED = "file_change.proposed"
    FILE_CHANGE_APPLIED = "file_change.applied"
    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_RESOLVED = "approval.resolved"
    USAGE_UPDATED = "usage.updated"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    """Capability matrix advertised by a backend."""

    persistent_threads: bool
    resume: bool
    fork: bool
    streaming: bool
    steer: bool
    interrupt: bool
    command_approvals: bool
    file_approvals: bool
    full_item_events: bool
    usage_events: bool
    read_only: bool
    workspace_write: bool

    def as_dict(self) -> dict[str, bool]:
        """Return a serializable, explicit capability matrix."""

        return {
            "persistent_threads": self.persistent_threads,
            "resume": self.resume,
            "fork": self.fork,
            "streaming": self.streaming,
            "steer": self.steer,
            "interrupt": self.interrupt,
            "command_approvals": self.command_approvals,
            "file_approvals": self.file_approvals,
            "full_item_events": self.full_item_events,
            "usage_events": self.usage_events,
            "read_only": self.read_only,
            "workspace_write": self.workspace_write,
        }


@dataclass(frozen=True, slots=True)
class CodexModelConfig:
    """Explicit model settings passed to Codex."""

    model: str | None
    effort: str | None
    service_tier: str | None


@dataclass(frozen=True, slots=True)
class CodexRunContext:
    """Required security and correlation context for a thread or turn."""

    task_id: str
    session_id: str
    correlation_id: str
    cwd: Path
    sandbox: SandboxMode
    approval_mode: ApprovalMode
    model: CodexModelConfig
    timeout_seconds: float
    step_limit: int
    token_limit: int | None
    developer_instructions: str | None
    isolated_workspace: Path | None

    def validated(self) -> CodexRunContext:
        """Validate all security-sensitive fields without implicit fallback."""

        for field_name in ("task_id", "session_id", "correlation_id"):
            if not getattr(self, field_name).strip():
                raise CodexPolicyError(f"{field_name} must be explicit and non-empty")

        cwd = self.cwd.resolve(strict=False)
        if not cwd.is_absolute():
            raise CodexPolicyError("cwd must be an absolute path")
        if not cwd.exists() or not cwd.is_dir():
            raise CodexPolicyError("cwd must be an existing directory")

        if self.approval_mode is ApprovalMode.AUTO_REVIEW:
            raise CodexPolicyError("automatic approval review is prohibited")
        if self.sandbox is SandboxMode.FULL_ACCESS:
            raise CodexPolicyError("full_access is prohibited")

        if self.sandbox is SandboxMode.WORKSPACE_WRITE:
            if self.isolated_workspace is None:
                raise CodexPolicyError(
                    "workspace_write requires an explicit isolated workspace"
                )
            root = self.isolated_workspace.resolve(strict=False)
            if not root.exists() or not root.is_dir():
                raise CodexPolicyError(
                    "isolated workspace must be an existing directory"
                )
            try:
                cwd.relative_to(root)
            except ValueError as exc:
                raise CodexPolicyError(
                    "workspace_write cwd must remain inside the isolated workspace"
                ) from exc

        if self.timeout_seconds <= 0:
            raise CodexPolicyError("timeout_seconds must be greater than zero")
        if self.step_limit <= 0:
            raise CodexPolicyError("step_limit must be greater than zero")
        if self.token_limit is not None and self.token_limit <= 0:
            raise CodexPolicyError("token_limit must be positive when provided")
        return self


@dataclass(frozen=True, slots=True)
class ThreadStartRequest:
    """Request to create a non-ephemeral Codex thread."""

    context: CodexRunContext


@dataclass(frozen=True, slots=True)
class ThreadResumeRequest:
    """Request to resume a persisted Codex thread."""

    context: CodexRunContext
    thread_id: str | None


@dataclass(frozen=True, slots=True)
class ThreadForkRequest:
    """Request to fork a persisted Codex thread."""

    context: CodexRunContext
    source_thread_id: str


@dataclass(frozen=True, slots=True)
class TurnStartRequest:
    """Request to start a turn on an existing thread."""

    context: CodexRunContext
    thread_id: str
    prompt: str


@dataclass(frozen=True, slots=True)
class BackendThread:
    """Backend-independent thread reference."""

    thread_id: str
    backend: CodexBackendKind
    task_id: str
    session_id: str
    status: str


@dataclass(frozen=True, slots=True)
class BackendTurn:
    """Backend-independent active turn reference."""

    turn_id: str
    thread_id: str
    backend: CodexBackendKind
    status: str


@dataclass(frozen=True, slots=True)
class CodexHealth:
    """Credential-safe backend health report."""

    available: bool
    authenticated: bool
    auth_mode: str | None
    runtime_version: str | None
    backend: CodexBackendKind
    capabilities: BackendCapabilities
    degraded_backend: bool = False
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class CodexEvent:
    """Normalized, versioned Codex lifecycle event."""

    event_id: str
    sequence: int
    occurred_at: str
    task_id: str
    session_id: str
    thread_id: str
    turn_id: str | None
    item_id: str | None
    backend: CodexBackendKind
    event_type: CodexEventType
    schema_version: str = "1.0"
    payload: Mapping[str, Any] = field(default_factory=dict)


class CodexBackendError(RuntimeError):
    """Base error normalized across Codex transports."""


class CodexPolicyError(CodexBackendError):
    """Raised when a request violates an OpenJarvis safety invariant."""


class CodexAuthenticationError(CodexBackendError):
    """Raised when the active Codex account is not an accepted ChatGPT login."""


class CodexCapabilityError(CodexBackendError):
    """Raised when a degraded backend cannot perform an operation."""


class CodexTimeoutError(CodexBackendError):
    """Raised when a bounded backend operation exceeds its deadline."""


__all__ = [
    "ApprovalMode",
    "BackendCapabilities",
    "BackendThread",
    "BackendTurn",
    "CodexAuthenticationError",
    "CodexBackendError",
    "CodexBackendKind",
    "CodexCapabilityError",
    "CodexEvent",
    "CodexEventType",
    "CodexHealth",
    "CodexModelConfig",
    "CodexPolicyError",
    "CodexRunContext",
    "CodexTimeoutError",
    "SandboxMode",
    "ThreadForkRequest",
    "ThreadResumeRequest",
    "ThreadStartRequest",
    "TurnStartRequest",
]
