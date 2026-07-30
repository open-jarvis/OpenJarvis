from __future__ import annotations

from pathlib import Path

from openjarvis.codex.types import (
    CodexBackendKind,
    CodexEvent,
    CodexEventType,
)
from openjarvis.tasks import (
    BudgetController,
    BudgetLimits,
    TaskService,
    TaskStore,
)


def _event(
    event_id: str,
    *,
    turn_input: int,
    turn_output: int,
    thread_input: int = 0,
    thread_output: int = 0,
) -> CodexEvent:
    return CodexEvent(
        event_id=event_id,
        sequence=1,
        occurred_at="2026-07-30T00:00:00+00:00",
        task_id="task",
        session_id="session",
        thread_id="thread",
        turn_id="turn",
        item_id=None,
        backend=CodexBackendKind.PYTHON_SDK,
        event_type=CodexEventType.USAGE_UPDATED,
        payload={
            "turn": {
                "inputTokens": turn_input,
                "outputTokens": turn_output,
            },
            "total": {
                "inputTokens": thread_input,
                "outputTokens": thread_output,
            },
        },
    )


def _controller(tmp_path: Path) -> tuple[TaskStore, BudgetController]:
    store = TaskStore(tmp_path / "runtime.db")
    TaskService(store).create(
        task_id="task",
        session_id="session",
        correlation_id="correlation",
        description="request",
        component="test",
        cause="user_request",
        idempotency_key="create",
    )
    limits = BudgetLimits(
        max_input_tokens=100,
        max_output_tokens=50,
        max_total_tokens_per_task=200,
        warning_threshold=0.8,
    )
    return store, BudgetController(store, limits)


def test_turn_and_cumulative_usage_remain_separate(tmp_path: Path) -> None:
    store, controller = _controller(tmp_path)
    try:
        decision = controller.observe(
            task_id="task",
            turn_id="turn",
            event=_event(
                "usage-1",
                turn_input=40,
                turn_output=10,
                thread_input=140,
                thread_output=20,
            ),
        )
        assert decision.usage.turn_input_tokens == 40
        assert decision.usage.turn_output_tokens == 10
        assert decision.usage.thread_input_tokens == 140
        assert decision.usage.thread_output_tokens == 20
        assert decision.warning is True
        assert decision.hard_exceeded is False
    finally:
        store.close()


def test_warning_precedes_hard_limit(tmp_path: Path) -> None:
    store, controller = _controller(tmp_path)
    try:
        warning = controller.observe(
            task_id="task",
            turn_id="turn",
            event=_event("warning", turn_input=80, turn_output=0),
        )
        hard = controller.observe(
            task_id="task",
            turn_id="turn",
            event=_event("hard", turn_input=101, turn_output=0),
        )
        assert warning.warning is True
        assert warning.hard_exceeded is False
        assert hard.hard_exceeded is True
        assert hard.reason == "max_input_tokens"
    finally:
        store.close()


def test_usage_updates_are_monotonic_not_double_counted(tmp_path: Path) -> None:
    store, controller = _controller(tmp_path)
    try:
        controller.observe(
            task_id="task",
            turn_id="turn",
            event=_event("newer", turn_input=50, turn_output=10),
        )
        controller.observe(
            task_id="task",
            turn_id="turn",
            event=_event("late", turn_input=20, turn_output=5),
        )
        usage = store.get_usage("task", "turn")
        assert usage is not None
        assert usage.turn_input_tokens == 50
        assert usage.turn_output_tokens == 10
        assert store.task_token_total("task") == 60
    finally:
        store.close()


def test_live_sdk_token_usage_shape_is_parsed(tmp_path: Path) -> None:
    store, controller = _controller(tmp_path)
    try:
        event = _event("live-shape", turn_input=0, turn_output=0)
        live_event = CodexEvent(
            event_id=event.event_id,
            sequence=event.sequence,
            occurred_at=event.occurred_at,
            task_id=event.task_id,
            session_id=event.session_id,
            thread_id=event.thread_id,
            turn_id=event.turn_id,
            item_id=event.item_id,
            backend=event.backend,
            event_type=event.event_type,
            payload={
                "tokenUsage": {
                    "last": {
                        "cachedInputTokens": 12,
                        "inputTokens": 40,
                        "outputTokens": 10,
                        "totalTokens": 50,
                    },
                    "total": {
                        "cachedInputTokens": 12,
                        "inputTokens": 140,
                        "outputTokens": 20,
                        "totalTokens": 160,
                    },
                    "modelContextWindow": 258_400,
                }
            },
        )
        decision = controller.observe(
            task_id="task",
            turn_id="turn",
            event=live_event,
        )
        assert decision.usage.turn_input_tokens == 40
        assert decision.usage.turn_output_tokens == 10
        assert decision.usage.thread_input_tokens == 140
        assert decision.usage.thread_output_tokens == 20
    finally:
        store.close()
