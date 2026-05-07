"""Unit tests for tool_cascade — racing tool-capable models with structured chunks."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List
from unittest.mock import MagicMock

import pytest

from openjarvis.engine._stubs import StreamChunk
from openjarvis.server.tool_cascade import (
    ToolTierSpec,
    _is_usable,
    _race_within_tier,
    cascade_tools,
    load_tool_tiers,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


async def _yield_after(delay: float, *chunks: StreamChunk) -> AsyncIterator[StreamChunk]:
    """Async generator that yields each chunk after a short delay."""
    for c in chunks:
        await asyncio.sleep(delay)
        yield c


class _FakeEngine:
    """Engine stub whose stream_full() dispatches per model id."""

    def __init__(self, plans: dict[str, list[StreamChunk]], delays: dict[str, float] | None = None):
        self.plans = plans
        self.delays = delays or {}
        self.calls: List[str] = []

    def stream_full(
        self,
        messages: Any,
        *,
        model: str,
        tools: List[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunk]:
        self.calls.append(model)
        chunks = self.plans.get(model, [])
        delay = self.delays.get(model, 0.0)
        return _yield_after(delay, *chunks)


# ---------------------------------------------------------------------------
# _is_usable
# ---------------------------------------------------------------------------


def test_is_usable_text_chunk():
    assert _is_usable(StreamChunk(content="hello"))


def test_is_usable_tool_call_chunk():
    assert _is_usable(StreamChunk(tool_calls=[{"id": "x", "function": {"name": "f"}}]))


def test_is_usable_finish_chunk():
    assert _is_usable(StreamChunk(finish_reason="stop"))


def test_is_usable_skips_empty_whitespace():
    assert not _is_usable(StreamChunk(content="   \n"))
    assert not _is_usable(StreamChunk(content=None))
    assert not _is_usable(StreamChunk())


# ---------------------------------------------------------------------------
# _race_within_tier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_race_winner_cancels_losers(monkeypatch):
    """First provider to yield a usable chunk wins; the slow loser is cancelled."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    engine = _FakeEngine(
        plans={
            "claude-sonnet-4-6": [StreamChunk(content="fast"), StreamChunk(finish_reason="stop")],
            "deepseek-chat": [StreamChunk(content="slow")],
        },
        delays={
            "claude-sonnet-4-6": 0.01,
            "deepseek-chat": 1.0,  # would be slow if it ran to completion
        },
    )

    tier = ToolTierSpec(name="TT1", providers=("claude-sonnet-4-6", "deepseek-chat"), deadline_s=2.0)
    stream = await _race_within_tier(tier, engine, [], [], temperature=0.0, max_tokens=128)
    assert stream is not None

    out: List[StreamChunk] = []
    async for chunk in stream:
        out.append(chunk)

    # Claude must have been called; DeepSeek may have been started but
    # cancelled before yielding anything usable.
    assert "claude-sonnet-4-6" in engine.calls
    # The first content delta should be from Claude.
    contents = [c.content for c in out if c.content]
    assert contents and contents[0] == "fast"


@pytest.mark.asyncio
async def test_race_filters_unreachable_providers(monkeypatch):
    """Providers without their API key in env are filtered before racing."""
    # Only DeepSeek's key is set — Claude must be skipped.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")

    engine = _FakeEngine(plans={
        "deepseek-chat": [StreamChunk(content="ds")],
    })
    tier = ToolTierSpec(name="TT1", providers=("claude-sonnet-4-6", "deepseek-chat"), deadline_s=2.0)

    stream = await _race_within_tier(tier, engine, [], [], temperature=0.0, max_tokens=128)
    assert stream is not None
    async for _ in stream:
        pass
    assert engine.calls == ["deepseek-chat"]


@pytest.mark.asyncio
async def test_race_returns_none_when_no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    engine = _FakeEngine(plans={})
    tier = ToolTierSpec(name="TT1", providers=("claude-sonnet-4-6", "deepseek-chat"), deadline_s=2.0)
    stream = await _race_within_tier(tier, engine, [], [], temperature=0.0, max_tokens=128)
    assert stream is None


# ---------------------------------------------------------------------------
# cascade_tools — full pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cascade_falls_through_on_t1_failure(monkeypatch):
    """If every TT1 provider errors, TT2 takes over."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    # Force tiny tiers so the test is quick.
    monkeypatch.setenv("TIER1_TOOL_PROVIDERS", "claude-sonnet-4-6")
    monkeypatch.setenv("TIER2_TOOL_PROVIDERS", "gpt-4o")
    monkeypatch.setenv("TIER3_TOOL_PROVIDERS", "")
    monkeypatch.setenv("TIER1_TOOL_DEADLINE_S", "0.5")
    monkeypatch.setenv("TIER2_TOOL_DEADLINE_S", "2.0")

    async def claude_raises(*args, **kwargs):
        raise RuntimeError("anthropic 429")
        yield  # unreachable, makes this an async-gen

    class _ClaudeFails:
        def stream_full(self, *args, **kwargs):
            return claude_raises()

    class _DispatchEngine:
        def __init__(self):
            self.calls = []

        def stream_full(self, messages, *, model, tools=None, temperature=0.7, max_tokens=1024):
            self.calls.append(model)
            if model == "claude-sonnet-4-6":
                return claude_raises()
            return _yield_after(0.01, StreamChunk(content="from-gpt"), StreamChunk(finish_reason="stop"))

    engine = _DispatchEngine()
    out: List[StreamChunk] = []
    async for chunk in cascade_tools(engine, [], [], temperature=0.0, max_tokens=64):
        out.append(chunk)

    contents = [c.content for c in out if c.content]
    assert any(c == "from-gpt" for c in contents)
    assert "claude-sonnet-4-6" in engine.calls
    assert "gpt-4o" in engine.calls


@pytest.mark.asyncio
async def test_cascade_yields_friendly_message_when_all_tiers_empty(monkeypatch):
    """No keys anywhere → cascade yields a single instructional StreamChunk."""
    for k in ("ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY",
              "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("TIER3_TOOL_PROVIDERS", "")  # avoid the gpt-5 fallback

    engine = MagicMock()
    out = []
    async for chunk in cascade_tools(engine, [], [], temperature=0.0, max_tokens=64):
        out.append(chunk)
    # We expect exactly one instructional chunk telling the user to set a key.
    assert len(out) == 1
    assert out[0].finish_reason == "stop"
    assert "tool-capable provider" in (out[0].content or "")
