"""OpenJarvis-controlled execution adapter for the Phase 2 Codex router."""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Coroutine, TypeVar

from openjarvis.codex.protocol import CodexBackend
from openjarvis.codex.router import CodexBackendRouter
from openjarvis.codex.types import (
    CodexBackendError,
    CodexEvent,
    CodexEventType,
    CodexModelConfig,
    CodexRunContext,
    ThreadResumeRequest,
    ThreadStartRequest,
    TurnStartRequest,
)
from openjarvis.tasks.budget import BudgetController, BudgetLimits
from openjarvis.tasks.lanes import ExecutionLaneScheduler
from openjarvis.tasks.policy import CentralRiskPolicy
from openjarvis.tasks.projection import CodexTaskEventProjector
from openjarvis.tasks.service import TaskService
from openjarvis.tasks.types import (
    InvalidTaskTransition,
    TaskOutcome,
    TaskRecord,
    TaskStatus,
)

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    """Result returned by the OpenJarvis Codex execution adapter."""

    task: TaskRecord
    content: str
    thread_id: str | None
    turn_id: str | None


@dataclass(slots=True)
class _TerminalFacts:
    completed: bool = False
    failed: bool = False
    interrupted: bool = False
    content: str = ""
    active_commands: set[str] = field(default_factory=set)
    open_file_changes: set[str] = field(default_factory=set)
    pending_approvals: set[str] = field(default_factory=set)
    budget_warning: bool = False
    budget_interrupted: bool = False

    @property
    def safe_to_finish(self) -> bool:
        return bool(
            self.completed
            and not self.failed
            and not self.interrupted
            and not self.active_commands
            and not self.open_file_changes
            and not self.pending_approvals
        )


class CodexTaskOrchestrator:
    """Run Codex as a backend while OpenJarvis owns lifecycle and policy."""

    def __init__(
        self,
        router: CodexBackendRouter,
        task_service: TaskService,
        projector: CodexTaskEventProjector,
        *,
        risk_policy: CentralRiskPolicy | None = None,
        default_timeout_seconds: float = 300.0,
        default_step_limit: int = 100,
        default_token_limit: int | None = None,
        lane_scheduler: ExecutionLaneScheduler | None = None,
        budget_limits: BudgetLimits | None = None,
        default_model: CodexModelConfig | None = None,
    ) -> None:
        if default_timeout_seconds <= 0:
            raise ValueError("default_timeout_seconds must be positive")
        if default_step_limit <= 0:
            raise ValueError("default_step_limit must be positive")
        self._router = router
        self._tasks = task_service
        self._projector = projector
        self._risk_policy = risk_policy or CentralRiskPolicy()
        self._token_limit = default_token_limit
        self._lanes = lane_scheduler or ExecutionLaneScheduler()
        self._budget = BudgetController(task_service.store, budget_limits)
        self._default_model = default_model or CodexModelConfig(
            model=None,
            effort=None,
            service_tier=None,
        )
        self._timeout_seconds = min(
            default_timeout_seconds,
            self._budget.limits.max_turn_duration,
        )
        self._step_limit = min(
            default_step_limit,
            self._budget.limits.max_steps,
        )
        self._active_turns: dict[str, tuple[str, CodexBackend, CodexRunContext]] = {}

    @property
    def lanes(self) -> ExecutionLaneScheduler:
        return self._lanes

    async def execute(
        self,
        task_id: str,
        prompt: str,
        *,
        cwd: Path,
        isolated_workspace: Path | None = None,
        model: CodexModelConfig | None = None,
        developer_instructions: str | None = None,
        turn_correlation_id: str | None = None,
        finalize_task: bool = True,
        _lane_acquired: bool = False,
    ) -> TaskExecutionResult:
        """Execute one turn and apply terminal state only after safety checks."""

        if not prompt.strip():
            raise ValueError("prompt must be non-empty")
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        policy = self._risk_policy.derive_turn_policy(
            risk_level=task.risk_level,
            cwd=cwd,
            isolated_workspace=isolated_workspace,
        )
        if not _lane_acquired:
            return await self._lanes.run(
                policy.execution_lane,
                lambda: self.execute(
                    task_id,
                    prompt,
                    cwd=cwd,
                    isolated_workspace=isolated_workspace,
                    model=model,
                    developer_instructions=developer_instructions,
                    turn_correlation_id=turn_correlation_id,
                    finalize_task=finalize_task,
                    _lane_acquired=True,
                ),
            )
        backend = await self._router.select(
            require_interactive_approvals=(
                policy.approval_mode.value == "brokered"
            )
        )
        model_config = model or self._default_model

        thread_context = CodexRunContext(
            task_id=task.task_id,
            session_id=task.session_id,
            correlation_id=f"{task.correlation_id}:thread",
            cwd=cwd,
            sandbox=policy.sandbox,
            approval_mode=policy.approval_mode,
            model=model_config,
            timeout_seconds=self._timeout_seconds,
            step_limit=self._step_limit,
            token_limit=self._token_limit,
            developer_instructions=developer_instructions,
            isolated_workspace=policy.isolated_workspace,
        ).validated()
        persisted = self._tasks.store.get_thread(task.task_id, task.session_id)
        if persisted is None:
            thread = await backend.start_thread(
                ThreadStartRequest(context=thread_context)
            )
        else:
            thread = await backend.resume_thread(
                ThreadResumeRequest(
                    context=thread_context,
                    thread_id=persisted.thread_id,
                )
            )
        self._project_persisted_events(thread.thread_id)

        turn_context = CodexRunContext(
            task_id=task.task_id,
            session_id=task.session_id,
            correlation_id=(
                turn_correlation_id
                or f"{task.correlation_id}:turn:{uuid.uuid4().hex}"
            ),
            cwd=cwd,
            sandbox=policy.sandbox,
            approval_mode=policy.approval_mode,
            model=model_config,
            timeout_seconds=self._timeout_seconds,
            step_limit=self._step_limit,
            token_limit=self._token_limit,
            developer_instructions=developer_instructions,
            isolated_workspace=policy.isolated_workspace,
        ).validated()
        turn = await backend.start_turn(
            TurnStartRequest(
                context=turn_context,
                thread_id=thread.thread_id,
                prompt=prompt,
            )
        )
        current = self._tasks.get(task.task_id)
        if current is None:
            raise RuntimeError("task disappeared before its turn started")
        if current.status in {
            TaskStatus.PENDING,
            TaskStatus.PAUSED,
            TaskStatus.RECOVERING,
        }:
            self._tasks.transition(
                task.task_id,
                TaskStatus.RUNNING,
                component="codex_task_orchestrator",
                cause="codex_turn_started",
                idempotency_key=f"{turn_context.correlation_id}:running",
                active_thread_id=thread.thread_id,
                active_turn_id=turn.turn_id,
            )

        facts = _TerminalFacts()
        self._active_turns[task.task_id] = (turn.turn_id, backend, turn_context)
        try:
            async for event in backend.stream_events(turn.turn_id):
                self._projector.project(event)
                self._observe(facts, event)
                if event.event_type is CodexEventType.USAGE_UPDATED:
                    decision = self._budget.observe(
                        task_id=task.task_id,
                        turn_id=turn.turn_id,
                        event=event,
                    )
                    facts.budget_warning = facts.budget_warning or decision.warning
                    if decision.hard_exceeded and not facts.completed:
                        await backend.interrupt(turn.turn_id)
                        facts.budget_interrupted = True
                        facts.interrupted = True
        except Exception as exc:
            current = self._tasks.get(task.task_id)
            if current is not None and current.status is TaskStatus.RUNNING:
                try:
                    self._tasks.transition(
                        task.task_id,
                        TaskStatus.FAILED,
                        component="codex_task_orchestrator",
                        cause="codex_event_stream_failed",
                        idempotency_key=(
                            f"{turn_context.correlation_id}:stream-failed"
                        ),
                        outcome=TaskOutcome.FAILED,
                        result=facts.content,
                        error_category=(
                            "codex_backend_error"
                            if isinstance(exc, CodexBackendError)
                            else "codex_runtime_error"
                        ),
                        payload={"error_type": type(exc).__name__},
                    )
                except InvalidTaskTransition:
                    pass
            raise
        finally:
            self._active_turns.pop(task.task_id, None)
        self._project_persisted_events(thread.thread_id)

        final_task = self._finish_task(
            task.task_id,
            facts,
            thread_id=thread.thread_id,
            turn_id=turn.turn_id,
            transition_key=turn_context.correlation_id,
            finalize_task=finalize_task,
        )
        return TaskExecutionResult(
            task=final_task,
            content=facts.content,
            thread_id=thread.thread_id,
            turn_id=turn.turn_id,
        )

    def execute_sync(self, *args: Any, **kwargs: Any) -> TaskExecutionResult:
        return _run_coroutine_sync(self.execute(*args, **kwargs))

    async def health(self):
        return await self._router.health()

    def active_context(self, task_id: str) -> CodexRunContext | None:
        """Return safe runtime policy metadata for local health reporting."""

        active = self._active_turns.get(task_id)
        return active[2] if active is not None else None

    async def pause(
        self,
        task_id: str,
        *,
        cause: str,
        idempotency_key: str,
    ) -> TaskRecord:
        """Interrupt an active turn before recording a paused task."""

        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        active = self._active_turns.get(task_id)
        if active is not None:
            await active[1].interrupt(active[0])
        return self._tasks.transition(
            task_id,
            TaskStatus.PAUSED,
            component="task_api",
            cause=cause,
            idempotency_key=idempotency_key,
            payload={"active_turn_interrupted": active is not None},
        )

    async def cancel(
        self,
        task_id: str,
        *,
        cause: str,
        idempotency_key: str,
    ) -> TaskRecord:
        """Interrupt an active turn before recording terminal cancellation."""

        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"unknown task: {task_id}")
        active = self._active_turns.get(task_id)
        if active is not None:
            await active[1].interrupt(active[0])
        return self._tasks.transition(
            task_id,
            TaskStatus.CANCELED,
            component="task_api",
            cause=cause,
            idempotency_key=idempotency_key,
            outcome=TaskOutcome.CANCELED,
            payload={"active_turn_interrupted": active is not None},
        )

    async def close(self) -> None:
        await self._router.close()

    def close_sync(self) -> None:
        _run_coroutine_sync(self.close())

    def _project_persisted_events(self, thread_id: str) -> None:
        for event in self._tasks.store.list_events(thread_id):
            self._projector.project(event)

    def _finish_task(
        self,
        task_id: str,
        facts: _TerminalFacts,
        *,
        thread_id: str,
        turn_id: str,
        transition_key: str,
        finalize_task: bool,
    ) -> TaskRecord:
        current = self._tasks.get(task_id)
        if current is None:
            raise RuntimeError("task disappeared after its Codex turn")
        if current.status in {TaskStatus.PAUSED, TaskStatus.CANCELED}:
            return current
        if current.status is TaskStatus.WAITING_APPROVAL:
            return self._tasks.transition(
                task_id,
                TaskStatus.PAUSED,
                component="codex_task_orchestrator",
                cause="turn_ended_with_pending_approval",
                idempotency_key=f"{transition_key}:pending-approval",
                payload={"thread_id": thread_id, "turn_id": turn_id},
            )
        if facts.interrupted:
            return self._tasks.transition(
                task_id,
                TaskStatus.FAILED,
                component="codex_task_orchestrator",
                cause=(
                    "usage_budget_hard_limit"
                    if facts.budget_interrupted
                    else "codex_turn_interrupted"
                ),
                idempotency_key=f"{transition_key}:interrupted",
                outcome=TaskOutcome.INTERRUPTED,
                result=facts.content,
                error_category=(
                    "budget_limit" if facts.budget_interrupted else "interrupted"
                ),
                budget_warning=facts.budget_warning,
            )
        if facts.failed:
            return self._tasks.transition(
                task_id,
                TaskStatus.FAILED,
                component="codex_task_orchestrator",
                cause="codex_turn_failed",
                idempotency_key=f"{transition_key}:failed",
                outcome=TaskOutcome.FAILED,
                result=facts.content,
                error_category="codex_turn_failed",
            )
        if facts.safe_to_finish and not finalize_task:
            return current
        if facts.safe_to_finish:
            return self._tasks.transition(
                task_id,
                TaskStatus.DONE,
                component="codex_task_orchestrator",
                cause="terminal_safety_checks_passed",
                idempotency_key=f"{transition_key}:done",
                outcome=(
                    TaskOutcome.COMPLETED_WITH_BUDGET_WARNING
                    if facts.budget_warning
                    else TaskOutcome.COMPLETED
                ),
                result=facts.content,
                budget_warning=facts.budget_warning,
            )
        return self._tasks.transition(
            task_id,
            TaskStatus.PAUSED,
            component="codex_task_orchestrator",
            cause="ambiguous_or_incomplete_turn_effect",
            idempotency_key=f"{transition_key}:paused",
            result=facts.content,
            payload={
                "active_commands": sorted(facts.active_commands),
                "open_file_changes": sorted(facts.open_file_changes),
                "pending_approvals": sorted(facts.pending_approvals),
                "terminal_event_received": facts.completed,
            },
        )

    @staticmethod
    def _observe(facts: _TerminalFacts, event: CodexEvent) -> None:
        item_key = event.item_id or event.event_id
        if event.event_type is CodexEventType.COMMAND_STARTED:
            facts.active_commands.add(item_key)
        elif event.event_type is CodexEventType.COMMAND_COMPLETED:
            facts.active_commands.discard(item_key)
        elif event.event_type is CodexEventType.FILE_CHANGE_PROPOSED:
            facts.open_file_changes.add(item_key)
        elif event.event_type is CodexEventType.FILE_CHANGE_APPLIED:
            facts.open_file_changes.discard(item_key)
        elif event.event_type is CodexEventType.APPROVAL_REQUESTED:
            facts.pending_approvals.add(item_key)
        elif event.event_type is CodexEventType.APPROVAL_RESOLVED:
            facts.pending_approvals.discard(item_key)
        elif event.event_type is CodexEventType.TURN_COMPLETED:
            facts.completed = True
        elif event.event_type is CodexEventType.TURN_FAILED:
            facts.failed = True
        elif event.event_type is CodexEventType.TURN_INTERRUPTED:
            facts.interrupted = True
        content = CodexTaskOrchestrator._event_content(event)
        if content:
            facts.content = content

    @staticmethod
    def _event_content(event: CodexEvent) -> str:
        payload = event.payload
        for key in ("content", "text", "message", "final_output"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
        item = payload.get("item")
        if isinstance(item, dict):
            for key in ("content", "text", "message"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value
        return ""


def _run_coroutine_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    """Run a coroutine from sync code, including callers already in an event loop."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[_T] = []
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # pragma: no cover - forwarded to caller
            error.append(exc)

    thread = threading.Thread(target=_runner, name="jarvis-codex-sync", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


__all__ = ["CodexTaskOrchestrator", "TaskExecutionResult"]
