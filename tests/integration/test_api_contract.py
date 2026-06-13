"""API Contract Tests — validate frontend payloads against backend Pydantic models.

Ensures the JSON that InputArea.tsx sends to /v1/chat/completions is
accepted by the FastAPI ChatCompletionRequest model without coercion
errors or silent data loss.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from openjarvis.server.models import (
    ChatCompletionRequest,
    ChatMessage,
)  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — mirror the exact payload shapes built by InputArea.tsx
# ---------------------------------------------------------------------------


def _minimal_payload() -> Dict[str, Any]:
    """Bare-minimum payload (model + messages only)."""
    return {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Hello"}],
    }


def _streaming_payload() -> Dict[str, Any]:
    """Exact shape sent by InputArea.tsx when streaming is enabled."""
    return {
        "model": "test-model",
        "messages": [
            {"role": "user", "content": "Hello"},
        ],
        "stream": True,
    }


def _full_payload_with_agent() -> Dict[str, Any]:
    """Full payload with all optional fields populated (agent_id active)."""
    return {
        "model": "test-model",
        "messages": [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "Hello"},
        ],
        "temperature": 0.5,
        "max_tokens": 2048,
        "stream": True,
        "agent_id": "bavaria_booking",
    }


def _frontend_message_shape() -> List[Dict[str, str]]:
    """Mirror of apiMessages = currentMessages.map(m => ({role, content}))."""
    return [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
    ]


def _payload_with_tools() -> Dict[str, Any]:
    """Payload including the tools array (OpenAI-compatible shape)."""
    return {
        "model": "test-model",
        "messages": [{"role": "user", "content": "Calc"}],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Add two numbers",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


class TestChatCompletionRequestContract:
    """Verify every frontend payload shape parses cleanly into the backend model."""

    def test_minimal_payload_accepted(self):
        """The bare-minimum POST body from the frontend must validate."""
        payload = _minimal_payload()
        req = ChatCompletionRequest.model_validate(payload)
        assert req.model == "test-model"
        assert len(req.messages) == 1
        assert req.messages[0].role == "user"
        assert req.messages[0].content == "Hello"
        # Defaults applied
        assert req.temperature == 0.7
        assert req.max_tokens == 1024
        assert req.stream is False
        assert req.tools is None
        assert req.agent_id is None

    def test_streaming_payload_accepted(self):
        """InputArea.tsx sets stream=True — backend must accept it."""
        payload = _streaming_payload()
        req = ChatCompletionRequest.model_validate(payload)
        assert req.stream is True

    def test_full_payload_with_agent(self):
        """Every optional field populated must round-trip cleanly."""
        payload = _full_payload_with_agent()
        req = ChatCompletionRequest.model_validate(payload)
        assert req.model == "test-model"
        assert len(req.messages) == 2
        assert req.messages[0].role == "system"
        assert req.messages[1].role == "user"
        assert req.temperature == 0.5
        assert req.max_tokens == 2048
        assert req.stream is True
        assert req.agent_id == "bavaria_booking"

    def test_frontend_message_shape(self):
        """apiMessages only sends {role, content} — backend ChatMessage has more fields."""
        messages = _frontend_message_shape()
        payload = {
            "model": "test-model",
            "messages": messages,
        }
        req = ChatCompletionRequest.model_validate(payload)
        assert len(req.messages) == 2
        # Extra ChatMessage fields (name, tool_calls, tool_call_id) default to None
        assert req.messages[0].name is None
        assert req.messages[0].tool_calls is None
        assert req.messages[0].tool_call_id is None

    def test_tools_payload(self):
        """tools array must be accepted when present."""
        payload = _payload_with_tools()
        req = ChatCompletionRequest.model_validate(payload)
        assert req.tools is not None
        assert len(req.tools) == 1
        assert req.tools[0]["type"] == "function"

    def test_agent_id_null_accepted(self):
        """When no domain agent is selected frontend sends null/undefined."""
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "agent_id": None,
        }
        req = ChatCompletionRequest.model_validate(payload)
        assert req.agent_id is None

    def test_missing_optional_fields_use_defaults(self):
        """Omitted temperature, max_tokens, stream, tools, agent_id must default."""
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
        }
        req = ChatCompletionRequest.model_validate(payload)
        assert req.temperature == 0.7
        assert req.max_tokens == 1024
        assert req.stream is False
        assert req.tools is None
        assert req.agent_id is None

    def test_empty_messages_rejected(self):
        """messages is required — empty list should still parse (backend handles it)."""
        payload = {
            "model": "test-model",
            "messages": [],
        }
        req = ChatCompletionRequest.model_validate(payload)
        assert req.messages == []

    def test_extra_fields_ignored(self):
        """Frontend may send extra fields (e.g. client-side IDs) — they should be ignored."""
        payload = {
            "model": "test-model",
            "messages": [
                {
                    "role": "user",
                    "content": "Hello",
                    "timestamp": 1234567890,  # frontend-only field
                }
            ],
            "extra_frontend_field": "should_be_ignored",
        }
        req = ChatCompletionRequest.model_validate(payload)
        assert req.messages[0].content == "Hello"
        # Pydantic v2 ignores extra by default unless configured otherwise
        assert not hasattr(req, "extra_frontend_field")

    def test_json_roundtrip(self):
        """Payload must survive JSON encode -> decode without data loss."""
        original = _full_payload_with_agent()
        json_str = json.dumps(original)
        decoded = json.loads(json_str)
        req = ChatCompletionRequest.model_validate(decoded)
        assert req.model == original["model"]
        assert req.temperature == original["temperature"]
        assert req.max_tokens == original["max_tokens"]
        assert req.stream == original["stream"]
        assert req.agent_id == original["agent_id"]

    def test_boolean_stream_not_coerced_to_string(self):
        """stream: true must remain a boolean, not become string 'true'."""
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "stream": True,
        }
        req = ChatCompletionRequest.model_validate(payload)
        assert req.stream is True
        assert isinstance(req.stream, bool)

    def test_agent_id_string_not_list(self):
        """agent_id must be a single string, not wrapped in a list."""
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "agent_id": "bavaria_booking",
        }
        req = ChatCompletionRequest.model_validate(payload)
        assert req.agent_id == "bavaria_booking"

    def test_temperature_numeric_not_string(self):
        """temperature must be a float, not a string like '0.5'."""
        payload = {
            "model": "test-model",
            "messages": [{"role": "user", "content": "Hello"}],
            "temperature": 0.5,
        }
        req = ChatCompletionRequest.model_validate(payload)
        assert req.temperature == 0.5
        assert isinstance(req.temperature, float)
