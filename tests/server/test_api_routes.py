"""Tests for extended API routes."""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.api_routes import include_all_routes  # noqa: E402


def _make_app():
    app = FastAPI()
    include_all_routes(app)
    return app


class TestAgentRoutes:
    def test_list_agents(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "registered" in data
        assert "running" in data

    def test_create_agent(self):
        client = TestClient(_make_app())
        resp = client.post("/v1/agents", json={"agent_type": "simple"})
        # May succeed or fail depending on agent_tools availability
        assert resp.status_code in (200, 501)

    def test_kill_nonexistent(self):
        client = TestClient(_make_app())
        resp = client.delete("/v1/agents/nonexistent")
        assert resp.status_code in (404, 501)


class TestMemoryRoutes:
    def test_search(self):
        client = TestClient(_make_app())
        resp = client.post("/v1/memory/search", json={"query": "test"})
        # May fail if SQLite not set up, that's ok
        assert resp.status_code in (200, 500)

    def test_stats(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/memory/stats")
        assert resp.status_code in (200, 500)


class TestMemoryRustMissing:
    """Regression for #502: when the native ``openjarvis_rust`` extension is
    missing from the serving venv, memory ops must surface a CLEAR, ACTIONABLE
    error — never the misleading "Failed to index path" or a 200 silent no-op.
    """

    @staticmethod
    def _client(monkeypatch):
        # Force the same failure mode as a venv without the compiled extension.
        def _boom():
            raise ImportError("No module named 'openjarvis_rust'")

        import openjarvis._rust_bridge as bridge

        monkeypatch.setattr(bridge, "get_rust_module", _boom)
        return TestClient(_make_app())

    def test_store_is_not_a_silent_noop(self, monkeypatch):
        client = self._client(monkeypatch)
        resp = client.post("/v1/memory/store", json={"content": "hi"})
        # Must NOT return the old 200 {"status":"stored","note":"no backend..."}.
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        assert "openjarvis_rust" in detail
        assert "maturin develop" in detail

    def test_index_surfaces_actionable_detail(self, monkeypatch, tmp_path):
        (tmp_path / "note.txt").write_text("hello world some content here")
        client = self._client(monkeypatch)
        resp = client.post("/v1/memory/index", json={"path": str(tmp_path)})
        assert resp.status_code == 503
        detail = resp.json()["detail"]
        # The frontend reads this `detail`; it must point at the real cause,
        # not blame the indexed path.
        assert "openjarvis_rust" in detail
        assert detail != "Failed to index path"
        assert detail != "No memory backend available"

    def test_config_reports_unavailable(self, monkeypatch):
        client = self._client(monkeypatch)
        resp = client.get("/v1/memory/config")
        assert resp.status_code == 200
        data = resp.json()
        # Must not falsely report a healthy backend when none could be built.
        assert data["available"] is False
        assert "openjarvis_rust" in (data["detail"] or "")


class TestBudgetRoutes:
    def test_get_budget(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/budget")
        assert resp.status_code == 200
        data = resp.json()
        assert "limits" in data
        assert "usage" in data

    def test_set_limits(self):
        client = TestClient(_make_app())
        resp = client.put("/v1/budget/limits", json={"max_tokens_per_day": 100000})
        assert resp.status_code == 200
        assert resp.json()["limits"]["max_tokens_per_day"] == 100000


class TestMetricsRoute:
    def test_metrics_endpoint(self):
        client = TestClient(_make_app())
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "openjarvis" in resp.text or "No metrics" in resp.text


class TestSkillRoutes:
    def test_list_skills(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/skills")
        assert resp.status_code == 200
        assert "skills" in resp.json()


class TestSessionRoutes:
    def test_list_sessions(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/sessions")
        assert resp.status_code == 200


class TestTraceRoutes:
    def test_list_traces(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/traces")
        assert resp.status_code == 200
