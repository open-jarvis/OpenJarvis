"""Local API exposing status and non-secret Flow session controls."""

from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from openjarvis.flow import FlowAuthenticationError

router = APIRouter(prefix="/v1/flow", tags=["flow"])


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


class NativeFlowAssertion(BaseModel):
    nonce: str = Field(min_length=16, max_length=200)
    authenticated_at: int
    signature: str = Field(min_length=64, max_length=64)
    owner: str = Field(min_length=1, max_length=256)


class ActivityRequest(BaseModel):
    session_id: str | None = Field(default=None, max_length=200)


def _authority(request: Request):
    authority = getattr(request.app.state, "flow_authority", None)
    if authority is None:
        raise HTTPException(status_code=503, detail="Flow authority is unavailable")
    return authority


@router.get("/status")
async def flow_status(request: Request) -> dict:
    _require_local(request)
    return _authority(request).status().as_dict()


@router.get("/capabilities")
async def flow_capabilities(request: Request) -> dict:
    _require_local(request)
    status = _authority(request).status()
    return {"mode": status.mode.value, "capabilities": status.capabilities}


@router.post("/activate")
async def activate_flow(
    assertion: NativeFlowAssertion,
    request: Request,
    native_bridge: Annotated[
        str | None, Header(alias="X-OpenJarvis-Native-Bridge")
    ] = None,
) -> dict:
    _require_local(request)
    if native_bridge != "tauri":
        raise HTTPException(
            status_code=403,
            detail="Flow activation must originate in the native desktop process",
        )
    try:
        return (
            _authority(request)
            .activate_flow(
                nonce=assertion.nonce,
                authenticated_at=assertion.authenticated_at,
                signature=assertion.signature,
                owner=assertion.owner,
            )
            .as_dict()
        )
    except FlowAuthenticationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/assistant")
async def activate_assistant(request: Request) -> dict:
    _require_local(request)
    return _authority(request).activate_assistant().as_dict()


@router.post("/lock")
async def lock_flow(request: Request, reason: str = "user_locked") -> dict:
    _require_local(request)
    return _authority(request).lock(reason).as_dict()


@router.post("/activity")
async def flow_activity(body: ActivityRequest, request: Request) -> dict:
    _require_local(request)
    try:
        return _authority(request).record_activity(body.session_id).as_dict()
    except FlowAuthenticationError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


__all__ = ["router"]
