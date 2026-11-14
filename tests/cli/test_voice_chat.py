"""Tests for the spoken-summary helper in the voice chat flow."""

from __future__ import annotations


def test_make_spoken_reply_condenses_via_engine():
    from openjarvis.cli._voice_chat import make_spoken_reply

    class FakeEngine:
        def __init__(self) -> None:
            self.messages = None

        def generate(self, messages, model="", **kwargs):
            self.messages = messages
            return {"content": "  Short spoken answer.  "}

    engine = FakeEngine()
    out = make_spoken_reply("A very long chapter of text.", engine, "m")

    assert out == "Short spoken answer."
    assert engine.messages is not None
    assert "Condense" in engine.messages[0].content
    assert engine.messages[1].content == "A very long chapter of text."


def test_make_spoken_reply_falls_back_to_full_text():
    from openjarvis.cli._voice_chat import make_spoken_reply

    class BadEngine:
        def generate(self, messages, model="", **kwargs):
            raise RuntimeError("boom")

    assert make_spoken_reply("full text", BadEngine(), "m") == "full text"
