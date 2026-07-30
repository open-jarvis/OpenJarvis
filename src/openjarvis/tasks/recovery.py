"""Conservative restart recovery for canonical Codex tasks."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Coroutine, TypeVar

from openjarvis.tasks.service import TaskService
from openjarvis.tasks.store import TaskStore
from openjarvis.tasks.types import TaskRecord, TaskStatus

_T = TypeVar("_T")


class RecoveryDecision(str, Enum):
    """Persisted recovery outcomes."""

    RESUMED_SAFE = "resumed_safe"
    RESUME_AVAILABLE = "resume_available"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED_AMBIGUOUS = "paused_ambiguous"
    PAUSED_NO_THREAD = "paused_no_thread"
    PAUSED_RESUME_FAILED = "paused_resume_failed"


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """Credential-safe result of checking one task after restart."""

    task_id: str
    prior_status: TaskStatus
    final_status: TaskStatus
    decision: RecoveryDecision
    safe_to_resume: bool
    ambiguous_effect: bool
    open_approval: bool
    reason: str
    thread_id: str | None
    turn_id: str | None


ResumeCallback = Callable[[TaskRecord], Awaitable[None]]


class RecoveryCoordinator:
    """Never repeat work whose external effect cannot be established."""

    def __init__(self, store: TaskStore, task_service: TaskService) -> None:
        self._store = store
        self._tasks = task_service

    async def recover_all(
        self,
        *,
        resume_safe: ResumeCallback | None = None,
    ) -> list[RecoveryReport]:
        reports = []
        for task in self._store.list_recoverable_tasks():
            reports.append(await self._recover_one(task, resume_safe=resume_safe))
        return reports

    def recover_all_sync(
        self,
        *,
        resume_safe: ResumeCallback | None = None,
    ) -> list[RecoveryReport]:
        return _run_coroutine_sync(self.recover_all(resume_safe=resume_safe))

    async def _recover_one(
        self,
        task: TaskRecord,
        *,
        resume_safe: ResumeCallback | None,
    ) -> RecoveryReport:
        started_at = datetime.now(timezone.utc).isoformat()
        prior_status = task.status
        if task.status is not TaskStatus.RECOVERING:
            task = self._tasks.transition(
                task.task_id,
                TaskStatus.RECOVERING,
                component="recovery_coordinator",
                cause="process_restart",
                idempotency_key=f"recovery:{task.version}:start",
            )

        thread = self._store.get_thread(task.task_id, task.session_id)
        latest_turn = (
            self._store.get_latest_turn(thread.thread_id)
            if thread is not None
            else None
        )
        approvals = self._store.list_unanswered_approvals(task.task_id)
        effects = self._effect_facts(task.task_id)
        open_approval = bool(approvals)
        ambiguous_effect = bool(
            effects["active_commands"]
            or effects["open_file_changes"]
            or (task.risk_level > 0 and prior_status is TaskStatus.RUNNING)
        )

        decision: RecoveryDecision
        reason: str
        safe_to_resume = False
        if open_approval:
            task = self._tasks.transition(
                task.task_id,
                TaskStatus.WAITING_APPROVAL,
                component="recovery_coordinator",
                cause="unanswered_approval_recovered",
                idempotency_key=f"recovery:{task.version}:approval",
                payload={
                    "approval_ids": [
                        approval.approval_id for approval in approvals
                    ]
                },
            )
            decision = RecoveryDecision.WAITING_APPROVAL
            reason = "An approval still needs a user or App Server response."
        elif thread is None:
            task = self._tasks.transition(
                task.task_id,
                TaskStatus.PAUSED,
                component="recovery_coordinator",
                cause="missing_persisted_thread",
                idempotency_key=f"recovery:{task.version}:no-thread",
            )
            decision = RecoveryDecision.PAUSED_NO_THREAD
            reason = "No persisted Codex thread can be verified."
        elif ambiguous_effect:
            task = self._tasks.transition(
                task.task_id,
                TaskStatus.PAUSED,
                component="recovery_coordinator",
                cause="ambiguous_side_effect",
                idempotency_key=f"recovery:{task.version}:ambiguous",
                payload=effects,
            )
            decision = RecoveryDecision.PAUSED_AMBIGUOUS
            reason = "A command, file change, or workspace-write effect is ambiguous."
        else:
            safe_to_resume = task.risk_level == 0
            if resume_safe is None:
                task = self._tasks.transition(
                    task.task_id,
                    TaskStatus.PAUSED,
                    component="recovery_coordinator",
                    cause="safe_resume_requires_dispatch",
                    idempotency_key=f"recovery:{task.version}:available",
                )
                decision = RecoveryDecision.RESUME_AVAILABLE
                reason = (
                    "Read-only state is safe; an explicit dispatcher may resume it."
                )
            else:
                task = self._tasks.transition(
                    task.task_id,
                    TaskStatus.RUNNING,
                    component="recovery_coordinator",
                    cause="verified_read_only_resume",
                    idempotency_key=f"recovery:{task.version}:resume",
                )
                try:
                    await resume_safe(task)
                except Exception:
                    current = self._tasks.get(task.task_id)
                    if current is not None and current.status is TaskStatus.RUNNING:
                        task = self._tasks.transition(
                            task.task_id,
                            TaskStatus.PAUSED,
                            component="recovery_coordinator",
                            cause="safe_resume_dispatch_failed",
                            idempotency_key=f"recovery:{task.version}:resume-failed",
                        )
                    decision = RecoveryDecision.PAUSED_RESUME_FAILED
                    reason = "The verified read-only resume dispatcher failed."
                else:
                    task = self._tasks.get(task.task_id) or task
                    decision = RecoveryDecision.RESUMED_SAFE
                    reason = "Verified read-only state was resumed."

        facts: dict[str, Any] = {
            **effects,
            "approval_ids": [approval.approval_id for approval in approvals],
            "thread_status": thread.status if thread else None,
            "turn_status": latest_turn.status if latest_turn else None,
        }
        self._store.save_recovery_check(
            task_id=task.task_id,
            prior_status=prior_status,
            decision=decision.value,
            safe_to_resume=safe_to_resume,
            ambiguous_effect=ambiguous_effect,
            open_approval=open_approval,
            reason=reason,
            thread_id=thread.thread_id if thread else None,
            turn_id=latest_turn.turn_id if latest_turn else None,
            started_at=started_at,
            facts=facts,
        )
        return RecoveryReport(
            task_id=task.task_id,
            prior_status=prior_status,
            final_status=task.status,
            decision=decision,
            safe_to_resume=safe_to_resume,
            ambiguous_effect=ambiguous_effect,
            open_approval=open_approval,
            reason=reason,
            thread_id=thread.thread_id if thread else None,
            turn_id=latest_turn.turn_id if latest_turn else None,
        )

    def _effect_facts(self, task_id: str) -> dict[str, list[str]]:
        active_commands: set[str] = set()
        open_file_changes: set[str] = set()
        for event in self._store.list_task_events(task_id):
            key = event.item_id or event.event_id
            if event.event_type == "command.started":
                active_commands.add(key)
            elif event.event_type == "command.completed":
                active_commands.discard(key)
            elif event.event_type == "file_change.proposed":
                open_file_changes.add(key)
            elif event.event_type == "file_change.applied":
                open_file_changes.discard(key)
        return {
            "active_commands": sorted(active_commands),
            "open_file_changes": sorted(open_file_changes),
        }


def _run_coroutine_sync(coro: Coroutine[Any, Any, _T]) -> _T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: list[_T] = []
    error: list[BaseException] = []

    def _runner() -> None:
        try:
            result.append(asyncio.run(coro))
        except BaseException as exc:  # pragma: no cover
            error.append(exc)

    thread = threading.Thread(target=_runner, name="jarvis-recovery", daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0]


__all__ = [
    "RecoveryCoordinator",
    "RecoveryDecision",
    "RecoveryReport",
    "ResumeCallback",
]
