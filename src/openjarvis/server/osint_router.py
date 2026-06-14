"""OSINT API routes for OpenJarvis.

Provides endpoints for:
- Searching the OSINT Arsenal knowledge base
- Running FBI Watchdog reconnaissance scans
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/osint", tags=["osint"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ArsenalSearchRequest(BaseModel):
    query: str = Field("", description="Search query for OSINT tools")
    limit: int = Field(20, ge=1, le=100)
    category: str = Field("", description="Optional category filter")


class ArsenalToolResult(BaseModel):
    name: str
    category: str
    description: str
    url: str | None
    install_command: str | None
    tags: list[str]


class ArsenalSearchResponse(BaseModel):
    query: str
    results: list[ArsenalToolResult]
    count: int


class WatchdogScanRequest(BaseModel):
    target: str = Field(..., description="Domain or IP to scan")
    modules: list[str] = Field(
        default=["dns", "http", "whois", "ip"],
        description="Modules to run: dns, http, whois, ip",
    )


class WatchdogScanResponse(BaseModel):
    target: str
    timestamp: str
    modules: list[str]
    results: dict[str, Any]
    summary: dict[str, Any]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/search", response_model=ArsenalSearchResponse)
async def search_arsenal(body: ArsenalSearchRequest) -> dict[str, Any]:
    """Search the OSINT Arsenal knowledge base for tools."""
    from openjarvis.tools.osint_arsenal.search_tool import _ensure_index, _score

    index = _ensure_index()
    if not index:
        raise HTTPException(status_code=503, detail="OSINT Arsenal index not available")

    import re

    query_words: set[str] = set()
    if body.query.strip():
        query_words = set(re.findall(r"[a-zA-Z0-9]+", body.query.lower()))
        if not query_words:
            query_words = {body.query.lower()}

    scored = []
    for tool in index:
        if body.category and body.category.lower() not in tool.get("category", "").lower():
            continue
        if query_words:
            score = _score(tool, query_words)
            if score > 0:
                scored.append((score, tool))
        else:
            scored.append((0, tool))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[: body.limit]

    results = [
        ArsenalToolResult(
            name=t["name"],
            category=t["category"],
            description=t["description"],
            url=t.get("url"),
            install_command=t.get("install_command"),
            tags=t.get("tags", []),
        )
        for _, t in top
    ]

    return {
        "query": body.query,
        "results": results,
        "count": len(results),
    }


@router.get("/categories")
async def list_categories() -> dict[str, list[str]]:
    """Return all unique categories in the OSINT Arsenal index."""
    from openjarvis.tools.osint_arsenal.search_tool import _ensure_index

    index = _ensure_index()
    if not index:
        raise HTTPException(status_code=503, detail="OSINT Arsenal index not available")

    cats = sorted({t.get("category", "") for t in index if t.get("category")})
    return {"categories": cats}


def _user_id(request: Request) -> str:
    """Extract user id from header or fallback to anonymous."""
    return request.headers.get("x-user-id", "anonymous")


@router.post("/watch", response_model=WatchdogScanResponse)
async def run_watchdog(body: WatchdogScanRequest, request: Request) -> dict[str, Any]:
    """Run an FBI Watchdog reconnaissance scan against a target."""
    from openjarvis.tools.fbi_watchdog.core import run_scan
    from openjarvis.server.osint_store import get_store

    try:
        results = run_scan(body.target, body.modules)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")

    # Persist result
    get_store().save_scan(
        user_id=_user_id(request),
        target=results["target"],
        modules=results["modules"],
        results=results["results"],
        summary=results["summary"],
    )

    return {
        "target": results["target"],
        "timestamp": results["timestamp"],
        "modules": results["modules"],
        "results": results["results"],
        "summary": results["summary"],
    }


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class ArsenalExecRequest(BaseModel):
    tool_name: str = Field(..., description="Name of the OSINT tool to execute")
    target: str = Field(..., description="Target to run the tool against")
    timeout: int = Field(60, ge=1, le=300)


class ArsenalExecResponse(BaseModel):
    tool: str
    target: str
    type: str
    output: str
    success: bool
    metadata: dict[str, Any]


@router.post("/exec", response_model=ArsenalExecResponse)
async def exec_tool(body: ArsenalExecRequest, request: Request) -> dict[str, Any]:
    """Execute an OSINT tool by name against a target."""
    from openjarvis.tools.osint_arsenal.exec_tool import OsintExecTool
    from openjarvis.server.osint_store import get_store

    tool = OsintExecTool()
    result = tool.execute(tool_name=body.tool_name, target=body.target, timeout=body.timeout)

    # Persist result
    get_store().save_exec(
        user_id=_user_id(request),
        tool_name=body.tool_name,
        target=body.target,
        output=result.content,
        success=result.success,
        metadata=result.metadata or {},
    )

    return {
        "tool": body.tool_name,
        "target": body.target,
        "type": result.metadata.get("type", "unknown") if result.metadata else "unknown",
        "output": result.content,
        "success": result.success,
        "metadata": result.metadata or {},
    }


@router.get("/tool/{name}")
async def get_tool(name: str) -> dict[str, Any]:
    """Get full details for a single OSINT tool by name."""
    from openjarvis.tools.osint_arsenal.search_tool import _ensure_index

    index = _ensure_index()
    if not index:
        raise HTTPException(status_code=503, detail="OSINT Arsenal index not available")

    for tool in index:
        if tool.get("name", "").lower() == name.lower():
            return {
                "name": tool.get("name"),
                "category": tool.get("category"),
                "description": tool.get("description"),
                "url": tool.get("url"),
                "install_command": tool.get("install_command"),
                "tags": tool.get("tags", []),
            }

    raise HTTPException(status_code=404, detail=f"Tool '{name}' not found")


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class WatchdogExportRequest(BaseModel):
    target: str
    modules: list[str] = ["dns", "http", "whois", "ip"]
    format: str = Field("json", pattern=r"^(json|csv)$")


@router.post("/watch/export")
async def export_watchdog(body: WatchdogExportRequest) -> dict[str, Any]:
    """Export FBI Watchdog results as JSON or CSV."""
    import csv
    import io
    from datetime import datetime, timezone

    from openjarvis.tools.fbi_watchdog.core import run_scan

    try:
        results = run_scan(body.target, body.modules)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")

    if body.format == "json":
        return {
            "format": "json",
            "filename": f"watchdog_{body.target}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json",
            "data": results,
        }

    # CSV flattening
    rows: list[dict[str, str]] = []
    for mod, data in results.get("results", {}).items():
        if isinstance(data, dict):
            for key, val in data.items():
                if isinstance(val, list):
                    val = "; ".join(str(v) for v in val)
                rows.append({
                    "module": mod,
                    "key": key,
                    "value": str(val),
                })
        else:
            rows.append({"module": mod, "key": "result", "value": str(data)})

    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=["module", "key", "value"])
        writer.writeheader()
        writer.writerows(rows)
    else:
        output.write("module,key,value\n")

    return {
        "format": "csv",
        "filename": f"watchdog_{body.target}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv",
        "data": output.getvalue(),
    }


# ---------------------------------------------------------------------------
# History + Favorites
# ---------------------------------------------------------------------------


class FavoriteRequest(BaseModel):
    tool_name: str = Field(..., description="Name of the tool to favorite/unfavorite")


class FavoriteResponse(BaseModel):
    tool_name: str
    favorited: bool


@router.get("/history")
async def list_history(request: Request, limit: int = 50) -> dict[str, Any]:
    """List OSINT scan and execution history for the current user."""
    from openjarvis.server.osint_store import get_store

    entries = get_store().list_history(_user_id(request), limit=limit)
    return {"entries": entries, "count": len(entries)}


@router.delete("/history/{entry_id}")
async def delete_history(entry_id: str, request: Request) -> dict[str, Any]:
    """Delete a single history entry."""
    from openjarvis.server.osint_store import get_store

    removed = get_store().delete_history_entry(_user_id(request), entry_id)
    return {"removed": removed}


@router.post("/favorites", response_model=FavoriteResponse)
async def toggle_favorite(body: FavoriteRequest, request: Request) -> dict[str, Any]:
    """Toggle favorite status for a tool."""
    from openjarvis.server.osint_store import get_store

    status = get_store().toggle_favorite(_user_id(request), body.tool_name)
    return {"tool_name": body.tool_name, "favorited": status}


@router.get("/favorites")
async def list_favorites(request: Request) -> dict[str, Any]:
    """List all favorited tool names for the current user."""
    from openjarvis.server.osint_store import get_store

    favs = get_store().list_favorites(_user_id(request))
    return {"favorites": favs, "count": len(favs)}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard/stats")
async def dashboard_stats(request: Request) -> dict[str, Any]:
    """Return aggregated dashboard stats for the current user."""
    from openjarvis.server.osint_store import get_store

    stats = get_store().get_dashboard_stats(_user_id(request))
    return stats


# ---------------------------------------------------------------------------
# Schedules
# ---------------------------------------------------------------------------


class ScheduleCreateRequest(BaseModel):
    target: str = Field(..., description="Domain or IP to scan")
    modules: list[str] = Field(
        default=["dns", "http", "whois", "ip"],
        description="Modules to run",
    )
    interval_minutes: int = Field(60, ge=5, le=10080, description="Interval in minutes (min 5, max 1 week)")


class ScheduleResponse(BaseModel):
    id: str
    target: str
    modules: list[str]
    interval_minutes: int
    last_run: str | None
    next_run: str | None
    enabled: bool
    created_at: str


class ScheduleListResponse(BaseModel):
    schedules: list[ScheduleResponse]
    count: int


@router.post("/schedule", response_model=ScheduleResponse)
async def create_schedule(body: ScheduleCreateRequest, request: Request) -> dict[str, Any]:
    """Create a new recurring scan schedule."""
    from openjarvis.server.osint_store import get_store

    job = get_store().create_schedule(
        user_id=_user_id(request),
        target=body.target,
        modules=body.modules,
        interval_minutes=body.interval_minutes,
    )
    return {
        "id": job.id,
        "target": job.target,
        "modules": job.modules,
        "interval_minutes": job.interval_minutes,
        "last_run": job.last_run,
        "next_run": job.next_run,
        "enabled": job.enabled,
        "created_at": job.created_at,
    }


@router.get("/schedule", response_model=ScheduleListResponse)
async def list_schedules(request: Request) -> dict[str, Any]:
    """List all recurring scan schedules for the current user."""
    from openjarvis.server.osint_store import get_store

    schedules = get_store().list_schedules(_user_id(request))
    return {"schedules": schedules, "count": len(schedules)}


@router.delete("/schedule/{schedule_id}")
async def delete_schedule(schedule_id: str, request: Request) -> dict[str, Any]:
    """Delete a schedule."""
    from openjarvis.server.osint_store import get_store

    removed = get_store().delete_schedule(_user_id(request), schedule_id)
    return {"removed": removed}


@router.post("/schedule/{schedule_id}/toggle")
async def toggle_schedule(schedule_id: str, request: Request) -> dict[str, Any]:
    """Toggle enabled status for a schedule."""
    from openjarvis.server.osint_store import get_store

    status = get_store().toggle_schedule(_user_id(request), schedule_id)
    return {"schedule_id": schedule_id, "enabled": status}


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------


@router.get("/alerts")
async def list_alerts(request: Request, limit: int = 20) -> dict[str, Any]:
    """Return scan entries with detected changes (diff)."""
    from openjarvis.server.osint_store import get_store

    alerts = get_store().list_alerts(_user_id(request), limit=limit)
    return {"alerts": alerts, "count": len(alerts), "unread": len(alerts)}
