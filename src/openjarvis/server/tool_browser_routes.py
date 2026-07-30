"""Authenticated local API for tool actions and owned browser sessions."""

from __future__ import annotations

import ipaddress
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from openjarvis.browser.process import BrowserOpenError
from openjarvis.codex.redaction import redact_data
from openjarvis.tools.action_service import ToolActionError
from openjarvis.tools.actions import ToolAction, ToolArtifact, ToolProposal
from openjarvis.tools.manifest import ManifestValidationError, ToolManifest

router = APIRouter(prefix="/v1", tags=["tools-browser"])


class CreateActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: ToolProposal
    execute: bool = True


class CreateBrowserSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _require_local(request: Request) -> None:
    host = request.client.host if request.client else ""
    if host == "testclient":
        return
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if not local:
        raise HTTPException(status_code=403, detail="Local access required")


def _mutation_context(
    request: Request,
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> tuple[str, str]:
    _require_local(request)
    if not correlation_id.strip() or not idempotency_key.strip():
        raise HTTPException(status_code=422, detail="Mutation headers cannot be empty")
    return correlation_id, idempotency_key


def _actions(request: Request):
    service = getattr(request.app.state, "tool_action_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Tool actions are disabled")
    return service


def _browser(request: Request):
    service = getattr(request.app.state, "browser_session_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Browser sessions are disabled")
    return service


def _manifest_payload(manifest: ToolManifest, *, runtime: bool) -> dict[str, Any]:
    payload = manifest.model_dump(mode="json")
    payload["runtime_available"] = runtime
    payload["healthy"] = bool(
        manifest.enabled and manifest.supports_current_platform() and runtime
    )
    return payload


def _action_payload(action: ToolAction) -> dict[str, Any]:
    return redact_data(action.model_dump(mode="json"))


def _artifact_payload(artifact: ToolArtifact) -> dict[str, Any]:
    return redact_data(artifact.model_dump(mode="json"))


def _session_payload(session) -> dict[str, Any]:
    return redact_data(
        {
            "session_id": session.session_id,
            "status": session.status.value,
            "profile_path": str(session.profile_path),
            "control_port": session.control_port,
            "browser_pid": session.browser_pid,
            "browser_start_time": session.browser_start_time,
            "control_service_pid": session.control_service_pid,
            "last_successful_heartbeat": session.last_successful_heartbeat,
            "recovery_attempts": session.recovery_attempts,
            "maximum_recovery_attempts": session.maximum_recovery_attempts,
            "safe_checkpoint": session.safe_checkpoint,
            "effect_known": session.effect_known,
            "owned_process": session.owned_process,
        }
    )


@router.get("/tools/health")
async def tools_health(request: Request) -> dict[str, Any]:
    _require_local(request)
    service = _actions(request)
    manifests = service.catalog.list()
    healthy = sum(
        bool(
            manifest.enabled
            and manifest.supports_current_platform()
            and service.runtime_available(manifest.tool_id)
        )
        for manifest in manifests
    )
    return {
        "healthy": healthy == len(manifests),
        "registered": len(manifests),
        "available": healthy,
        "degraded": len(manifests) - healthy,
        "lanes": service.lanes.snapshot(),
    }


@router.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    _require_local(request)
    service = _actions(request)
    tools = [
        _manifest_payload(
            manifest,
            runtime=service.runtime_available(manifest.tool_id),
        )
        for manifest in service.catalog.list()
    ]
    return {"tools": tools, "count": len(tools)}


@router.get("/tools/{tool_id}")
async def get_tool(tool_id: str, request: Request) -> dict[str, Any]:
    _require_local(request)
    service = _actions(request)
    try:
        manifest = service.catalog.get(tool_id)
    except ManifestValidationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _manifest_payload(
        manifest,
        runtime=service.runtime_available(manifest.tool_id),
    )


@router.get("/tasks/{task_id}/actions")
async def list_task_actions(task_id: str, request: Request) -> dict[str, Any]:
    _require_local(request)
    actions = _actions(request).store.list_actions(task_id)
    return {
        "actions": [_action_payload(action) for action in actions],
        "count": len(actions),
    }


@router.post("/tasks/{task_id}/actions", status_code=201)
async def create_task_action(
    task_id: str,
    body: CreateActionRequest,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    correlation_id, idempotency_key = mutation
    proposal = body.proposal
    if proposal.task_id != task_id:
        raise HTTPException(status_code=409, detail="Task-ID mismatch")
    if proposal.correlation_id != correlation_id:
        raise HTTPException(status_code=409, detail="Correlation-ID mismatch")
    if proposal.idempotency_key != idempotency_key:
        raise HTTPException(status_code=409, detail="Idempotency-Key mismatch")
    service = _actions(request)
    try:
        action = service.create(proposal)
        if body.execute and action.status.value == "validated":
            action = await service.execute(action.action_id)
    except ToolActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _action_payload(action)


@router.get("/actions/{action_id}")
async def get_action(action_id: str, request: Request) -> dict[str, Any]:
    _require_local(request)
    action = _actions(request).store.get_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return _action_payload(action)


@router.get("/actions/{action_id}/artifacts")
async def get_action_artifacts(action_id: str, request: Request) -> dict[str, Any]:
    _require_local(request)
    service = _actions(request)
    if service.store.get_action(action_id) is None:
        raise HTTPException(status_code=404, detail="Action not found")
    artifacts = service.store.list_artifacts(action_id)
    return {
        "artifacts": [_artifact_payload(artifact) for artifact in artifacts],
        "count": len(artifacts),
    }


async def _approval_action(
    action_id: str,
    request: Request,
    mutation: tuple[str, str],
    *,
    allow: bool,
) -> dict[str, Any]:
    _correlation_id, decision_id = mutation
    try:
        if allow:
            action = await _actions(request).approve(
                action_id,
                decision_id=decision_id,
            )
        else:
            action = _actions(request).deny(action_id, decision_id=decision_id)
    except ToolActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _action_payload(action)


@router.post("/actions/{action_id}/approve")
async def approve_action(
    action_id: str,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    return await _approval_action(action_id, request, mutation, allow=True)


@router.post("/actions/{action_id}/deny")
async def deny_action(
    action_id: str,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    return await _approval_action(action_id, request, mutation, allow=False)


@router.post("/actions/{action_id}/cancel")
async def cancel_action(
    action_id: str,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    try:
        return _action_payload(_actions(request).cancel(action_id))
    except ToolActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/actions/{action_id}/retry")
async def retry_action(
    action_id: str,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    try:
        return _action_payload(await _actions(request).retry(action_id))
    except ToolActionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/browser/health")
async def browser_health(
    request: Request,
    session_id: str | None = Query(default=None),
) -> dict[str, Any]:
    _require_local(request)
    service = _browser(request)
    try:
        health = (
            (service.health(session_id),)
            if session_id is not None
            else service.health_all()
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "sessions": [
            redact_data(asdict(item)) | {"healthy": item.healthy}
            for item in health
        ],
        "count": len(health),
        "healthy": all(item.healthy for item in health),
    }


@router.get("/browser/sessions")
async def browser_sessions(request: Request) -> dict[str, Any]:
    _require_local(request)
    sessions = _browser(request).list()
    return {
        "sessions": [_session_payload(session) for session in sessions],
        "count": len(sessions),
    }


@router.post("/browser/sessions", status_code=201)
async def create_browser_session(
    _body: CreateBrowserSessionRequest,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    try:
        return _session_payload(_browser(request).create())
    except BrowserOpenError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/browser/sessions/{session_id}/recover")
async def recover_browser_session(
    session_id: str,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    try:
        return redact_data(asdict(_browser(request).recover(session_id)))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BrowserOpenError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/browser/sessions/{session_id}")
async def close_browser_session(
    session_id: str,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    try:
        return _session_payload(_browser(request).close(session_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


__all__ = ["router"]
