"""Tests for extended API routes."""

import inspect
from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.core.events import EventBus, EventType  # noqa: E402
from openjarvis.security.capabilities import CapabilityPolicy  # noqa: E402
from openjarvis.server.api_routes import (  # noqa: E402
    include_all_routes,
    memory_index,
    memory_search,
    memory_stats,
    memory_store,
)


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

    def test_admin_lifecycle_is_capability_gated_before_mutation(self):
        from openjarvis.tools.agent_tools import _SPAWNED_AGENTS

        app = _make_app()
        app.state.bus = EventBus(record_history=True)
        app.state.capability_policy = CapabilityPolicy(default_deny=True)
        app.state.rate_limiter = None
        _SPAWNED_AGENTS.pop("forbidden-api-agent", None)

        resp = TestClient(app).post(
            "/v1/agents",
            json={
                "agent_type": "simple",
                "agent_id": "forbidden-api-agent",
            },
        )

        assert resp.status_code == 403
        assert "forbidden-api-agent" not in _SPAWNED_AGENTS
        denied = [
            event
            for event in app.state.bus.history
            if event.event_type == EventType.CAPABILITY_DENIED
        ]
        assert denied[-1].data == {
            "agent_id": "server:api",
            "capability": "system:admin",
            "tool": "agent_spawn",
        }

    def test_agent_listing_is_capability_gated_before_disclosure(self):
        from openjarvis.tools.agent_tools import _SPAWNED_AGENTS

        app = _make_app()
        app.state.bus = EventBus(record_history=True)
        app.state.capability_policy = CapabilityPolicy(default_deny=True)
        app.state.rate_limiter = None
        _SPAWNED_AGENTS["private-api-agent"] = {
            "agent_id": "private-api-agent",
            "agent_type": "simple",
            "status": "running",
            "created_at": 0.0,
        }
        try:
            resp = TestClient(app).get("/v1/agents")
        finally:
            _SPAWNED_AGENTS.pop("private-api-agent", None)

        assert resp.status_code == 403
        assert "private-api-agent" not in resp.text
        assert any(
            event.event_type == EventType.CAPABILITY_DENIED
            and event.data
            == {
                "agent_id": "server:api",
                "capability": "system:admin",
                "tool": "agent_list",
            }
            for event in app.state.bus.history
        )

    def test_admin_lifecycle_is_rate_limited_before_mutation(self):
        from openjarvis.tools.agent_tools import _SPAWNED_AGENTS

        class _DenyLimiter:
            def __init__(self) -> None:
                self.keys = []

            def check(self, key: str):
                self.keys.append(key)
                return False, 2.5

        app = _make_app()
        app.state.bus = EventBus(record_history=True)
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("server:api", "system:admin")
        limiter = _DenyLimiter()
        app.state.capability_policy = policy
        app.state.rate_limiter = limiter
        _SPAWNED_AGENTS.pop("limited-api-agent", None)

        resp = TestClient(app).post(
            "/v1/agents",
            json={"agent_type": "simple", "agent_id": "limited-api-agent"},
        )

        assert resp.status_code == 429
        assert "limited-api-agent" not in _SPAWNED_AGENTS
        assert limiter.keys == ["server:api:agent_spawn"]
        assert any(
            event.event_type == EventType.RATE_LIMITED
            and event.data["agent_id"] == "server:api"
            for event in app.state.bus.history
        )

    def test_agent_listing_is_rate_limited_before_disclosure(self):
        class _DenyLimiter:
            def __init__(self) -> None:
                self.keys = []

            def check(self, key: str):
                self.keys.append(key)
                return False, 2.5

        app = _make_app()
        app.state.bus = EventBus(record_history=True)
        policy = CapabilityPolicy(default_deny=True)
        policy.grant("server:api", "system:admin")
        limiter = _DenyLimiter()
        app.state.capability_policy = policy
        app.state.rate_limiter = limiter

        resp = TestClient(app).get("/v1/agents")

        assert resp.status_code == 429
        assert limiter.keys == ["server:api:agent_list"]
        assert any(
            event.event_type == EventType.RATE_LIMITED
            and event.data["agent_id"] == "server:api"
            and event.data["tool"] == "agent_list"
            for event in app.state.bus.history
        )


class TestMemoryRoutes:
    # 503 is the documented response when the native ``openjarvis_rust``
    # extension is absent from the venv (see TestMemoryRustMissing below).
    # These tests are only asserting "the route is wired up", so a backend
    # that cannot be built is tolerated the same way a 500 is.
    _BACKEND_OPTIONAL = (200, 500, 503)

    def test_blocking_memory_handlers_use_starlette_threadpool(self):
        """Sync endpoints are automatically dispatched to worker threads."""
        for handler in (memory_store, memory_search, memory_stats, memory_index):
            assert not inspect.iscoroutinefunction(handler)

    def test_search(self):
        client = TestClient(_make_app())
        resp = client.post("/v1/memory/search", json={"query": "test"})
        # May fail if SQLite not set up, that's ok
        assert resp.status_code in self._BACKEND_OPTIONAL

    def test_stats(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/memory/stats")
        assert resp.status_code in self._BACKEND_OPTIONAL


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
    def test_metrics_endpoint(self, tmp_path, monkeypatch):
        """An isolated empty config dir returns the exact no-data response.

        Pinning ``DEFAULT_CONFIG_DIR`` keeps the test independent of the
        machine's real telemetry database and makes any other response a
        regression rather than accepting all possible production states.
        """
        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))

        client = TestClient(_make_app())
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.text == "# no telemetry data\n"
        assert resp.headers["content-type"].startswith("text/plain")

    def test_metrics_endpoint_reports_real_stats(self, tmp_path, monkeypatch):
        """Regression for #760: /metrics must report actual aggregated
        stats instead of silently falling back to the placeholder text.

        The handler called ``stats.get(...)`` on ``AggregatedStats``, a
        dataclass with no ``.get()`` method -- every real request raised
        ``AttributeError``, caught by the broad ``except Exception`` and
        papered over as "No metrics available", even with real telemetry
        data present in ``telemetry.db``.
        """
        import time

        from openjarvis.core.types import TelemetryRecord
        from openjarvis.telemetry.store import TelemetryStore

        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))

        db_path = tmp_path / "telemetry.db"
        store = TelemetryStore(db_path)
        store.record(
            TelemetryRecord(
                timestamp=time.time(),
                model_id="test-model",
                engine="ollama",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                latency_seconds=2.0,
                cost_usd=0.001,
            )
        )
        store.close()

        client = TestClient(_make_app())
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "No metrics available" not in resp.text
        assert "openjarvis_requests_total 1" in resp.text
        assert "openjarvis_tokens_total 15" in resp.text
        assert "openjarvis_latency_avg_ms 2000" in resp.text

    def test_metrics_endpoint_empty_db_no_division_by_zero(self, tmp_path, monkeypatch):
        """An existing but empty telemetry.db (total_calls=0) must not
        raise ZeroDivisionError when computing average latency."""
        from openjarvis.telemetry.store import TelemetryStore

        monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path))

        db_path = tmp_path / "telemetry.db"
        TelemetryStore(db_path).close()  # creates the schema, no records

        client = TestClient(_make_app())
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "No metrics available" not in resp.text
        assert "openjarvis_requests_total 0" in resp.text
        assert "openjarvis_latency_avg_ms 0" in resp.text

    def test_metrics_endpoint_uses_active_app_telemetry_path(self, tmp_path):
        import time

        from openjarvis.core.types import TelemetryRecord
        from openjarvis.telemetry.store import TelemetryStore

        db_path = tmp_path / "runtime" / "custom-telemetry.sqlite"
        store = TelemetryStore(db_path)
        store.record(
            TelemetryRecord(
                timestamp=time.time(),
                model_id="configured-model",
                engine="ollama",
                prompt_tokens=4,
                completion_tokens=3,
                total_tokens=7,
                latency_seconds=0.5,
                cost_usd=0.0,
            )
        )
        store.close()

        app = _make_app()
        app.state.config = SimpleNamespace(
            telemetry=SimpleNamespace(db_path=str(db_path))
        )
        resp = TestClient(app).get("/metrics")

        assert resp.status_code == 200
        assert "openjarvis_requests_total 1" in resp.text
        assert "openjarvis_tokens_total 7" in resp.text
        assert "openjarvis_latency_avg_ms 500" in resp.text


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
