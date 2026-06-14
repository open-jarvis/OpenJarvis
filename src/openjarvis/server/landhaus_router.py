"""FastAPI router for /v1/landhaus — Landhaus Bavaria data access endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from openjarvis.tools.landhaus_bavaria import LandhausBavariaConnector

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/v1/landhaus/health", tags=["landhaus"])
async def landhaus_health() -> dict[str, Any]:
    """Health check for all configured Landhaus Bavaria data sources."""
    connector = LandhausBavariaConnector()
    try:
        results = await connector.health()
        return {"status": "ok", "sources": results}
    except Exception as exc:
        logger.error("Landhaus health check failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        await connector.close()


@router.get("/v1/landhaus/availability", tags=["landhaus"])
async def landhaus_availability(date_from: str, date_to: str) -> dict[str, Any]:
    """Query room availability via Deskline proxy."""
    connector = LandhausBavariaConnector()
    try:
        results = await connector.room_availability(date_from, date_to)
        if "error" in results:
            raise HTTPException(status_code=503, detail=results["error"])
        return results
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Landhaus availability query failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        await connector.close()
