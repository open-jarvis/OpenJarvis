"""REST API for automations (scheduled routines) and assistant capabilities.

Backed by the ``TaskScheduler`` the server starts when ``[scheduler]`` is
enabled (``app.state.task_scheduler``). Used by the HUD's automations panel.

* ``GET    /v1/automations/status``       scheduler, Claude, Claude Code status
* ``POST   /v1/automations/settings``     store the default timezone
* ``GET    /v1/automations``              list routines with their last run
* ``POST   /v1/automations``              create a routine
* ``POST   /v1/automations/{id}/pause``   / ``resume`` / ``run``
* ``DELETE /v1/automations/{id}``         remove a routine
* ``GET    /v1/automations/{id}/runs``    run history for one routine
* ``GET    /v1/automations/runs/recent``  runs newer than ``after_id``
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/automations", tags=["automations"])

_SCHEDULE_TYPES = ("cron", "interval", "once")
_RESULT_PREVIEW = 600


class AutomationCreate(BaseModel):
    name: str = Field("", max_length=80)
    prompt: str = Field(..., min_length=1, max_length=4000)
    schedule_type: str
    schedule_value: str = Field(..., min_length=1, max_length=200)
    timezone: str = ""
    tools: str = ""


class AutomationSettings(BaseModel):
    timezone: str


def _scheduler(request: Request):
    sched = getattr(request.app.state, "task_scheduler", None)
    if sched is None:
        raise HTTPException(
            status_code=503,
            detail="The automation scheduler is not running on this server.",
        )
    return sched


def _preview(text: str) -> str:
    text = (text or "").strip()
    return text if len(text) <= _RESULT_PREVIEW else text[:_RESULT_PREVIEW] + "…"


def _serialize(task: Any, last_run: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    meta = task.metadata or {}
    return {
        "id": task.id,
        "name": meta.get("name") or task.prompt[:60],
        "prompt": task.prompt,
        "schedule_type": task.schedule_type,
        "schedule_value": task.schedule_value,
        "timezone": meta.get("timezone") or "",
        "status": task.status,
        "next_run": task.next_run,
        "last_run": task.last_run,
        "last_result": (
            {
                "success": bool(last_run.get("success")),
                "finished_at": last_run.get("finished_at"),
                "result": _preview(last_run.get("result") or ""),
                "error": _preview(last_run.get("error") or ""),
            }
            if last_run
            else None
        ),
    }


@router.get("/status")
async def automation_status(request: Request) -> Dict[str, Any]:
    import os

    from openjarvis.scheduler.settings import get_default_timezone
    from openjarvis.server.smart_routing import claude_available, claude_model
    from openjarvis.tools.claude_code_worker import claude_code_ready

    engine = getattr(request.app.state, "engine", None)
    agent = getattr(request.app.state, "agent", None)
    tool_names = sorted(
        t.spec.name
        for t in (getattr(agent, "_tools", None) or [])
        if hasattr(t, "spec")
    )
    cc_ready, cc_reason = claude_code_ready()
    return {
        "scheduler_running": getattr(request.app.state, "task_scheduler", None)
        is not None,
        "timezone": get_default_timezone(),
        "local_model": getattr(request.app.state, "model", ""),
        "claude": {
            "model": claude_model(),
            "key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "available": claude_available(engine),
        },
        "claude_code": {"ready": cc_ready, "reason": cc_reason},
        "agent_tools": tool_names,
    }


@router.post("/settings")
async def automation_settings(body: AutomationSettings) -> Dict[str, Any]:
    from openjarvis.scheduler.settings import set_default_timezone

    try:
        set_default_timezone(body.timezone)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"timezone": body.timezone}


@router.get("")
async def list_automations(request: Request) -> Dict[str, Any]:
    sched = _scheduler(request)
    store = sched._store
    items = []
    for task in sched.list_tasks():
        if task.status == "cancelled":
            continue
        logs = store.get_run_logs(task.id, limit=1)
        items.append(_serialize(task, logs[0] if logs else None))
    items.sort(key=lambda t: (t["status"] != "active", t["next_run"] or "~"))
    return {"automations": items, "latest_run_id": store.latest_run_id()}


@router.post("")
async def create_automation(request: Request, body: AutomationCreate) -> Dict[str, Any]:
    from openjarvis.scheduler.settings import get_default_timezone, valid_timezone

    sched = _scheduler(request)
    if body.schedule_type not in _SCHEDULE_TYPES:
        raise HTTPException(
            status_code=400, detail=f"schedule_type must be one of {_SCHEDULE_TYPES}"
        )
    if body.schedule_type == "interval":
        try:
            seconds = float(body.schedule_value)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Interval must be a number of seconds"
            ) from exc
        if seconds < 60:
            raise HTTPException(
                status_code=400, detail="Interval must be at least 60 seconds"
            )
    if body.schedule_type == "cron":
        try:
            from croniter import croniter

            if not croniter.is_valid(body.schedule_value):
                raise ValueError
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Invalid cron expression"
            ) from exc

    tz = (
        body.timezone
        if valid_timezone(body.timezone)
        else (get_default_timezone() or "")
    )
    metadata: Dict[str, Any] = {}
    if body.name.strip():
        metadata["name"] = body.name.strip()
    if tz:
        metadata["timezone"] = tz
    try:
        task = sched.create_task(
            prompt=body.prompt.strip(),
            schedule_type=body.schedule_type,
            schedule_value=body.schedule_value.strip(),
            # Tool-using agent so routines can check the PC, open things, etc.
            # Empty ``tools`` means the server's configured tool set.
            agent="orchestrator",
            tools=body.tools,
            metadata=metadata,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Could not create automation: {exc}"
        ) from exc
    return _serialize(task, None)


def _with_task(request: Request, task_id: str, action: str) -> Dict[str, Any]:
    sched = _scheduler(request)
    try:
        getattr(sched, f"{action}_task")(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Automation not found") from exc
    d = sched._store.get_task(task_id)
    return {"id": task_id, "status": d.get("status") if d else "deleted"}


@router.post("/{task_id}/pause")
async def pause_automation(request: Request, task_id: str) -> Dict[str, Any]:
    return _with_task(request, task_id, "pause")


@router.post("/{task_id}/resume")
async def resume_automation(request: Request, task_id: str) -> Dict[str, Any]:
    return _with_task(request, task_id, "resume")


@router.delete("/{task_id}")
async def delete_automation(request: Request, task_id: str) -> Dict[str, Any]:
    sched = _scheduler(request)
    if sched._store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Automation not found")
    sched.cancel_task(task_id)
    sched._store.delete_task(task_id)
    return {"id": task_id, "status": "deleted"}


@router.post("/{task_id}/run")
async def run_automation(request: Request, task_id: str) -> Dict[str, Any]:
    """Start a run now in the background; poll ``runs/recent`` for the result."""
    sched = _scheduler(request)
    if sched._store.get_task(task_id) is None:
        raise HTTPException(status_code=404, detail="Automation not found")

    async def _run() -> None:
        try:
            await asyncio.to_thread(sched.run_task_now, task_id)
        except Exception:
            logger.exception("Run-now failed for automation %s", task_id)

    asyncio.get_running_loop().create_task(_run())
    return {"id": task_id, "status": "started"}


@router.get("/runs/recent")
async def recent_runs(request: Request, after_id: int = 0) -> Dict[str, Any]:
    sched = _scheduler(request)
    store = sched._store
    names: Dict[str, str] = {}
    runs = []
    for r in store.get_recent_runs(after_id=after_id):
        tid = r["task_id"]
        if tid not in names:
            d = store.get_task(tid) or {}
            names[tid] = (d.get("metadata") or {}).get("name") or (
                d.get("prompt") or ""
            )[:60]
        runs.append(
            {
                "id": r["id"],
                "task_id": tid,
                "name": names[tid],
                "success": bool(r["success"]),
                "finished_at": r["finished_at"],
                "result": _preview(r["result"]),
                "error": _preview(r["error"]),
            }
        )
    return {"runs": runs, "latest_run_id": store.latest_run_id()}


@router.get("/{task_id}/runs")
async def task_runs(request: Request, task_id: str, limit: int = 10) -> Dict[str, Any]:
    sched = _scheduler(request)
    logs = sched._store.get_run_logs(task_id, limit=max(1, min(limit, 50)))
    return {
        "runs": [
            {
                "id": r["id"],
                "success": bool(r["success"]),
                "started_at": r["started_at"],
                "finished_at": r["finished_at"],
                "result": _preview(r["result"]),
                "error": _preview(r["error"]),
            }
            for r in logs
        ]
    }


__all__ = ["router"]
