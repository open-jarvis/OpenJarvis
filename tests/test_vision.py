"""Tests for vision input support: ``Message.images`` -> Ollama payload.

These cover the data-flow contract that makes vision work end to end:
a ``Message`` can carry base64 images, the engine serializer forwards them
to Ollama's ``/api/chat`` ``images`` field, and text-only messages are
completely unaffected. The security guardrail must preserve images when it
rewrites a flagged message.
"""

from __future__ import annotations

from types import SimpleNamespace

import openjarvis.engine.ollama as ollama_mod
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import messages_to_dicts


def test_message_defaults_to_no_images() -> None:
    assert Message(role=Role.USER, content="hi").images is None


def test_messages_to_dicts_omits_images_for_text() -> None:
    dicts = messages_to_dicts([Message(role=Role.USER, content="hi")])
    assert "images" not in dicts[0]


def test_messages_to_dicts_forwards_images() -> None:
    b64 = "aGVsbG8="  # "hello"
    dicts = messages_to_dicts(
        [Message(role=Role.USER, content="what is this?", images=[b64])]
    )
    assert dicts[0]["role"] == "user"
    assert dicts[0]["content"] == "what is this?"
    assert dicts[0]["images"] == [b64]


def test_messages_to_dicts_empty_images_treated_as_text() -> None:
    dicts = messages_to_dicts([Message(role=Role.USER, content="hi", images=[])])
    assert "images" not in dicts[0]


def test_default_num_ctx_default_and_override(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_NUM_CTX", raising=False)
    assert ollama_mod._default_num_ctx() == 16384

    monkeypatch.setenv("JARVIS_NUM_CTX", "8000")
    assert ollama_mod._default_num_ctx() == 8000

    # A non-integer override must fall back to the safe default, not crash.
    monkeypatch.setenv("JARVIS_NUM_CTX", "not-an-int")
    assert ollama_mod._default_num_ctx() == 16384


def test_guardrails_preserves_images_when_sanitizing() -> None:
    """A flagged message gets rewritten; its image must survive the rewrite."""
    from openjarvis.security.guardrails import GuardrailsEngine

    class _RecordingEngine:
        """Captures the messages the guardrail forwards to the real engine."""

        def __init__(self) -> None:
            self.received: list[Message] = []

        def generate(self, messages, *, model, **kwargs):
            self.received = list(messages)
            return {"content": "ok"}

    class _AlwaysFlag:
        """A scanner that flags everything, forcing the sanitize rewrite path."""

        def scan(self, text: str):
            finding = SimpleNamespace(
                pattern_name="test",
                threat_level=SimpleNamespace(value="low"),
                description="always flags",
            )
            return SimpleNamespace(findings=[finding])

        def redact(self, text: str) -> str:
            return text

    engine = _RecordingEngine()
    guarded = GuardrailsEngine(
        engine,
        scanners=[_AlwaysFlag()],
        scan_input=True,
        scan_output=False,
    )
    msg = Message(role=Role.USER, content="suspicious", images=["aGVsbG8="])

    guarded.generate([msg], model="x")

    assert engine.received[0].images == ["aGVsbG8="]
