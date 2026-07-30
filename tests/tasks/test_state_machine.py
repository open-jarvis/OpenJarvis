from __future__ import annotations

import pytest

from openjarvis.tasks.types import (
    ALLOWED_TRANSITIONS,
    InvalidTaskTransition,
    TaskOutcome,
    TaskStatus,
    validate_outcome,
    validate_transition,
)


def test_state_machine_contains_only_the_canonical_states() -> None:
    assert {state.value for state in TaskStatus} == {
        "pending",
        "running",
        "waiting_approval",
        "paused",
        "recovering",
        "failed",
        "done",
        "canceled",
    }
    assert set(ALLOWED_TRANSITIONS) == set(TaskStatus)


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (current, requested)
        for current, requested_states in ALLOWED_TRANSITIONS.items()
        for requested in sorted(requested_states, key=lambda state: state.value)
    ],
)
def test_every_declared_transition_is_accepted(
    current: TaskStatus,
    requested: TaskStatus,
) -> None:
    validate_transition(current, requested)


@pytest.mark.parametrize(
    ("current", "requested"),
    [
        (current, requested)
        for current in TaskStatus
        for requested in TaskStatus
        if requested not in ALLOWED_TRANSITIONS[current]
    ],
)
def test_every_undeclared_transition_is_rejected(
    current: TaskStatus,
    requested: TaskStatus,
) -> None:
    with pytest.raises(InvalidTaskTransition):
        validate_transition(current, requested)


def test_outcome_does_not_expand_the_main_state_model() -> None:
    validate_outcome(TaskStatus.DONE, TaskOutcome.COMPLETED)
    validate_outcome(
        TaskStatus.DONE,
        TaskOutcome.COMPLETED_WITH_BUDGET_WARNING,
    )
    validate_outcome(TaskStatus.FAILED, TaskOutcome.INTERRUPTED)
    validate_outcome(TaskStatus.FAILED, TaskOutcome.FAILED)
    validate_outcome(TaskStatus.CANCELED, TaskOutcome.CANCELED)

    with pytest.raises(InvalidTaskTransition):
        validate_outcome(TaskStatus.RUNNING, TaskOutcome.COMPLETED)
    with pytest.raises(InvalidTaskTransition):
        validate_outcome(TaskStatus.DONE, TaskOutcome.FAILED)
    with pytest.raises(InvalidTaskTransition):
        validate_outcome(TaskStatus.DONE, None)
