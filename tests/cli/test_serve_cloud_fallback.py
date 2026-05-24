"""Tests for local-first cloud exposure in ``jarvis serve``."""

from __future__ import annotations

from openjarvis.cli.serve import _cloud_multi_enabled
from openjarvis.core.config import JarvisConfig


def test_cloud_multi_disabled_by_default_even_with_api_key(monkeypatch) -> None:
    cfg = JarvisConfig()
    cfg.engine.allow_cloud_fallback = False
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert _cloud_multi_enabled(cfg, "ollama") is False


def test_cloud_multi_enabled_when_user_opts_in(monkeypatch) -> None:
    cfg = JarvisConfig()
    cfg.engine.allow_cloud_fallback = True
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert _cloud_multi_enabled(cfg, "ollama") is True


def test_cloud_multi_not_used_when_cloud_is_primary(monkeypatch) -> None:
    cfg = JarvisConfig()
    cfg.engine.allow_cloud_fallback = True
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    assert _cloud_multi_enabled(cfg, "cloud") is False
