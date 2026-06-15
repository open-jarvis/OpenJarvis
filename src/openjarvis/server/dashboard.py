"""Dashboard route — serves the React SPA for the dashboard."""

from __future__ import annotations

import pathlib

from fastapi import APIRouter
from fastapi.responses import FileResponse

dashboard_router = APIRouter()

_STATIC_DIR = pathlib.Path(__file__).parent / "static"


@dashboard_router.get("/dashboard", response_class=FileResponse)
async def dashboard():
    """Serve the React SPA for the dashboard route."""
    return FileResponse(_STATIC_DIR / "index.html")


__all__ = ["dashboard_router"]
