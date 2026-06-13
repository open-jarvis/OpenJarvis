"""OSINT API routes for OpenJarvis.

Provides endpoints for:
- Searching the OSINT Arsenal knowledge base
- Running FBI Watchdog reconnaissance scans
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
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


@router.post("/watch", response_model=WatchdogScanResponse)
async def run_watchdog(body: WatchdogScanRequest) -> dict[str, Any]:
    """Run an FBI Watchdog reconnaissance scan against a target."""
    from openjarvis.tools.fbi_watchdog.core import run_scan

    try:
        results = run_scan(body.target, body.modules)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Scan failed: {exc}")

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
async def exec_tool(body: ArsenalExecRequest) -> dict[str, Any]:
    """Execute an OSINT tool by name against a target."""
    from openjarvis.tools.osint_arsenal.exec_tool import OsintExecTool

    tool = OsintExecTool()
    result = tool.execute(tool_name=body.tool_name, target=body.target, timeout=body.timeout)

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
