"""Canonical task types and state-transition rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class TaskStatus(str, Enum):
    """The only canonical task states."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    RECOVERING = "recovering"
    FAILED = "failed"
    DONE = "done"
    CANCELED = "canceled"


class TaskOutcome(str, Enum):
    """Terminal or qualified result without expanding the main state model."""

    COMPLETED = "completed"
    COMPLETED_WITH_BUDGET_WARNING = "completed_with_budget_warning"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
    CANCELED = "canceled"


class ExecutionLane(str, Enum):
    """Resource lane used by one task execution."""

    MODEL = "model_lane"
    INTERACTIVE = "interactive_lane"


class ApprovalKind(str, Enum):
    """Codex actions that can require a user decision."""

    COMMAND = "command"
    FILE_CHANGE = "file_change"


class ApprovalStatus(str, Enum):
    """Persistent broker decision state."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


ALLOWED_TRANSITIONS: Mapping[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.PAUSED,
            TaskStatus.CANCELED,
        }
    ),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.PAUSED,
            TaskStatus.RECOVERING,
            TaskStatus.FAILED,
            TaskStatus.DONE,
            TaskStatus.CANCELED,
        }
    ),
    TaskStatus.WAITING_APPROVAL: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.PAUSED,
            TaskStatus.RECOVERING,
            TaskStatus.FAILED,
            TaskStatus.CANCELED,
        }
    ),
    TaskStatus.PAUSED: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.RECOVERING,
            TaskStatus.CANCELED,
        }
    ),
    TaskStatus.RECOVERING: frozenset(
        {
            TaskStatus.RUNNING,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.PAUSED,
            TaskStatus.FAILED,
            TaskStatus.CANCELED,
        }
    ),
    TaskStatus.FAILED: frozenset({TaskStatus.RECOVERING}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELED: frozenset(),
}


class InvalidTaskTransition(ValueError):
    """Raised when a component requests a forbidden canonical transition."""


@dataclass(frozen=True, slots=True)
class TaskRecord:
    """Persisted canonical task."""

    task_id: str
    session_id: str
    correlation_id: str
    description: str
    status: TaskStatus
    outcome: TaskOutcome | None
    execution_lane: ExecutionLane
    backend: str
    risk_level: int
    created_at: str
    updated_at: str
    version: int
    result: str = ""
    error_category: str | None = None
    active_thread_id: str | None = None
    active_turn_id: str | None = None
    budget_warning: bool = False


@dataclass(frozen=True, slots=True)
class TaskEvent:
    """One committed and ordered task lifecycle event."""

    event_id: str
    task_id: str
    sequence: int
    event_type: str
    occurred_at: str
    cause: str
    component: str
    correlation_id: str
    session_id: str
    status_from: TaskStatus | None = None
    status_to: TaskStatus | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    item_id: str | None = None
    approval_id: str | None = None
    action_id: str | None = None
    artifact_id: str | None = None
    schema_version: str = "1.0"
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskItem:
    """Persisted Codex item correlated to a task, thread, and turn."""

    item_id: str
    task_id: str
    session_id: str
    thread_id: str
    turn_id: str
    item_type: str
    status: str
    sequence: int
    source_event_id: str
    created_at: str
    updated_at: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskSource:
    """External or legacy record that refers to a canonical task."""

    source_id: str
    task_id: str
    source_kind: str
    external_id: str
    created_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskArtifact:
    """Bounded binary/text payload referenced by task events and traces."""

    artifact_id: str
    task_id: str
    kind: str
    media_type: str
    byte_size: int
    sha256: str
    storage_ref: str
    created_at: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """Persistent exact-once Codex approval request."""

    approval_id: str
    request_id: str
    task_id: str
    thread_id: str
    turn_id: str | None
    item_id: str | None
    action_id: str | None
    kind: ApprovalKind
    action: str
    target: str
    effect: str
    risk_level: int
    sandbox: str
    cwd: str
    undo: str
    created_at: str
    expires_at: str
    status: ApprovalStatus
    user_decision: str | None
    decision_at: str | None
    decision_id: str | None
    response_id: str | None
    responded_at: str | None
    payload: Mapping[str, Any] = field(default_factory=dict)


def validate_transition(current: TaskStatus, requested: TaskStatus) -> None:
    """Validate a canonical state transition."""

    if requested not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTaskTransition(
            f"task transition {current.value!r} -> {requested.value!r} is not allowed"
        )


def validate_outcome(status: TaskStatus, outcome: TaskOutcome | None) -> None:
    """Keep result detail consistent with the canonical main state."""

    allowed: dict[TaskStatus, frozenset[TaskOutcome | None]] = {
        TaskStatus.DONE: frozenset(
            {
                TaskOutcome.COMPLETED,
                TaskOutcome.COMPLETED_WITH_BUDGET_WARNING,
            }
        ),
        TaskStatus.FAILED: frozenset(
            {
                TaskOutcome.FAILED,
                TaskOutcome.INTERRUPTED,
            }
        ),
        TaskStatus.CANCELED: frozenset({TaskOutcome.CANCELED}),
    }
    if status in allowed:
        if outcome not in allowed[status]:
            values = ", ".join(
                sorted(value.value for value in allowed[status] if value is not None)
            )
            raise InvalidTaskTransition(
                f"{status.value!r} requires an outcome in: {values}"
            )
    elif outcome is not None:
        raise InvalidTaskTransition(
            f"non-terminal task state {status.value!r} cannot set outcome"
        )


__all__ = [
    "ALLOWED_TRANSITIONS",
    "ApprovalKind",
    "ApprovalRecord",
    "ApprovalStatus",
    "ExecutionLane",
    "InvalidTaskTransition",
    "TaskEvent",
    "TaskArtifact",
    "TaskItem",
    "TaskOutcome",
    "TaskRecord",
    "TaskSource",
    "TaskStatus",
    "validate_outcome",
    "validate_transition",
]
