"""An explicit UI choice must persist and immediately gate both senders."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import tomllib
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.analytics.client import AnalyticsClient
from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.core.events import EventBus, EventType
from openjarvis.server import analytics_routes
from openjarvis.server.auth_middleware import AuthMiddleware


@pytest.fixture
def preference_app(tmp_path: Path, monkeypatch):
    path = tmp_path / "custom-config.toml"
    path.write_text('# Keep this comment\n[engine]\ndefault = "ollama"\n')
    cfg = JarvisConfig()
    cfg._config_path = path
    cfg.analytics.anon_id_path = str(tmp_path / "anon_id")

    def fake_sdk(client):
        client._posthog = MagicMock()

    monkeypatch.setattr(AnalyticsClient, "_init_sdk", fake_sdk)
    app = FastAPI()
    app.state.config = cfg
    app.state.bus = EventBus()
    app.include_router(analytics_routes.router)
    yield app, path, cfg
    analytics_routes.stop_analytics(app)


def test_enable_and_disable_apply_immediately_and_survive_reload(preference_app):
    app, path, cfg = preference_app
    http = TestClient(app)
    assert http.get("/v1/analytics/identity").json()["enabled"] is False
    assert not Path(cfg.analytics.anon_id_path).exists()

    response = http.post("/v1/analytics/preference", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True
    assert response.json()["choice_recorded"] is True
    assert response.json()["key"]
    sdk = app.state.analytics_client._posthog
    closed = threading.Event()
    sdk.shutdown.side_effect = closed.set
    # Re-saving an enabled choice must not replace a working sender.
    assert (
        http.post("/v1/analytics/preference", json={"enabled": True}).status_code == 200
    )
    assert app.state.analytics_client._posthog is sdk
    app.state.bus.publish(EventType.FEEDBACK_RECEIVED, {"rating": 1})
    assert sdk.capture.call_count == 1

    response = http.post("/v1/analytics/preference", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["key"] == ""
    assert response.json()["anon_id"] == ""
    assert app.state.analytics_client is None
    assert app.state.analytics_bridge is None
    assert closed.wait(timeout=2)
    sdk.shutdown.assert_called_once()
    app.state.bus.publish(EventType.FEEDBACK_RECEIVED, {"rating": 2})
    assert sdk.capture.call_count == 1
    loaded = load_config(path)
    assert loaded.analytics.enabled is False
    assert loaded.analytics.choice_recorded is True
    assert loaded.engine.default == "ollama"
    assert "# Keep this comment" in path.read_text()


@pytest.mark.parametrize(
    "config_source", ["default", "environment", "explicit", "programmatic"]
)
@pytest.mark.parametrize("enabled", [False, True])
def test_preference_persists_to_active_config(
    preference_app, tmp_path, monkeypatch, config_source, enabled
):
    app, _, _ = preference_app
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("OPENJARVIS_HOME", str(home))
    monkeypatch.delenv("OPENJARVIS_CONFIG", raising=False)
    default_path = home / "config.toml"
    path = default_path
    if config_source in ("environment", "explicit"):
        path = tmp_path / "deployment.toml"
        default_path.write_text("# Leave the default configuration alone\n")
    if config_source == "environment":
        monkeypatch.setenv("OPENJARVIS_CONFIG", str(path))
    elif config_source == "explicit":
        # An explicit load path takes precedence over the environment too.
        monkeypatch.setenv("OPENJARVIS_CONFIG", str(tmp_path / "unused.toml"))
    path.write_text(f"[analytics]\nenabled = {str(not enabled).lower()}\n")
    load_config.cache_clear()
    try:
        if config_source == "programmatic":
            cfg = JarvisConfig()
            cfg.analytics.enabled = not enabled
        else:
            cfg = load_config(path if config_source == "explicit" else None)
        analytics_routes.configure_analytics(app, cfg)

        response = TestClient(app).post(
            "/v1/analytics/preference", json={"enabled": enabled}
        )

        assert response.status_code == 200
        assert response.json()["enabled"] is enabled
        load_config.cache_clear()
        reloaded = load_config(path if config_source == "explicit" else None)
        assert reloaded.analytics.enabled is enabled
        assert reloaded.analytics.choice_recorded is True
        if path != default_path:
            assert (
                default_path.read_text() == "# Leave the default configuration alone\n"
            )
        assert not (tmp_path / "unused.toml").exists()
    finally:
        load_config.cache_clear()


def test_decline_does_not_wait_for_an_unreachable_analytics_server(preference_app):
    app, path, cfg = preference_app
    http = TestClient(app)
    assert (
        http.post("/v1/analytics/preference", json={"enabled": True}).status_code == 200
    )
    sdk = app.state.analytics_client._posthog
    release = threading.Event()
    sdk.flush.side_effect = lambda: release.wait(5)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            response = executor.submit(
                http.post, "/v1/analytics/preference", json={"enabled": False}
            ).result(timeout=2)
        assert response.status_code == 200
        assert cfg.analytics.enabled is False
        assert app.state.analytics_client is None
    finally:
        release.set()


@pytest.mark.parametrize(
    "body",
    [
        {"enabled": "false"},
        {"enabled": 1},
        {"enabled": True, "email": "test@example.org"},
    ],
)
def test_preference_accepts_only_a_boolean_and_no_contest_details(preference_app, body):
    app, path, cfg = preference_app
    original = path.read_text()
    response = TestClient(app).post("/v1/analytics/preference", json=body)
    assert response.status_code == 422
    assert path.read_text() == original
    assert cfg.analytics.enabled is False
    assert not Path(cfg.analytics.anon_id_path).exists()


def test_failed_persistence_does_not_enable_sending(preference_app, monkeypatch):
    app, path, cfg = preference_app
    original = path.read_text()
    monkeypatch.setattr(
        analytics_routes.tempfile,
        "NamedTemporaryFile",
        MagicMock(side_effect=PermissionError("read-only config")),
    )
    response = TestClient(app).post("/v1/analytics/preference", json={"enabled": True})
    assert response.status_code == 500
    assert path.read_text() == original
    assert cfg.analytics.enabled is False
    assert not Path(cfg.analytics.anon_id_path).exists()


def test_preference_uses_existing_api_authentication(preference_app):
    app, path, cfg = preference_app
    app.add_middleware(AuthMiddleware, api_key="test-api-key")
    http = TestClient(app)
    assert (
        http.post("/v1/analytics/preference", json={"enabled": True}).status_code == 401
    )
    assert cfg.analytics.enabled is False
    response = http.post(
        "/v1/analytics/preference",
        json={"enabled": False},
        headers={"Authorization": "Bearer test-api-key"},
    )
    assert response.status_code == 200
    assert tomllib.loads(path.read_text())["analytics"]["choice_recorded"] is True
