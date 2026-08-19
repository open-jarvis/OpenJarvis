"""REST endpoints for the Science Lab module and the voice pipeline's status."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

science_lab_router = APIRouter(prefix="/v1/science-lab", tags=["science-lab"])


class AnalyzeRequest(BaseModel):
    description: str
    project_name: Optional[str] = None


def _serialize_result(result: Any) -> Dict[str, Any]:
    return {
        "content": result.content,
        "metadata": result.metadata,
    }


@science_lab_router.post("/analyze")
async def analyze(req: AnalyzeRequest, request: Request) -> Dict[str, Any]:
    agent = getattr(request.app.state, "science_lab_agent", None)
    if agent is None:
        raise HTTPException(status_code=501, detail="Science Lab agent not configured")
    try:
        result = await asyncio.to_thread(
            agent.run, req.description, project_name=req.project_name
        )
    except Exception as exc:
        logger.exception("Science Lab analyze failed")
        raise HTTPException(
            status_code=500, detail=f"Science Lab analyze failed: {exc}"
        ) from exc
    return _serialize_result(result)


@science_lab_router.get("/projects")
async def list_projects(request: Request) -> Dict[str, Any]:
    from openjarvis.core.config import load_config
    from openjarvis.science_lab.store import ScienceProjectStore

    config = load_config()
    store = ScienceProjectStore(db_path=config.science_lab.db_path)
    try:
        projects = store.list_projects()
        return {"projects": [p.to_dict() for p in projects]}
    finally:
        store.close()


@science_lab_router.get("/projects/{name}")
async def get_project(name: str, request: Request) -> Dict[str, Any]:
    from openjarvis.core.config import load_config
    from openjarvis.science_lab.store import ScienceProjectStore

    config = load_config()
    store = ScienceProjectStore(db_path=config.science_lab.db_path)
    try:
        project = store.get(name)
    finally:
        store.close()
    if project is None:
        raise HTTPException(status_code=404, detail=f"No project named {name!r}")
    return project.to_dict()


@science_lab_router.post("/projects/{name}/save")
async def save_project(name: str, request: Request) -> Dict[str, Any]:
    """Re-run analysis for *name*'s stored objective and re-save it.

    Primarily used by the frontend "re-analyze & save" action; new projects
    are normally created via ``POST /analyze`` with ``project_name`` set.
    """
    from openjarvis.core.config import load_config
    from openjarvis.science_lab.store import ScienceProjectStore

    agent = getattr(request.app.state, "science_lab_agent", None)
    if agent is None:
        raise HTTPException(status_code=501, detail="Science Lab agent not configured")

    config = load_config()
    store = ScienceProjectStore(db_path=config.science_lab.db_path)
    try:
        existing = store.get(name)
    finally:
        store.close()
    if existing is None:
        raise HTTPException(status_code=404, detail=f"No project named {name!r}")

    result = await asyncio.to_thread(agent.run, existing.objective, project_name=name)
    return _serialize_result(result)


@science_lab_router.get("/voice/status")
async def voice_status(request: Request) -> Dict[str, Any]:
    svc = getattr(request.app.state, "voice_service", None)
    if svc is None:
        return {"available": False}
    return {"available": True, **svc.status()}


__all__ = ["science_lab_router"]
