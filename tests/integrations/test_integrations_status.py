"""Tests for the GET /v1/integrations/status route."""

from __future__ import annotations

import pytest

from openjarvis.server.integrations_routes import integrations_status


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Strip every env var in ENV_REGISTRY (and known aliases) for each test."""
    from openjarvis.core.env import ENV_REGISTRY

    for spec in ENV_REGISTRY.values():
        monkeypatch.delenv(spec.name, raising=False)
        for alias in spec.aliases:
            monkeypatch.delenv(alias, raising=False)


@pytest.mark.asyncio
async def test_unconfigured_integrations_show_unhealthy_with_reason():
    payload = await integrations_status()
    integrations = payload["integrations"]

    assert "openai" in integrations
    openai = integrations["openai"]
    assert openai["configured"] is False
    assert openai["healthy"] is False
    assert "OPENAI_API_KEY" in openai["reason"]

    cloudinary = integrations["cloudinary"]
    assert cloudinary["configured"] is False
    # All three Cloudinary vars should be listed as missing.
    missing = cloudinary["reason"]
    for var in ("CLOUDINARY_API_KEY", "CLOUDINARY_API_SECRET", "CLOUDINARY_CLOUD_NAME"):
        assert var in missing


@pytest.mark.asyncio
async def test_openai_alias_marks_integration_healthy(monkeypatch):
    """Setting only OpenAI_API (the Railway alias) should still report healthy."""
    monkeypatch.setenv("OpenAI_API", "sk-railway-value")
    # Trigger the alias pass to mirror app startup.
    from openjarvis.core.env import apply_aliases

    apply_aliases()

    payload = await integrations_status()
    openai = payload["integrations"]["openai"]
    assert openai["configured"] is True
    assert openai["healthy"] is True
    assert openai["reason"] == ""


@pytest.mark.asyncio
async def test_github_token_fallback(monkeypatch):
    """GITHUB_TOKEN alone should satisfy the GITHUB_PAT requirement."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-fallback")
    from openjarvis.core.env import apply_aliases

    apply_aliases()

    payload = await integrations_status()
    github = payload["integrations"]["github"]
    assert github["configured"] is True


@pytest.mark.asyncio
async def test_var_listing_includes_alias_metadata():
    payload = await integrations_status()
    openai_vars = payload["integrations"]["openai"]["vars"]
    spec = next(v for v in openai_vars if v["name"] == "OPENAI_API_KEY")
    assert "OpenAI_API" in spec["aliases"]
    assert spec["secret"] is True
