"""Tests for the env-var registry, fallback reader, and alias pass."""

from __future__ import annotations

import os

import pytest

from openjarvis.core.env import (
    ENV_REGISTRY,
    apply_aliases,
    get_env,
    is_configured,
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Each test gets a clean slate for the env vars we touch."""
    for name in (
        "OPENAI_API_KEY",
        "OpenAI_API",
        "OPENAI_API",
        "ANTHROPIC_API_KEY",
        "GITHUB_PAT",
        "GITHUB_TOKEN",
        "DEEPSEEK_API_KEY",
        "OBSIDIAN_VAULT_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_get_env_returns_first_non_empty():
    os.environ["B"] = "from-b"
    os.environ["C"] = "from-c"
    try:
        assert get_env("A", "B", "C") == "from-b"
    finally:
        del os.environ["B"]
        del os.environ["C"]


def test_get_env_returns_default_when_all_missing():
    assert get_env("NOPE_1", "NOPE_2", default="fallback") == "fallback"
    assert get_env("NOPE_1", "NOPE_2") is None


def test_get_env_skips_empty_strings():
    os.environ["EMPTY"] = ""
    os.environ["FILLED"] = "v"
    try:
        assert get_env("EMPTY", "FILLED") == "v"
    finally:
        del os.environ["EMPTY"]
        del os.environ["FILLED"]


def test_apply_aliases_populates_canonical_from_alias(monkeypatch):
    """The OpenAI Railway-quirk case: only the alias is set."""
    monkeypatch.setenv("OpenAI_API", "sk-railway-value")
    populated = apply_aliases()
    assert "OPENAI_API_KEY" in populated
    assert os.environ["OPENAI_API_KEY"] == "sk-railway-value"


def test_apply_aliases_idempotent(monkeypatch):
    monkeypatch.setenv("OpenAI_API", "sk-1")
    apply_aliases()
    populated = apply_aliases()  # second call
    # Canonical is already set; nothing to populate.
    assert "OPENAI_API_KEY" not in populated


def test_apply_aliases_does_not_overwrite_existing_canonical(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-canonical")
    monkeypatch.setenv("OpenAI_API", "sk-alias-loses")
    apply_aliases()
    assert os.environ["OPENAI_API_KEY"] == "sk-canonical"


def test_github_pat_falls_back_to_github_token(monkeypatch):
    """GITHUB_TOKEN is a documented alias for GITHUB_PAT."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp-fallback")
    apply_aliases()
    assert os.environ.get("GITHUB_PAT") == "ghp-fallback"


def test_is_configured_checks_aliases(monkeypatch):
    monkeypatch.setenv("OpenAI_API", "sk-alias-only")
    # Even before apply_aliases, is_configured should detect it via the alias chain.
    assert is_configured("OPENAI_API_KEY")


def test_registry_has_required_entries():
    """Smoke-check that key integrations are registered."""
    required = {
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_EMAIL",
        "DEEPSEEK_API_KEY",
        "RAILWAY_TOKEN",
        "N8N_API_KEY",
        "N8N_BASE_URL",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "V0_API_KEY",
        "GITHUB_PAT",
        "CLOUDINARY_API_KEY",
        "CLOUDINARY_API_SECRET",
        "CLOUDINARY_CLOUD_NAME",
        "DATABASE_URL",
        "OBSIDIAN_VAULT_URL",
    }
    assert required.issubset(set(ENV_REGISTRY.keys()))


def test_registry_secret_classification():
    """Non-secret vars (URLs, usernames, account names) should be flagged."""
    for name in ("N8N_BASE_URL", "OBSIDIAN_VAULT_URL", "CLOUDINARY_CLOUD_NAME",
                 "ANTHROPIC_EMAIL", "SMTP_USER"):
        assert ENV_REGISTRY[name].secret is False, (
            f"{name} should be marked secret=False"
        )
    # Secrets should be flagged.
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_PAT",
                 "DATABASE_URL", "RAILWAY_TOKEN"):
        assert ENV_REGISTRY[name].secret is True, (
            f"{name} should be marked secret=True"
        )
