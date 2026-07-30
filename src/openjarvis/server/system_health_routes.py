"""Credential-safe, unified Phase 6 system health endpoint."""

from __future__ import annotations

import importlib.metadata
from dataclasses import asdict, is_dataclass
from typing import Any

from fastapi import APIRouter, Request

router = APIRouter(tags=["system"])


def _version() -> str:
    try:
        return importlib.metadata.version("openjarvis")
    except importlib.metadata.PackageNotFoundError:
        return "development"


def _component(available: bool, **details: Any) -> dict[str, Any]:
    return {
        "status": "healthy" if available else "unavailable",
        "available": available,
        **details,
    }


async def _codex_health(orchestrator: Any) -> dict[str, Any]:
    if orchestrator is None:
        return _component(False, authenticated=False, backends=[])
    try:
        reports = await orchestrator.health()
        if not isinstance(reports, (tuple, list)):
            reports = (reports,)
        backends = [
            {
                "backend": getattr(getattr(item, "backend", None), "value", "unknown"),
                "available": bool(getattr(item, "available", False)),
                "authenticated": bool(getattr(item, "authenticated", False)),
                "auth_mode": getattr(item, "auth_mode", None),
                "runtime_version": getattr(item, "runtime_version", None),
                "degraded": bool(getattr(item, "degraded_backend", False)),
            }
            for item in reports
        ]
        available = any(item["available"] for item in backends)
        authenticated = any(item["authenticated"] for item in backends)
        return _component(
            available and authenticated,
            backend_available=available,
            authenticated=authenticated,
            backends=backends,
        )
    except Exception as exc:
        return _component(
            False,
            authenticated=False,
            backends=[],
            last_error=type(exc).__name__,
        )


def _memory_health(service: Any) -> dict[str, Any]:
    if service is None:
        return _component(False, fts5_available=False, note_count=0)
    try:
        report = service.health()
        values = asdict(report) if is_dataclass(report) else {}
        # Never expose a vault path or raw exception. MemoryHealth is already
        # privacy-safe; reduce last_error to an availability signal here.
        last_error = values.pop("last_error", None)
        available = bool(
            values.get("index_available") and values.get("vault_reachable")
        )
        safe_error = (
            type(last_error).__name__
            if isinstance(last_error, Exception)
            else bool(last_error)
        )
        return _component(
            available,
            **values,
            last_error=safe_error,
        )
    except Exception as exc:
        return _component(
            False,
            fts5_available=False,
            note_count=0,
            last_error=type(exc).__name__,
        )


@router.get("/v1/system/health")
async def system_health(request: Request) -> dict[str, Any]:
    """Return one redacted readiness view for the unified Jarvis workspace."""

    state = request.app.state
    task_service = getattr(state, "task_service", None)
    task_store = getattr(state, "task_store", None)
    trace_store = getattr(state, "trace_store", None)
    action_service = getattr(state, "tool_action_service", None)
    browser_service = getattr(state, "browser_session_service", None)
    speech = getattr(state, "speech_backend", None)
    tts = getattr(state, "tts_backend", None)

    try:
        tasks = task_service.list(limit=500) if task_service is not None else []
        task_counts: dict[str, int] = {}
        for task in tasks:
            key = getattr(getattr(task, "status", None), "value", "unknown")
            task_counts[key] = task_counts.get(key, 0) + 1
    except Exception:
        task_counts = {}

    try:
        pending_approvals = (
            len(task_store.list_pending_approvals()) if task_store is not None else 0
        )
    except Exception:
        pending_approvals = 0

    try:
        manifests = action_service.catalog.list() if action_service is not None else ()
        enabled_tools = sum(bool(item.enabled) for item in manifests)
        disabled_tools = len(manifests) - enabled_tools
    except Exception:
        enabled_tools = disabled_tools = 0

    try:
        browser_sessions = browser_service.list() if browser_service is not None else ()
        browser_counts: dict[str, int] = {}
        for session in browser_sessions:
            key = getattr(getattr(session, "status", None), "value", "unknown")
            browser_counts[key] = browser_counts.get(key, 0) + 1
    except Exception:
        browser_counts = {}

    codex = await _codex_health(getattr(state, "codex_orchestrator", None))
    memory = _memory_health(getattr(state, "vault_memory_service", None))
    components = {
        "server": _component(True),
        "codex": codex,
        "memory": memory,
        "task_store": _component(task_store is not None, counts=task_counts),
        "trace_store": _component(trace_store is not None),
        "tools": _component(
            action_service is not None,
            enabled=enabled_tools,
            disabled=disabled_tools,
        ),
        "browser": _component(
            browser_service is not None,
            owned_sessions=browser_counts,
        ),
        "desktop_adapter": _component(
            bool(getattr(state, "desktop_adapter_available", False))
        ),
        "speech": _component(
            speech is not None or tts is not None,
            stt_available=speech is not None,
            tts_available=tts is not None,
            stt_provider=getattr(speech, "backend_id", None) if speech else None,
            tts_provider=getattr(tts, "backend_id", None) if tts else None,
        ),
    }
    unavailable = [name for name, value in components.items() if not value["available"]]
    return {
        "status": "healthy" if not unavailable else "degraded",
        "version": _version(),
        "components": components,
        "pending_approvals": pending_approvals,
        "unavailable": unavailable,
        "credential_safe": True,
    }


__all__ = ["router", "system_health"]
