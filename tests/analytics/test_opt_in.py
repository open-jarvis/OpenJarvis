"""Default-off analytics must not create an identity or initialise sending."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.analytics.client import AnalyticsClient
from openjarvis.core.config import AnalyticsConfig, JarvisConfig, load_config
from openjarvis.server import analytics_routes


def test_missing_analytics_section_defaults_off(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[engine]\ndefault = "ollama"\n')
    assert load_config(path).analytics.enabled is False


def test_disabled_client_never_creates_id_or_initialises_sdk(
    tmp_path, monkeypatch
) -> None:
    init_sdk = MagicMock()
    monkeypatch.setattr(AnalyticsClient, "_init_sdk", init_sdk)
    cfg = AnalyticsConfig(anon_id_path=str(tmp_path / "anon_id"))
    client = AnalyticsClient(cfg)
    client.capture("app_opened", {"platform": "cli"})
    assert not client.enabled
    assert client.anon_id == ""
    assert not Path(cfg.anon_id_path).exists()
    init_sdk.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_identity_gates_frontend_and_id_creation(
    tmp_path, monkeypatch, enabled
) -> None:
    cfg = JarvisConfig()
    cfg.analytics.enabled = enabled
    cfg.analytics.anon_id_path = str(tmp_path / "anon_id")
    monkeypatch.setattr(analytics_routes, "load_config", lambda: cfg)
    app = FastAPI()
    app.include_router(analytics_routes.router)
    response = TestClient(app).get("/v1/analytics/identity")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is enabled
    assert bool(data["key"]) is enabled
    assert bool(data["anon_id"]) is enabled
    assert Path(cfg.analytics.anon_id_path).exists() is enabled
