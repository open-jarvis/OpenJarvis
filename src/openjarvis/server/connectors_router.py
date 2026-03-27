"""FastAPI router for /v1/connectors — connector management endpoints."""

from __future__ import annotations

from typing import Any, Dict, Optional

# Module-level cache of connector instances (keyed by connector_id).
_instances: Dict[str, Any] = {}


def _ensure_connectors_registered() -> None:
    """Ensure ConnectorRegistry is populated.

    If the registry has been cleared (e.g. by test fixtures) but connector
    modules are already cached in sys.modules, reload each submodule to
    re-execute their @ConnectorRegistry.register decorators.
    """
    import importlib
    import sys

    from openjarvis.core.registry import ConnectorRegistry

    # First, try a normal import (works if modules haven't been imported yet).
    try:
        import openjarvis.connectors  # noqa: F401
    except Exception:
        pass

    # If the registry is still empty, reload individual connector submodules
    # that are already present in sys.modules.
    if not ConnectorRegistry.keys():
        for mod_name in list(sys.modules):
            if (
                mod_name.startswith("openjarvis.connectors.")
                and not mod_name.endswith("_stubs")
                and not mod_name.endswith("pipeline")
                and not mod_name.endswith("store")
                and not mod_name.endswith("chunker")
                and not mod_name.endswith("retriever")
                and not mod_name.endswith("sync_engine")
                and not mod_name.endswith("oauth")
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# Pydantic request model — defined at module level so FastAPI can resolve
# the type annotation correctly when injecting request bodies.
# ---------------------------------------------------------------------------

try:
    from pydantic import BaseModel as _BaseModel

    class ConnectRequest(_BaseModel):
        """Credentials / connection parameters for a connector."""

        path: Optional[str] = None
        token: Optional[str] = None
        code: Optional[str] = None
        email: Optional[str] = None
        password: Optional[str] = None

except ImportError:
    ConnectRequest = None  # type: ignore[assignment,misc]


def create_connectors_router():
    """Return an APIRouter with /connectors endpoints.

    Importing FastAPI inside the factory avoids a hard import-time
    dependency and mirrors the pattern used by other optional routers in
    this package.
    """
    try:
        from fastapi import APIRouter, HTTPException
    except ImportError as exc:
        raise ImportError(
            "fastapi and pydantic are required for the connectors router"
        ) from exc

    if ConnectRequest is None:
        raise ImportError("pydantic is required for the connectors router")

    from openjarvis.core.registry import ConnectorRegistry

    router = APIRouter(prefix="/connectors", tags=["connectors"])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_or_create(connector_id: str) -> Any:
        """Return a cached connector instance, creating it if needed."""
        if connector_id not in _instances:
            cls = ConnectorRegistry.get(connector_id)
            _instances[connector_id] = cls()
        return _instances[connector_id]

    def _connector_summary(connector_id: str, instance: Any) -> Dict[str, Any]:
        """Build the dict returned by GET /connectors."""
        return {
            "connector_id": connector_id,
            "display_name": getattr(instance, "display_name", connector_id),
            "auth_type": getattr(instance, "auth_type", "unknown"),
            "connected": instance.is_connected(),
        }

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @router.get("")
    async def list_connectors():
        """List all registered connectors with their connection status."""
        _ensure_connectors_registered()
        results = []
        for key in sorted(ConnectorRegistry.keys()):
            try:
                instance = _get_or_create(key)
                results.append(_connector_summary(key, instance))
            except Exception:
                results.append(
                    {
                        "connector_id": key,
                        "display_name": key,
                        "auth_type": "unknown",
                        "connected": False,
                    }
                )
        return {"connectors": results}

    @router.get("/{connector_id}")
    async def connector_detail(connector_id: str):
        """Return detail for a single connector."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        instance = _get_or_create(connector_id)

        # Try to get an OAuth URL if applicable; ignore errors for non-OAuth
        # connectors.
        auth_url: Optional[str] = None
        try:
            auth_url = instance.auth_url()
        except (NotImplementedError, Exception):
            pass

        # Serialise MCP tool names only (ToolSpec objects are not JSON-safe).
        mcp_tools = []
        try:
            mcp_tools = [t.name for t in instance.mcp_tools()]
        except Exception:
            pass

        return {
            "connector_id": connector_id,
            "display_name": getattr(instance, "display_name", connector_id),
            "auth_type": getattr(instance, "auth_type", "unknown"),
            "connected": instance.is_connected(),
            "auth_url": auth_url,
            "mcp_tools": mcp_tools,
        }

    @router.post("/{connector_id}/connect")
    async def connect_connector(connector_id: str, req: ConnectRequest):
        """Connect a connector using the supplied credentials."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        instance = _get_or_create(connector_id)

        try:
            auth_type = getattr(instance, "auth_type", "unknown")

            if auth_type == "filesystem":
                # Filesystem connectors accept a vault / directory path.
                if req.path:
                    instance._vault_path = req.path
                    from pathlib import Path

                    instance._connected = Path(req.path).is_dir()

            elif auth_type == "oauth":
                if req.code:
                    instance.handle_callback(req.code)
                elif req.token:
                    # Some OAuth connectors accept a pre-existing token.
                    if hasattr(instance, "_token"):
                        instance._token = req.token

            else:
                # Generic: try to store token or credentials if the instance
                # exposes the relevant attributes.
                if req.token and hasattr(instance, "_token"):
                    instance._token = req.token
                if req.email and hasattr(instance, "_email"):
                    instance._email = req.email
                if req.password and hasattr(instance, "_password"):
                    instance._password = req.password

        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        return {
            "connector_id": connector_id,
            "connected": instance.is_connected(),
            "status": "connected" if instance.is_connected() else "pending",
        }

    @router.post("/{connector_id}/disconnect")
    async def disconnect_connector(connector_id: str):
        """Disconnect a connector and clear its credentials."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        instance = _get_or_create(connector_id)
        try:
            instance.disconnect()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return {
            "connector_id": connector_id,
            "connected": False,
            "status": "disconnected",
        }

    @router.post("/{connector_id}/sync")
    def trigger_sync(connector_id: str) -> Dict[str, Any]:
        """Trigger an incremental sync for a connector."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        inst = _get_or_create(connector_id)
        if not inst.is_connected():
            raise HTTPException(
                status_code=400,
                detail=f"Connector '{connector_id}' is not connected",
            )

        from openjarvis.connectors.pipeline import IngestionPipeline
        from openjarvis.connectors.store import KnowledgeStore
        from openjarvis.connectors.sync_engine import SyncEngine

        store = KnowledgeStore()
        pipeline = IngestionPipeline(store=store)
        engine = SyncEngine(pipeline=pipeline)
        chunks = engine.sync(inst)

        return {
            "connector_id": connector_id,
            "chunks_indexed": chunks,
            "status": "complete",
        }

    @router.get("/{connector_id}/sync")
    async def sync_status(connector_id: str):
        """Return the current sync status for a connector."""
        _ensure_connectors_registered()
        if not ConnectorRegistry.contains(connector_id):
            raise HTTPException(
                status_code=404,
                detail=f"Connector '{connector_id}' not found",
            )
        instance = _get_or_create(connector_id)
        try:
            status = instance.sync_status()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        return {
            "connector_id": connector_id,
            "state": status.state,
            "items_synced": status.items_synced,
            "items_total": status.items_total,
            "last_sync": (status.last_sync.isoformat() if status.last_sync else None),
            "error": status.error,
        }

    return router


__all__ = ["ConnectRequest", "create_connectors_router"]
