"""Engine test fixtures — ensure cloud API key isolation across tests."""

from __future__ import annotations

import pytest

CLOUD_KEY_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MINIMAX_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_CODEX_API_KEY",
    "OPENROUTER_API_KEY",
)


@pytest.fixture(autouse=True)
def isolate_cloud_key_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear all cloud provider API key env vars before each engine test."""
    for var in CLOUD_KEY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
