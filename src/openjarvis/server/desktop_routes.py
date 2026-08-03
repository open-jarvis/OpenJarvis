"""Loopback-only onboarding and status API for productive desktop access."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from openjarvis.desktop.controller import DesktopAccessMode, DesktopTargetGrant
from openjarvis.desktop.win32 import WindowsDesktopError
from openjarvis.server.tool_browser_routes import _mutation_context, _require_local

router = APIRouter(prefix="/v1/desktop", tags=["desktop"])


class DesktopGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    label: str = Field(min_length=1, max_length=160)
    executable: str = Field(min_length=3, max_length=1024)
    title_contains: str = Field(min_length=1, max_length=256)
    mode: DesktopAccessMode
    capabilities: list[str] = Field(max_length=12)


class DesktopTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str = Field(min_length=1, max_length=80)


def _controller(request: Request):
    _require_local(request)
    controller = getattr(request.app.state, "desktop_controller", None)
    if controller is None:
        raise HTTPException(status_code=503, detail="Productive desktop access is disabled")
    return controller


@router.get("/status")
async def desktop_status(request: Request) -> dict[str, Any]:
    return _controller(request).status()


@router.put("/targets/{target_id}")
async def save_desktop_target(
    target_id: str,
    payload: DesktopGrantRequest,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    if payload.target_id != target_id:
        raise HTTPException(status_code=409, detail="Desktop target ID mismatch")
    executable = Path(payload.executable).resolve(strict=False)
    if payload.mode is not DesktopAccessMode.OFF:
        if not executable.is_file() or executable.suffix.casefold() != ".exe":
            raise HTTPException(
                status_code=422,
                detail="Desktop executable must be an existing absolute .exe file",
            )
    try:
        grant = _controller(request).access_store.put(
            DesktopTargetGrant(
                target_id=payload.target_id,
                label=payload.label,
                executable=str(executable),
                title_contains=payload.title_contains,
                mode=payload.mode,
                capabilities=tuple(payload.capabilities),
            )
        )
    except (ValueError, WindowsDesktopError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "target_id": grant.target_id,
        "mode": grant.mode.value,
        "capabilities": list(grant.capabilities),
        "status": "saved",
    }


@router.post("/connect")
async def connect_desktop_target(
    payload: DesktopTargetRequest,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    try:
        window = _controller(request).connect(payload.target_id)
    except WindowsDesktopError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "target_id": payload.target_id,
        "window_title": window.title,
        "process_id": window.process_id,
        "status": "connected",
    }


@router.post("/interrupt")
async def interrupt_desktop(
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, str]:
    _controller(request).interrupt()
    return {"status": "interrupted"}


__all__ = ["router"]
