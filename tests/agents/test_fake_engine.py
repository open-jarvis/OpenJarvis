"""Tests for FakeEngine."""

from __future__ import annotations

import pytest

from tests.agents.fake_engine import FakeEngine


def test_fake_engine_returns_responses_in_order():
    engine = FakeEngine([
        {"content": "first"},
        {"content": "second"},
    ])
    r1 = engine.generate([], model="m")
    r2 = engine.generate([], model="m")
    assert r1["content"] == "first"
    assert r2["content"] == "second"
    assert engine.call_count == 2


def test_fake_engine_repeats_last_response():
    engine = FakeEngine([{"content": "only"}])
    engine.generate([], model="m")
    r = engine.generate([], model="m")
    assert r["content"] == "only"


def test_fake_engine_raises_on_request():
    engine = FakeEngine([{"raise": ValueError("boom")}])
    with pytest.raises(ValueError, match="boom"):
        engine.generate([], model="m")


def test_fake_engine_tool_calls():
    engine = FakeEngine([{
        "content": "",
        "tool_calls": [{"id": "1", "function": {"name": "think", "arguments": "{}"}}],
    }])
    r = engine.generate([], model="m")
    assert r["finish_reason"] == "tool_calls"
    assert len(r["tool_calls"]) == 1
