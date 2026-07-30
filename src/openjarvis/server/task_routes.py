"""Local, audited REST API for canonical Codex-backed tasks."""

from __future__ import annotations

import ipaddress
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from openjarvis import __version__
from openjarvis.codex.redaction import redact_data
from openjarvis.codex.types import CodexBackendError
from openjarvis.tasks.policy import CentralRiskPolicy, RiskLevel
from openjarvis.tasks.types import (
    ApprovalRecord,
    ExecutionLane,
    InvalidTaskTransition,
    TaskEvent,
    TaskRecord,
    TaskStatus,
)

try:
    from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
    from pydantic import BaseModel, Field, field_validator
except ImportError:
    raise ImportError("fastapi and pydantic are required for task routes")

router = APIRouter(prefix="/v1")

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_ACTIVE_STATUSES = {
    TaskStatus.RUNNING,
    TaskStatus.WAITING_APPROVAL,
    TaskStatus.RECOVERING,
}


class CreateTaskRequest(BaseModel):
    """Validated request to create, but not automatically execute, a task."""

    description: str = Field(min_length=1, max_length=20_000)
    session_id: str | None = Field(default=None, max_length=200)
    risk_level: int = Field(default=0, ge=0, le=4)

    @field_validator("description")
    @classmethod
    def _non_blank_description(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("description must not be blank")
        return value.strip()

    @field_validator("session_id")
    @classmethod
    def _valid_session(cls, value: str | None) -> str | None:
        if value is not None and not _IDENTIFIER_RE.fullmatch(value):
            raise ValueError("session_id contains unsupported characters")
        return value


class ResumeTaskRequest(BaseModel):
    """One explicit continuation turn for a pending or paused task."""

    prompt: str | None = Field(default=None, max_length=20_000)
    cwd: str = Field(min_length=1, max_length=4096)
    isolated_workspace: str | None = Field(default=None, max_length=4096)
    finalize_task: bool = True

    @field_validator("prompt")
    @classmethod
    def _non_blank_prompt(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("prompt must not be blank")
        return value


def _require_local(request: Request) -> None:
    client = request.client
    host = client.host if client is not None else ""
    if host == "testclient":
        return
    try:
        if ipaddress.ip_address(host).is_loopback:
            return
    except ValueError:
        if host.lower() == "localhost":
            return
    raise HTTPException(status_code=403, detail="Local access required")


def _validated_header(value: str, name: str) -> str:
    if not _IDENTIFIER_RE.fullmatch(value):
        raise HTTPException(
            status_code=422,
            detail=f"{name} contains unsupported characters",
        )
    return value


def _mutation_context(
    request: Request,
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> tuple[str, str]:
    _require_local(request)
    return (
        _validated_header(correlation_id, "X-Correlation-ID"),
        _validated_header(idempotency_key, "Idempotency-Key"),
    )


def _task_service(request: Request):
    service = getattr(request.app.state, "task_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Codex task capability is disabled",
        )
    return service


def _orchestrator(request: Request):
    orchestrator = getattr(request.app.state, "codex_orchestrator", None)
    if orchestrator is None:
        raise HTTPException(
            status_code=503,
            detail="Codex orchestration capability is disabled",
        )
    return orchestrator


def serialize_task(task: TaskRecord, *, developer: bool = False) -> dict[str, Any]:
    thread_id = task.active_thread_id
    if thread_id and not developer:
        thread_id = f"…{thread_id[-8:]}"
    return {
        "task_id": task.task_id,
        "session_id": task.session_id,
        "correlation_id": task.correlation_id,
        "description": task.description,
        "status": task.status.value,
        "outcome": task.outcome.value if task.outcome is not None else None,
        "execution_lane": task.execution_lane.value,
        "backend": task.backend,
        "risk_level": task.risk_level,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "version": task.version,
        "result": task.result,
        "error_category": task.error_category,
        "active_thread_id": thread_id,
        "active_turn_id": task.active_turn_id if developer else None,
        "budget_warning": task.budget_warning,
    }


def serialize_event(event: TaskEvent, *, developer: bool = False) -> dict[str, Any]:
    thread_id = event.thread_id
    if thread_id and not developer:
        thread_id = f"…{thread_id[-8:]}"
    return {
        "event_id": event.event_id,
        "task_id": event.task_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "occurred_at": event.occurred_at,
        "cause": event.cause,
        "component": event.component,
        "correlation_id": event.correlation_id,
        "session_id": event.session_id,
        "status_from": (
            event.status_from.value if event.status_from is not None else None
        ),
        "status_to": event.status_to.value if event.status_to is not None else None,
        "thread_id": thread_id,
        "turn_id": event.turn_id if developer else None,
        "item_id": event.item_id,
        "approval_id": event.approval_id,
        "action_id": event.action_id,
        "artifact_id": event.artifact_id,
        "schema_version": event.schema_version,
        "payload": redact_data(dict(event.payload)),
    }


def serialize_approval(record: ApprovalRecord) -> dict[str, Any]:
    tier = ("trivial", "low", "medium", "high", "high")[record.risk_level]
    return {
        "id": record.approval_id,
        "approval_id": record.approval_id,
        "source": "codex_task",
        "task_id": record.task_id,
        "thread_id": f"…{record.thread_id[-8:]}",
        "turn_id": None,
        "item_id": record.item_id,
        "action_id": record.action_id,
        "action_type": record.kind.value,
        "description": record.effect,
        "action": record.action,
        "target": record.target,
        "effect": record.effect,
        "risk_level": record.risk_level,
        "sandbox": record.sandbox,
        "cwd": record.cwd,
        "undo": record.undo,
        "permission_key": "",
        "tier": tier,
        "status": record.status.value,
        "created_at": record.created_at,
        "expires_at": record.expires_at,
        "payload": redact_data(dict(record.payload)),
    }


@router.post("/tasks", status_code=201)
async def create_task(
    body: CreateTaskRequest,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    correlation_id, idempotency_key = mutation
    service = _task_service(request)
    risk_level = CentralRiskPolicy().classify(
        requested_level=body.risk_level,
        action=body.description,
    )
    task = service.create(
        session_id=body.session_id or uuid.uuid4().hex,
        correlation_id=correlation_id,
        description=body.description,
        execution_lane=(
            ExecutionLane.INTERACTIVE
            if risk_level >= RiskLevel.EXTERNAL_PREPARATION
            else ExecutionLane.MODEL
        ),
        risk_level=int(risk_level),
        component="task_api",
        cause="local_user_created_task",
        idempotency_key=idempotency_key,
    )
    return serialize_task(task)


@router.get("/tasks")
async def list_tasks(
    request: Request,
    status: TaskStatus | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    developer: bool = False,
) -> dict[str, Any]:
    _require_local(request)
    tasks = _task_service(request).list(status=status, limit=limit)
    return {
        "tasks": [serialize_task(task, developer=developer) for task in tasks],
        "count": len(tasks),
    }


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: str,
    request: Request,
    developer: bool = False,
) -> dict[str, Any]:
    _require_local(request)
    task = _task_service(request).get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return serialize_task(task, developer=developer)


@router.get("/tasks/{task_id}/timeline")
async def get_task_timeline(
    task_id: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    limit: int = Query(default=1000, ge=1, le=5000),
    developer: bool = False,
) -> dict[str, Any]:
    _require_local(request)
    service = _task_service(request)
    if service.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    events = service.timeline(
        task_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return {
        "events": [
            serialize_event(event, developer=developer) for event in events
        ],
        "count": len(events),
    }


@router.get("/tasks/{task_id}/sources")
async def get_task_sources(
    task_id: str,
    request: Request,
) -> dict[str, Any]:
    _require_local(request)
    service = _task_service(request)
    if service.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    sources = service.store.list_sources(task_id)
    return {
        "sources": [
            {
                "source_id": source.source_id,
                "task_id": source.task_id,
                "source_kind": source.source_kind,
                "external_id": source.external_id,
                "created_at": source.created_at,
                "metadata": redact_data(dict(source.metadata)),
            }
            for source in sources
        ],
        "count": len(sources),
    }


@router.get("/tasks/{task_id}/usage")
async def get_task_usage(
    task_id: str,
    request: Request,
    developer: bool = False,
) -> dict[str, Any]:
    _require_local(request)
    service = _task_service(request)
    if service.get(task_id) is None:
        raise HTTPException(status_code=404, detail="Task not found")
    usage = service.store.list_usage(task_id)
    latest = usage[-1] if usage else None
    return {
        "turns": [
            {
                "turn_id": item.turn_id if developer else None,
                "input_tokens": item.turn_input_tokens,
                "output_tokens": item.turn_output_tokens,
                "warning": item.warning,
                "hard_exceeded": item.hard_exceeded,
                "reason": item.reason,
            }
            for item in usage
        ],
        "cumulative_thread": {
            "input_tokens": latest.thread_input_tokens if latest else 0,
            "output_tokens": latest.thread_output_tokens if latest else 0,
        },
        "task_total_tokens": service.store.task_token_total(task_id),
    }


@router.post("/tasks/{task_id}/pause")
async def pause_task(
    task_id: str,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    correlation_id, idempotency_key = mutation
    try:
        task = await _orchestrator(request).pause(
            task_id,
            cause=f"local_user_pause:{correlation_id}",
            idempotency_key=idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_task(task)


@router.post("/tasks/{task_id}/resume")
async def resume_task(
    task_id: str,
    body: ResumeTaskRequest,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    correlation_id, idempotency_key = mutation
    service = _task_service(request)
    task = service.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    prompt = (body.prompt or task.description).strip()
    cwd = Path(body.cwd)
    isolated = Path(body.isolated_workspace) if body.isolated_workspace else None
    if not cwd.is_absolute() or not cwd.is_dir():
        raise HTTPException(
            status_code=422,
            detail="cwd must be an existing absolute directory",
        )
    if isolated is not None and (
        not isolated.is_absolute() or not isolated.is_dir()
    ):
        raise HTTPException(
            status_code=422,
            detail="isolated_workspace must be an existing absolute directory",
        )
    event, created = service.store.append_event(
        task_id=task_id,
        source_event_id=f"api-resume:{idempotency_key}",
        event_type="task.resume_requested",
        occurred_at=datetime.now(timezone.utc).isoformat(),
        cause="local_user_resume",
        component="task_api",
        payload={"request_correlation_id": correlation_id},
    )
    if not created:
        replayed = service.get(task_id)
        if replayed is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return {
            "task": serialize_task(replayed),
            "content": replayed.result,
            "idempotent_replay": True,
        }
    service.project_committed(event)
    try:
        result = await _orchestrator(request).execute(
            task_id,
            prompt,
            cwd=cwd,
            isolated_workspace=isolated,
            turn_correlation_id=correlation_id,
            finalize_task=body.finalize_task,
        )
    except (ValueError, InvalidTaskTransition) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except CodexBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "task": serialize_task(result.task),
        "content": result.content,
        "idempotent_replay": False,
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    correlation_id, idempotency_key = mutation
    try:
        task = await _orchestrator(request).cancel(
            task_id,
            cause=f"local_user_cancel:{correlation_id}",
            idempotency_key=idempotency_key,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task not found") from exc
    except InvalidTaskTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return serialize_task(task)


@router.get("/codex/health")
async def codex_health(
    request: Request,
    developer: bool = False,
) -> dict[str, Any]:
    _require_local(request)
    service = _task_service(request)
    orchestrator = _orchestrator(request)
    reports = await orchestrator.health()
    tasks = service.list(limit=100)
    active_task = next(
        (task for task in tasks if task.status in _ACTIVE_STATUSES),
        None,
    )
    thread = (
        service.store.get_thread(active_task.task_id, active_task.session_id)
        if active_task is not None
        else None
    )
    available = [report for report in reports if report.available]
    authenticated = [
        report for report in available if report.authenticated
    ]
    selected = None
    if thread is not None:
        selected = next(
            (report for report in reports if report.backend is thread.backend),
            None,
        )
    if selected is None and authenticated:
        selected = authenticated[0]
    config = getattr(request.app.state, "config", None)
    codex_config = getattr(config, "codex", None)
    pending = service.store.list_pending_approvals()
    last_error = next(
        (task.error_category for task in tasks if task.error_category),
        None,
    )
    return redact_data(
        {
            "active_backend": (
                selected.backend.value if selected is not None else None
            ),
            "chatgpt_authenticated": any(
                report.authenticated and report.auth_mode == "chatgpt"
                for report in reports
            ),
            "runtime_version": (
                selected.runtime_version if selected is not None else None
            ),
            "openjarvis_version": __version__,
            "sandbox": (
                thread.sandbox.value
                if thread is not None
                else getattr(codex_config, "analysis_sandbox", "read_only")
            ),
            "approval_mode": (
                thread.approval_mode.value
                if thread is not None
                else getattr(codex_config, "approval_mode", "deny_all")
            ),
            "persistent_threads": any(
                report.capabilities.persistent_threads for report in reports
            ),
            "app_server_available": any(
                report.backend.value == "app_server" and report.available
                for report in reports
            ),
            "cli_fallback_enabled": bool(
                getattr(codex_config, "allow_cli_fallback", False)
            ),
            "degraded": (
                selected is None
                or not selected.authenticated
                or selected.degraded_backend
            ),
            "active_task": (
                serialize_task(active_task, developer=developer)
                if active_task is not None
                else None
            ),
            "open_approvals": len(pending),
            "last_error_category": last_error,
            "backends": [
                {
                    "backend": report.backend.value,
                    "available": report.available,
                    "authenticated": report.authenticated,
                    "auth_mode": report.auth_mode,
                    "runtime_version": report.runtime_version,
                    "degraded": report.degraded_backend,
                    "capabilities": report.capabilities.as_dict(),
                    "detail": report.detail,
                }
                for report in reports
            ],
        }
    )


__all__ = [
    "router",
    "serialize_approval",
    "serialize_event",
    "serialize_task",
]
