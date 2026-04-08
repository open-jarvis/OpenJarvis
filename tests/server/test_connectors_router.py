"""Tests for the /v1/connectors API router."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def app():
    try:
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
    except ImportError:
        pytest.skip("fastapi not installed")

    from openjarvis.server.connectors_router import create_connectors_router

    _app = FastAPI()
    router = create_connectors_router()
    _app.include_router(router)
    return TestClient(_app)


def test_list_connectors(app):
    """GET /v1/connectors returns a list that includes the obsidian connector."""
    resp = app.get("/v1/connectors")
    assert resp.status_code == 200
    data = resp.json()
    assert "connectors" in data
    ids = [c["connector_id"] for c in data["connectors"]]
    assert "obsidian" in ids


def test_connector_detail(app):
    """GET /v1/connectors/obsidian returns the expected fields."""
    resp = app.get("/v1/connectors/obsidian")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert "display_name" in data
    assert "auth_type" in data
    assert "connected" in data
    assert "mcp_tools" in data


def test_connector_not_found(app):
    """GET /v1/connectors/nonexistent returns 404."""
    resp = app.get("/v1/connectors/nonexistent")
    assert resp.status_code == 404


def test_connect_obsidian(app, tmp_path):
    """POST /v1/connectors/obsidian/connect with a valid path marks it connected."""
    # Create a minimal vault directory so is_connected() returns True.
    vault = tmp_path / "vault"
    vault.mkdir()

    resp = app.post("/v1/connectors/obsidian/connect", json={"path": str(vault)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert data["connected"] is True


def test_disconnect(app):
    """POST /v1/connectors/obsidian/disconnect returns 200 with connected=False."""
    resp = app.post("/v1/connectors/obsidian/disconnect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_id"] == "obsidian"
    assert data["connected"] is False


def test_sync_status(app):
    """GET /v1/connectors/obsidian/sync returns a response with a state field."""
    resp = app.get("/v1/connectors/obsidian/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert data["connector_id"] == "obsidian"


def test_trigger_sync(app, tmp_path: Path) -> None:
    """POST /v1/connectors/obsidian/sync triggers an incremental sync."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Test note\n\nContent here.")
    app.post("/v1/connectors/obsidian/connect", json={"path": str(vault)})
    resp = app.post("/v1/connectors/obsidian/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chunks_indexed"] >= 1


def test_list_connectors_closes_store_connections(app, monkeypatch) -> None:
    """GET /v1/connectors closes every KnowledgeStore it opens (regression)."""
    from openjarvis.connectors import store as store_module

    close_calls = 0
    original_close = store_module.KnowledgeStore.close

    def counted_close(self: store_module.KnowledgeStore) -> None:
        nonlocal close_calls
        close_calls += 1
        original_close(self)

    monkeypatch.setattr(store_module.KnowledgeStore, "close", counted_close)

    resp = app.get("/v1/connectors")
    assert resp.status_code == 200
    num_connectors = len(resp.json()["connectors"])
    assert num_connectors > 0

    baseline = close_calls
    polls = 3
    for _ in range(polls):
        assert app.get("/v1/connectors").status_code == 200

    assert close_calls - baseline == polls * num_connectors
