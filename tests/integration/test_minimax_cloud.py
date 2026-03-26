"""Integration test for MiniMax cloud provider.

Requires MINIMAX_API_KEY environment variable to be set.
Run with: pytest tests/integration/test_minimax_cloud.py -v
"""

from __future__ import annotations

import os

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import CloudEngine

_MINIMAX_KEY = os.environ.get("MINIMAX_API_KEY", "")
_skip_no_key = pytest.mark.skipif(
    not _MINIMAX_KEY,
    reason="MINIMAX_API_KEY not set",
)


@_skip_no_key
class TestMiniMaxCloudIntegration:
    """Live integration tests against MiniMax Cloud API."""

    @pytest.fixture()
    def engine(self, monkeypatch: pytest.MonkeyPatch) -> CloudEngine:
        monkeypatch.setenv("MINIMAX_API_KEY", _MINIMAX_KEY)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        if not EngineRegistry.contains("cloud"):
            EngineRegistry.register_value("cloud", CloudEngine)
        return CloudEngine()

    def test_m27_highspeed_basic_chat(self, engine: CloudEngine) -> None:
        """Send a simple message via M2.7-highspeed and verify non-empty response."""
        result = engine.generate(
            [Message(role=Role.USER, content="Reply with exactly: hello world")],
            model="MiniMax-M2.7-highspeed",
            temperature=0.01,
            max_tokens=32,
        )
        assert result["content"], "Expected non-empty content"
        assert result["usage"]["prompt_tokens"] > 0
        assert result["usage"]["completion_tokens"] > 0
        assert result["finish_reason"] in ("stop", "length")

    def test_m27_highspeed_health(self, engine: CloudEngine) -> None:
        """Engine health should be True when MINIMAX_API_KEY is set."""
        assert engine.health() is True

    def test_m27_highspeed_list_models(self, engine: CloudEngine) -> None:
        """MiniMax models should appear in list_models."""
        models = engine.list_models()
        assert "MiniMax-M2.7" in models
        assert "MiniMax-M2.7-highspeed" in models
        assert "MiniMax-M2.5" in models
        assert "MiniMax-M2.5-highspeed" in models
