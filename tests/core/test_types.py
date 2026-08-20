"""Tests for core data types."""

from __future__ import annotations

import time

from openjarvis.core.types import (
    Conversation,
    Message,
    ModelSpec,
    Quantization,
    Role,
    TelemetryRecord,
    ToolCall,
    ToolResult,
)


class TestRole:
    def test_values(self) -> None:
        assert Role.SYSTEM == "system"
        assert Role.USER == "user"
        assert Role.ASSISTANT == "assistant"
        assert Role.TOOL == "tool"


class TestQuantization:
    def test_none_and_variants(self) -> None:
        assert Quantization.NONE == "none"
        assert Quantization.GGUF_Q4 == "gguf_q4"


class TestMessage:
    def test_basic_message(self) -> None:
        msg = Message(role=Role.USER, content="hello")
        assert msg.role == Role.USER
        assert msg.content == "hello"
        assert msg.text == "hello"
        assert msg.tool_calls is None
        assert msg.metadata == {}

    def test_none_content_text_helper(self) -> None:
        msg = Message(role=Role.ASSISTANT, content=None)
        assert msg.content is None
        assert msg.text == ""

    def test_tool_calls(self) -> None:
        tc = ToolCall(id="1", name="calc", arguments='{"x": 1}')
        msg = Message(role=Role.ASSISTANT, content="", tool_calls=[tc])
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "calc"


class TestConversation:
    def test_add_and_window(self) -> None:
        conv = Conversation()
        conv.add(Message(role=Role.USER, content="a"))
        conv.add(Message(role=Role.ASSISTANT, content="b"))
        conv.add(Message(role=Role.USER, content="c"))
        assert len(conv.messages) == 3
        assert [m.content for m in conv.window(2)] == ["b", "c"]

    def test_window_zero_returns_empty(self) -> None:
        conv = Conversation()
        conv.add(Message(role=Role.USER, content="a"))
        conv.add(Message(role=Role.ASSISTANT, content="b"))
        assert conv.window(0) == []

    def test_max_messages(self) -> None:
        conv = Conversation(max_messages=2)
        for i in range(5):
            conv.add(Message(role=Role.USER, content=str(i)))
        assert len(conv.messages) == 2
        assert conv.messages[0].content == "3"
        assert conv.messages[1].content == "4"


class TestModelSpec:
    def test_defaults(self) -> None:
        spec = ModelSpec(
            model_id="m1",
            name="Model One",
            parameter_count_b=7.0,
            context_length=8192,
        )
        assert spec.quantization == Quantization.NONE
        assert spec.min_vram_gb == 0.0
        assert spec.active_parameter_count_b is None
        assert spec.metadata == {}


class TestToolResult:
    def test_success_defaults(self) -> None:
        tr = ToolResult(tool_name="calc", content="42")
        assert tr.success is True
        assert tr.cost_usd == 0.0


class TestTelemetryRecord:
    def test_fields(self) -> None:
        rec = TelemetryRecord(
            timestamp=time.time(),
            model_id="m1",
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30,
        )
        assert rec.total_tokens == 30
        assert rec.energy_joules == 0.0
