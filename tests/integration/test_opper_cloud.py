"""Integration test for the Opper cloud provider.

Requires the OPPER_API_KEY environment variable to be set.
Run with: pytest tests/integration/test_opper_cloud.py -v
"""

from __future__ import annotations

import os

import pytest

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine.cloud import _OPPER_POPULAR, CloudEngine

_OPPER_KEY = os.environ.get("OPPER_API_KEY", "")
_skip_no_key = pytest.mark.skipif(
    not _OPPER_KEY,
    reason="OPPER_API_KEY not set",
)

_DEFAULT_MODEL = "opper/claude-sonnet-4-6"


@_skip_no_key
class TestOpperIntegration:
    """Live integration tests against the Opper gateway."""

    @pytest.fixture()
    def engine(self, monkeypatch: pytest.MonkeyPatch) -> CloudEngine:
        monkeypatch.setenv("OPPER_API_KEY", _OPPER_KEY)
        for name in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENROUTER_API_KEY",
            "MINIMAX_API_KEY",
            "DEEPSEEK_API_KEY",
            "ATLASCLOUD_API_KEY",
        ):
            monkeypatch.delenv(name, raising=False)
        if not EngineRegistry.contains("cloud"):
            EngineRegistry.register_value("cloud", CloudEngine)
        return CloudEngine()

    def test_basic_chat(self, engine: CloudEngine) -> None:
        """Send a simple message and verify a non-empty, costed response."""
        result = engine.generate(
            [Message(role=Role.USER, content="Reply with exactly: hello world")],
            model=_DEFAULT_MODEL,
            temperature=0.01,
            max_tokens=32,
        )
        assert result["content"], "Expected non-empty content"
        assert result["usage"]["prompt_tokens"] > 0
        assert result["usage"]["completion_tokens"] > 0
        assert result["finish_reason"] in ("stop", "length")
        assert result["cost_usd"] > 0.0

    @pytest.mark.asyncio
    async def test_streaming(self, engine: CloudEngine) -> None:
        tokens = [
            t
            async for t in engine.stream(
                [Message(role=Role.USER, content="Count: 1 2 3")],
                model=_DEFAULT_MODEL,
                temperature=0.01,
                max_tokens=32,
            )
        ]
        assert "".join(tokens).strip()

    def test_tool_calling(self, engine: CloudEngine) -> None:
        """The gateway forwards OpenAI tool calls unchanged."""
        result = engine.generate(
            [Message(role=Role.USER, content="What is the weather in Paris?")],
            model=_DEFAULT_MODEL,
            temperature=0.01,
            max_tokens=128,
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Look up the current weather for a city.",
                        "parameters": {
                            "type": "object",
                            "properties": {"city": {"type": "string"}},
                            "required": ["city"],
                        },
                    },
                }
            ],
        )
        assert result["tool_calls"], "Expected the model to call get_weather"
        assert result["tool_calls"][0]["function"]["name"] == "get_weather"

    def test_health_and_list_models(self, engine: CloudEngine) -> None:
        assert engine.health() is True
        models = engine.list_models()
        for model in _OPPER_POPULAR:
            assert model in models
