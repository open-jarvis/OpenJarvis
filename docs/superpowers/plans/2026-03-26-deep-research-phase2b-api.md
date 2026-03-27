# Deep Research Phase 2B-i: Connector Management API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FastAPI endpoints for connector management so the desktop wizard and CLI can list sources, initiate OAuth, check sync status, and trigger syncs — all via HTTP.

**Architecture:** A new `connectors` API router exposes endpoints for listing available connectors, initiating auth flows, checking connection status, triggering syncs, and streaming sync progress. The router wraps the existing `ConnectorRegistry`, `SyncEngine`, and `KnowledgeStore` from Phase 1. An OAuth callback server handles the browser redirect during auth flows.

**Tech Stack:** Python 3.10+, FastAPI (existing server infrastructure), pytest + httpx (test client)

**Spec:** `docs/superpowers/specs/2026-03-25-deep-research-setup-design.md` — Sections 4, 10

**Depends on:** Phase 1 (ConnectorRegistry, BaseConnector, SyncEngine, KnowledgeStore)

---

## File Structure

```
src/openjarvis/server/
├── connectors_router.py     # FastAPI router: /v1/connectors/* endpoints

tests/server/
├── test_connectors_router.py  # API endpoint tests
```

---

### Task 1: Connectors API Router

**Files:**
- Create: `src/openjarvis/server/connectors_router.py`
- Create: `tests/server/test_connectors_router.py`

- [ ] **Step 1: Write failing tests**

Create `tests/server/test_connectors_router.py`:

```python
"""Tests for the /v1/connectors API endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.server.connectors_router import create_connectors_router


@pytest.fixture
def app():
    """Create a minimal FastAPI app with the connectors router."""
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    app = FastAPI()
    router = create_connectors_router()
    app.include_router(router, prefix="/v1")
    return TestClient(app)


def test_list_connectors(app) -> None:
    """GET /v1/connectors returns list of available connectors."""
    resp = app.get("/v1/connectors")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # Should have at least obsidian (always available)
    ids = [c["connector_id"] for c in data]
    assert "obsidian" in ids


def test_connector_detail(app) -> None:
    """GET /v1/connectors/{id} returns connector info."""
    resp = app.get("/v1/connectors/obsidian")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert data["auth_type"] == "filesystem"
    assert "connected" in data


def test_connector_not_found(app) -> None:
    """GET /v1/connectors/{id} returns 404 for unknown."""
    resp = app.get("/v1/connectors/nonexistent")
    assert resp.status_code == 404


def test_connect_obsidian(app, tmp_path: Path) -> None:
    """POST /v1/connectors/obsidian/connect with path."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Test")
    resp = app.post(
        "/v1/connectors/obsidian/connect",
        json={"path": str(vault)},
    )
    assert resp.status_code == 200
    assert resp.json()["connected"] is True


def test_disconnect(app) -> None:
    """POST /v1/connectors/obsidian/disconnect."""
    resp = app.post("/v1/connectors/obsidian/disconnect")
    assert resp.status_code == 200


def test_sync_status(app) -> None:
    """GET /v1/connectors/obsidian/sync returns sync status."""
    resp = app.get("/v1/connectors/obsidian/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/server/test_connectors_router.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement connectors router**

Create `src/openjarvis/server/connectors_router.py`:

```python
"""FastAPI router for connector management: /v1/connectors/*

Exposes endpoints for listing connectors, connecting/disconnecting,
checking status, and triggering syncs.  Used by the desktop wizard
and CLI.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from openjarvis.connectors._stubs import SyncStatus
from openjarvis.core.registry import ConnectorRegistry

logger = logging.getLogger(__name__)

# Connector instances cache (keyed by connector_id)
_instances: Dict[str, Any] = {}


def _get_or_create(connector_id: str, **kwargs: Any) -> Any:
    """Get a cached connector instance or create one."""
    if connector_id not in _instances:
        cls = ConnectorRegistry.get(connector_id)
        _instances[connector_id] = cls(**kwargs)
    return _instances[connector_id]


def create_connectors_router():
    """Factory that returns a FastAPI APIRouter for /v1/connectors.

    Separated from module-level to allow lazy import of FastAPI.
    """
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    router = APIRouter(tags=["connectors"])

    class ConnectRequest(BaseModel):
        path: Optional[str] = None
        token: Optional[str] = None
        code: Optional[str] = None
        email: Optional[str] = None
        password: Optional[str] = None

    class ConnectorInfo(BaseModel):
        connector_id: str
        display_name: str
        auth_type: str
        connected: bool

    # Import connectors to trigger registration
    import openjarvis.connectors  # noqa: F401

    @router.get("/connectors")
    def list_connectors() -> List[Dict[str, Any]]:
        """List all available data source connectors."""
        results = []
        for key in sorted(ConnectorRegistry.keys()):
            cls = ConnectorRegistry.get(key)
            try:
                inst = _get_or_create(key)
                connected = inst.is_connected()
            except Exception:
                connected = False
            results.append(
                {
                    "connector_id": key,
                    "display_name": getattr(
                        cls, "display_name", key
                    ),
                    "auth_type": getattr(cls, "auth_type", "unknown"),
                    "connected": connected,
                }
            )
        return results

    @router.get("/connectors/{connector_id}")
    def get_connector(connector_id: str) -> Dict[str, Any]:
        """Get details for a specific connector."""
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        cls = ConnectorRegistry.get(connector_id)
        try:
            inst = _get_or_create(connector_id)
            connected = inst.is_connected()
        except Exception:
            connected = False

        auth_url = ""
        try:
            inst = _get_or_create(connector_id)
            auth_url = inst.auth_url()
        except NotImplementedError:
            pass

        mcp_tools = []
        try:
            inst = _get_or_create(connector_id)
            mcp_tools = [t.name for t in inst.mcp_tools()]
        except Exception:
            pass

        return {
            "connector_id": connector_id,
            "display_name": getattr(cls, "display_name", connector_id),
            "auth_type": getattr(cls, "auth_type", "unknown"),
            "connected": connected,
            "auth_url": auth_url,
            "mcp_tools": mcp_tools,
        }

    @router.post("/connectors/{connector_id}/connect")
    def connect_source(
        connector_id: str, req: ConnectRequest
    ) -> Dict[str, Any]:
        """Connect a data source."""
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        cls = ConnectorRegistry.get(connector_id)
        auth_type = getattr(cls, "auth_type", "")

        if auth_type == "filesystem" and req.path:
            inst = cls(vault_path=req.path)
            _instances[connector_id] = inst
            return {"connected": inst.is_connected()}

        if req.token:
            inst = cls(token=req.token)
            _instances[connector_id] = inst
            return {"connected": inst.is_connected()}

        if req.code:
            inst = _get_or_create(connector_id)
            inst.handle_callback(req.code)
            return {"connected": inst.is_connected()}

        if req.email and req.password:
            inst = cls(
                email_address=req.email,
                app_password=req.password,
            )
            _instances[connector_id] = inst
            return {"connected": inst.is_connected()}

        raise HTTPException(
            status_code=400,
            detail="Provide path, token, code, or email+password",
        )

    @router.post("/connectors/{connector_id}/disconnect")
    def disconnect_source(connector_id: str) -> Dict[str, Any]:
        """Disconnect a data source."""
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        inst = _get_or_create(connector_id)
        inst.disconnect()
        return {"disconnected": True}

    @router.get("/connectors/{connector_id}/sync")
    def get_sync_status(connector_id: str) -> Dict[str, Any]:
        """Get sync status for a connector."""
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        inst = _get_or_create(connector_id)
        status = inst.sync_status()
        return {
            "state": status.state,
            "items_synced": status.items_synced,
            "items_total": status.items_total,
            "last_sync": (
                status.last_sync.isoformat() if status.last_sync else None
            ),
            "error": status.error,
        }

    return router
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/server/test_connectors_router.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Run linter**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run ruff check src/openjarvis/server/connectors_router.py`

Expected: No errors.

- [ ] **Step 6: Commit**

```bash
git add src/openjarvis/server/connectors_router.py tests/server/test_connectors_router.py
git commit -m "feat: add /v1/connectors API router for connector management"
```

---

## Post-Plan Notes

**What this plan produces:**
- `GET /v1/connectors` — list all available connectors with connection status
- `GET /v1/connectors/{id}` — connector detail with auth_url and MCP tools
- `POST /v1/connectors/{id}/connect` — connect with path, token, code, or email+password
- `POST /v1/connectors/{id}/disconnect` — disconnect a source
- `GET /v1/connectors/{id}/sync` — sync status (state, items_synced, items_total, error)

**Phase 2B-ii (Frontend wizard)** will consume these endpoints to build:
- Source picker grid (calls `GET /v1/connectors`)
- Per-source OAuth flow (calls `GET /v1/connectors/{id}` for auth_url, then `POST .../connect`)
- Ingest progress dashboard (polls `GET /v1/connectors/{id}/sync`)
- New Tauri commands wrapping these endpoints

**Phase 2B-ii is a TypeScript/React effort** — separate plan needed for the frontend components, Tauri commands, and wizard UI.
