"""Tests for Science Lab API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.agents._stubs import AgentResult  # noqa: E402
from openjarvis.science_lab.models import ConfidenceScore, ScienceProject  # noqa: E402
from openjarvis.science_lab.store import ScienceProjectStore  # noqa: E402
from openjarvis.server.science_lab_routes import science_lab_router  # noqa: E402


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.run.return_value = AgentResult(
        content="Resultado final",
        metadata={"refused": False, "reasoning_summary": [("OBJETIVO", "x")]},
    )
    return agent


@pytest.fixture
def app_with_agent(mock_agent):
    from fastapi import FastAPI

    app = FastAPI()
    app.state.science_lab_agent = mock_agent
    app.state.voice_service = None
    app.include_router(science_lab_router)
    return app


@pytest.fixture
def client(app_with_agent):
    return TestClient(app_with_agent)


def test_analyze_endpoint(client, mock_agent):
    response = client.post(
        "/v1/science-lab/analyze", json={"description": "quero um fluido tipo teia"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["content"] == "Resultado final"
    mock_agent.run.assert_called_once()


def test_analyze_no_agent_configured():
    from fastapi import FastAPI

    app = FastAPI()
    app.state.science_lab_agent = None
    app.include_router(science_lab_router)
    client = TestClient(app)

    response = client.post("/v1/science-lab/analyze", json={"description": "x"})
    assert response.status_code == 501


def test_analyze_surfaces_agent_error(client, mock_agent):
    mock_agent.run.side_effect = RuntimeError("engine unavailable")
    response = client.post("/v1/science-lab/analyze", json={"description": "x"})
    assert response.status_code == 500
    assert "engine unavailable" in response.json()["detail"]


def test_voice_status_unavailable(client):
    response = client.get("/v1/science-lab/voice/status")
    assert response.status_code == 200
    assert response.json() == {"available": False}


def test_voice_status_available():
    from fastapi import FastAPI

    svc = MagicMock()
    svc.status.return_value = {"state": "listening"}

    app = FastAPI()
    app.state.science_lab_agent = None
    app.state.voice_service = svc
    app.include_router(science_lab_router)
    client = TestClient(app)

    response = client.get("/v1/science-lab/voice/status")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["state"] == "listening"


def test_list_and_get_project_routes(client, tmp_path, monkeypatch):
    db_path = str(tmp_path / "science_lab.db")
    store = ScienceProjectStore(db_path=db_path)
    store.save(
        ScienceProject(
            name="spider-fluid", objective="test", confidence=ConfidenceScore(0.5)
        )
    )
    store.close()

    from openjarvis.core.config import load_config

    config = load_config()
    monkeypatch.setattr(config.science_lab, "db_path", db_path)
    monkeypatch.setattr("openjarvis.core.config.load_config", lambda: config)

    list_response = client.get("/v1/science-lab/projects")
    assert list_response.status_code == 200
    assert len(list_response.json()["projects"]) == 1

    get_response = client.get("/v1/science-lab/projects/spider-fluid")
    assert get_response.status_code == 200
    assert get_response.json()["objective"] == "test"

    missing_response = client.get("/v1/science-lab/projects/does-not-exist")
    assert missing_response.status_code == 404
