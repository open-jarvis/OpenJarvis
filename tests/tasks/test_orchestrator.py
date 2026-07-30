from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from openjarvis.codex.events import CodexEventAdapter
from openjarvis.codex.router import CodexBackendRouter
from openjarvis.codex.store import CodexThreadRecord, CodexTurnRecord
from openjarvis.codex.types import (
    BackendCapabilities,
    BackendThread,
    BackendTurn,
    CodexBackendKind,
    CodexEvent,
    CodexEventType,
    CodexHealth,
    ThreadForkRequest,
    ThreadResumeRequest,
    ThreadStartRequest,
    TurnStartRequest,
)
from openjarvis.tasks import (
    BudgetLimits,
    CodexTaskEventProjector,
    CodexTaskOrchestrator,
    TaskOutcome,
    TaskService,
    TaskStatus,
    TaskStore,
)


class FakeCodexBackend:
    capabilities = BackendCapabilities(
        persistent_threads=True,
        resume=True,
        fork=True,
        streaming=True,
        steer=True,
        interrupt=True,
        command_approvals=False,
        file_approvals=False,
        full_item_events=True,
        usage_events=True,
        read_only=True,
        workspace_write=False,
    )

    def __init__(
        self,
        store: TaskStore,
        event_specs: list[tuple[CodexEventType, str | None, dict[str, Any]]],
    ) -> None:
        self.store = store
        self.adapter = CodexEventAdapter(store)
        self.event_specs = event_specs
        self.resume_count = 0
        self.turn_count = 0
        self.turn_events: dict[str, list[CodexEvent]] = {}
        self.interrupt_count = 0

    async def health(self) -> CodexHealth:
        return CodexHealth(
            available=True,
            authenticated=True,
            auth_mode="chatgpt",
            runtime_version="fake",
            backend=CodexBackendKind.PYTHON_SDK,
            capabilities=self.capabilities,
        )

    async def start_thread(self, request: ThreadStartRequest) -> BackendThread:
        now = datetime.now(timezone.utc).isoformat()
        record = self.store.save_thread(
            CodexThreadRecord(
                task_id=request.context.task_id,
                session_id=request.context.session_id,
                correlation_id=request.context.correlation_id,
                thread_id="thread",
                backend=CodexBackendKind.PYTHON_SDK,
                sandbox=request.context.sandbox,
                approval_mode=request.context.approval_mode,
                cwd=str(request.context.cwd),
                model_config={},
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        self.adapter.emit(
            CodexEventType.THREAD_STARTED,
            context=request.context,
            backend=CodexBackendKind.PYTHON_SDK,
            thread_id=record.thread_id,
        )
        return BackendThread(
            thread_id=record.thread_id,
            backend=record.backend,
            task_id=record.task_id,
            session_id=record.session_id,
            status=record.status,
        )

    async def resume_thread(self, request: ThreadResumeRequest) -> BackendThread:
        self.resume_count += 1
        record = self.store.get_thread(
            request.context.task_id,
            request.context.session_id,
        )
        assert record is not None
        self.adapter.emit(
            CodexEventType.THREAD_RESUMED,
            context=request.context,
            backend=CodexBackendKind.PYTHON_SDK,
            thread_id=record.thread_id,
        )
        return BackendThread(
            thread_id=record.thread_id,
            backend=record.backend,
            task_id=record.task_id,
            session_id=record.session_id,
            status=record.status,
        )

    async def fork_thread(self, request: ThreadForkRequest) -> BackendThread:
        raise NotImplementedError

    async def list_threads(self, *, limit: int = 100) -> list[BackendThread]:
        del limit
        return []

    async def start_turn(self, request: TurnStartRequest) -> BackendTurn:
        self.turn_count += 1
        turn_id = f"turn-{self.turn_count}"
        now = datetime.now(timezone.utc).isoformat()
        self.store.save_turn(
            CodexTurnRecord(
                turn_id=turn_id,
                task_id=request.context.task_id,
                session_id=request.context.session_id,
                correlation_id=request.context.correlation_id,
                thread_id=request.thread_id,
                backend=CodexBackendKind.PYTHON_SDK,
                sandbox=request.context.sandbox,
                approval_mode=request.context.approval_mode,
                cwd=str(request.context.cwd),
                status="running",
                created_at=now,
                updated_at=now,
            )
        )
        events: list[CodexEvent] = []
        started = self.adapter.emit(
            CodexEventType.TURN_STARTED,
            context=request.context,
            backend=CodexBackendKind.PYTHON_SDK,
            thread_id=request.thread_id,
            turn_id=turn_id,
        )
        if started:
            events.append(started)
        for event_type, item_id, payload in self.event_specs:
            event = self.adapter.emit(
                event_type,
                context=request.context,
                backend=CodexBackendKind.PYTHON_SDK,
                thread_id=request.thread_id,
                turn_id=turn_id,
                item_id=item_id,
                payload=payload,
            )
            if event:
                events.append(event)
        self.turn_events[turn_id] = events
        return BackendTurn(
            turn_id=turn_id,
            thread_id=request.thread_id,
            backend=CodexBackendKind.PYTHON_SDK,
            status="running",
        )

    async def stream_events(self, turn_id: str) -> AsyncIterator[CodexEvent]:
        for event in self.turn_events[turn_id]:
            yield event

    async def steer(self, turn_id: str, prompt: str) -> None:
        del turn_id, prompt

    async def interrupt(self, turn_id: str) -> None:
        del turn_id
        self.interrupt_count += 1

    async def read_thread(self, thread_id: str) -> Any:
        return {"id": thread_id}

    async def close(self) -> None:
        return None


def _runtime(
    tmp_path: Path,
    specs: list[tuple[CodexEventType, str | None, dict[str, Any]]],
    *,
    budget_limits: BudgetLimits | None = None,
) -> tuple[TaskStore, TaskService, FakeCodexBackend, CodexTaskOrchestrator]:
    store = TaskStore(tmp_path / "runtime.db")
    service = TaskService(store)
    service.create(
        task_id="task",
        session_id="session",
        correlation_id="correlation",
        description="read-only request",
        component="test",
        cause="user_request",
        idempotency_key="create",
    )
    fake = FakeCodexBackend(store, specs)
    router = CodexBackendRouter(
        sdk_backend=fake,
        app_server_backend=fake,
    )
    orchestrator = CodexTaskOrchestrator(
        router,
        service,
        CodexTaskEventProjector(store),
        budget_limits=budget_limits,
    )
    return store, service, fake, orchestrator


@pytest.mark.asyncio
async def test_safe_completed_turn_marks_task_done(tmp_path: Path) -> None:
    store, service, _, orchestrator = _runtime(
        tmp_path,
        [
            (
                CodexEventType.ITEM_COMPLETED,
                "message",
                {"item": {"type": "agentMessage", "text": "answer"}},
            ),
            (CodexEventType.TURN_COMPLETED, None, {}),
        ],
    )
    try:
        result = await orchestrator.execute("task", "question", cwd=tmp_path)
        assert result.content == "answer"
        assert result.task.status is TaskStatus.DONE
        assert result.task.outcome is TaskOutcome.COMPLETED
        assert result.thread_id == "thread"
        assert result.turn_id == "turn-1"
        event_types = [event.event_type for event in service.timeline("task")]
        assert "thread.started" in event_types
        assert "turn.started" in event_types
        assert "item.completed" in event_types
        assert "turn.completed" in event_types
    finally:
        store.close()


@pytest.mark.asyncio
async def test_text_does_not_finish_with_active_command(tmp_path: Path) -> None:
    store, _, _, orchestrator = _runtime(
        tmp_path,
        [
            (
                CodexEventType.ITEM_COMPLETED,
                "message",
                {"item": {"type": "agentMessage", "text": "looks done"}},
            ),
            (CodexEventType.COMMAND_STARTED, "command", {"command": "fake"}),
            (CodexEventType.TURN_COMPLETED, None, {}),
        ],
    )
    try:
        result = await orchestrator.execute("task", "question", cwd=tmp_path)
        assert result.content == "looks done"
        assert result.task.status is TaskStatus.PAUSED
        assert result.task.outcome is None
    finally:
        store.close()


@pytest.mark.asyncio
async def test_interrupted_turn_has_distinct_outcome(tmp_path: Path) -> None:
    store, _, _, orchestrator = _runtime(
        tmp_path,
        [(CodexEventType.TURN_INTERRUPTED, None, {"message": "stopped"})],
    )
    try:
        result = await orchestrator.execute("task", "question", cwd=tmp_path)
        assert result.task.status is TaskStatus.FAILED
        assert result.task.outcome is TaskOutcome.INTERRUPTED
    finally:
        store.close()


@pytest.mark.asyncio
async def test_two_turns_resume_same_persistent_thread(tmp_path: Path) -> None:
    store, _, fake, orchestrator = _runtime(
        tmp_path,
        [(CodexEventType.TURN_COMPLETED, None, {})],
    )
    try:
        first = await orchestrator.execute(
            "task",
            "first",
            cwd=tmp_path,
            turn_correlation_id="first-turn",
            finalize_task=False,
        )
        second = await orchestrator.execute(
            "task",
            "second",
            cwd=tmp_path,
            turn_correlation_id="second-turn",
        )
        assert first.task.status is TaskStatus.RUNNING
        assert second.task.status is TaskStatus.DONE
        assert first.thread_id == second.thread_id == "thread"
        assert fake.resume_count == 1
        assert fake.turn_count == 2
    finally:
        store.close()


@pytest.mark.asyncio
async def test_budget_warning_qualifies_successful_outcome(tmp_path: Path) -> None:
    limits = BudgetLimits(
        max_input_tokens=100,
        max_output_tokens=100,
        max_total_tokens_per_task=1_000,
        warning_threshold=0.8,
    )
    store, _, fake, orchestrator = _runtime(
        tmp_path,
        [
            (
                CodexEventType.USAGE_UPDATED,
                None,
                {"turn": {"inputTokens": 85, "outputTokens": 1}},
            ),
            (CodexEventType.TURN_COMPLETED, None, {}),
        ],
        budget_limits=limits,
    )
    try:
        result = await orchestrator.execute("task", "question", cwd=tmp_path)
        assert result.task.status is TaskStatus.DONE
        assert result.task.outcome is TaskOutcome.COMPLETED_WITH_BUDGET_WARNING
        assert result.task.budget_warning is True
        assert fake.interrupt_count == 0
    finally:
        store.close()


@pytest.mark.asyncio
async def test_hard_budget_interrupt_before_result_is_interrupted(
    tmp_path: Path,
) -> None:
    limits = BudgetLimits(
        max_input_tokens=100,
        max_output_tokens=100,
        max_total_tokens_per_task=1_000,
    )
    store, _, fake, orchestrator = _runtime(
        tmp_path,
        [
            (
                CodexEventType.USAGE_UPDATED,
                None,
                {"turn": {"inputTokens": 101, "outputTokens": 1}},
            ),
            (CodexEventType.TURN_COMPLETED, None, {}),
        ],
        budget_limits=limits,
    )
    try:
        result = await orchestrator.execute("task", "question", cwd=tmp_path)
        assert result.task.status is TaskStatus.FAILED
        assert result.task.outcome is TaskOutcome.INTERRUPTED
        assert result.task.error_category == "budget_limit"
        assert fake.interrupt_count == 1
    finally:
        store.close()


@pytest.mark.asyncio
async def test_late_hard_usage_does_not_invalidate_received_result(
    tmp_path: Path,
) -> None:
    limits = BudgetLimits(
        max_input_tokens=100,
        max_output_tokens=100,
        max_total_tokens_per_task=1_000,
    )
    store, _, fake, orchestrator = _runtime(
        tmp_path,
        [
            (
                CodexEventType.ITEM_COMPLETED,
                "message",
                {"item": {"type": "agentMessage", "text": "correct"}},
            ),
            (CodexEventType.TURN_COMPLETED, None, {}),
            (
                CodexEventType.USAGE_UPDATED,
                None,
                {"turn": {"inputTokens": 101, "outputTokens": 1}},
            ),
        ],
        budget_limits=limits,
    )
    try:
        result = await orchestrator.execute("task", "question", cwd=tmp_path)
        assert result.content == "correct"
        assert result.task.status is TaskStatus.DONE
        assert result.task.outcome is TaskOutcome.COMPLETED_WITH_BUDGET_WARNING
        assert fake.interrupt_count == 0
    finally:
        store.close()


@pytest.mark.asyncio
async def test_pause_interrupts_active_turn_before_state_change(
    tmp_path: Path,
) -> None:
    store, service, fake, orchestrator = _runtime(tmp_path, [])
    stream_started = asyncio.Event()
    stream_released = asyncio.Event()

    async def blocking_stream(turn_id: str) -> AsyncIterator[CodexEvent]:
        for event in fake.turn_events[turn_id]:
            yield event
        stream_started.set()
        await stream_released.wait()

    async def interrupt(turn_id: str) -> None:
        del turn_id
        fake.interrupt_count += 1
        stream_released.set()

    fake.stream_events = blocking_stream  # type: ignore[method-assign]
    fake.interrupt = interrupt  # type: ignore[method-assign]
    try:
        execution = asyncio.create_task(
            orchestrator.execute("task", "question", cwd=tmp_path)
        )
        await asyncio.wait_for(stream_started.wait(), timeout=1)
        paused = await orchestrator.pause(
            "task",
            cause="local_user_pause",
            idempotency_key="pause-once",
        )
        result = await asyncio.wait_for(execution, timeout=1)
        assert fake.interrupt_count == 1
        assert paused.status is TaskStatus.PAUSED
        assert result.task.status is TaskStatus.PAUSED
        assert service.get("task").status is TaskStatus.PAUSED
    finally:
        store.close()
