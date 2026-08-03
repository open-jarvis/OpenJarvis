"""Loopback-only MCP server management and health routes."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from openjarvis.mcp.action_bridge import (
    disconnect_server,
    discover_action_tools,
    interrupt_active_calls,
)
from openjarvis.server.tool_browser_routes import _mutation_context, _require_local

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


class MCPServerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server_id: str = Field(min_length=1, max_length=48, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=120)
    transport: str = Field(pattern=r"^(http|stdio)$")
    enabled: bool = True
    url: str = Field(default="", max_length=2048)
    command: str = Field(default="", max_length=1024)
    args: list[str] = Field(default_factory=list, max_length=32)
    token_env: str = Field(default="", max_length=96, pattern=r"^(|MCP_[A-Z0-9_]+_API_KEY)$")
    include_tools: list[str] = Field(default_factory=list, max_length=256)
    exclude_tools: list[str] = Field(default_factory=list, max_length=256)
    tool_policies: dict[str, str] = Field(default_factory=dict)


def _registry(request: Request):
    _require_local(request)
    registry = getattr(request.app.state, "mcp_server_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=503, detail="Persistent MCP configuration is unavailable"
        )
    return registry


def _status(request: Request) -> dict[str, Any]:
    registry = _registry(request)
    runtime = {
        str(item.get("server_id")): item
        for item in getattr(request.app.state, "_mcp_status", [])
    }
    servers = []
    for record in registry.list():
        value = record.public_dict()
        value.update(
            {
                "connected": False,
                "tool_count": 0,
                "tools": [],
            }
        )
        value.update(runtime.get(record.server_id, {}))
        servers.append(value)
    connected = sum(1 for item in servers if item.get("connected"))
    return {
        "available": True,
        "servers": servers,
        "connected_servers": connected,
        "disconnected_servers": sum(
            1 for item in servers if item.get("enabled") and not item.get("connected")
        ),
        "discovered_tools": sum(int(item.get("tool_count", 0)) for item in servers),
        "active_provider": "mcp" if connected else "none",
    }


@router.get("/status")
async def mcp_status(request: Request) -> dict[str, Any]:
    return _status(request)


@router.get("/servers")
async def mcp_servers(request: Request) -> dict[str, Any]:
    return _status(request)


@router.put("/servers/{server_id}")
async def put_mcp_server(
    server_id: str,
    payload: MCPServerRequest,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    if payload.server_id != server_id:
        raise HTTPException(status_code=409, detail="MCP server ID mismatch")
    registry = _registry(request)
    current = registry.get(server_id)
    value = payload.model_dump()
    if current is not None:
        value["last_connected_at"] = current.last_connected_at
        value["last_error"] = current.last_error
    try:
        record = registry.put(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    disconnect_server(request.app.state, server_id)
    return {"status": "saved", "server": record.public_dict()}


@router.delete("/servers/{server_id}")
async def delete_mcp_server(
    server_id: str,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, str]:
    registry = _registry(request)
    if not registry.remove(server_id):
        raise HTTPException(status_code=404, detail="MCP server not found")
    disconnect_server(request.app.state, server_id)
    return {"status": "removed", "server_id": server_id}


@router.post("/servers/{server_id}/reconnect")
async def reconnect_mcp_server(
    server_id: str,
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    registry = _registry(request)
    if registry.get(server_id) is None:
        raise HTTPException(status_code=404, detail="MCP server not found")
    disconnect_server(request.app.state, server_id)
    await asyncio.to_thread(discover_action_tools, request.app.state, force=True)
    return _status(request)


@router.post("/interrupt")
async def interrupt_mcp_calls(
    request: Request,
    _mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
) -> dict[str, Any]:
    _registry(request)
    interrupted = set(interrupt_active_calls(request.app.state))
    for item in getattr(request.app.state, "_mcp_status", []):
        if item.get("server_id") in interrupted:
            item["connected"] = False
            item["last_error"] = "MCP action interrupted"
    return {"status": "interrupted", "active_calls": len(interrupted)}


__all__ = ["router"]
