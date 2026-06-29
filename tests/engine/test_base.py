"""Tests for openjarvis.engine._base utility helpers."""

from __future__ import annotations

from openjarvis.core.types import Message, Role
from openjarvis.engine._base import estimate_prompt_tokens


class TestEstimatePromptTokens:
    def test_counts_basic_messages(self):
        # 25 content chars // 4  +  2 messages * 4 overhead
        msgs = [
            Message(role=Role.USER, content="hello there"),
            Message(role=Role.ASSISTANT, content="general kenobi"),
        ]
        assert estimate_prompt_tokens(msgs) == 14

    def test_handles_none_content(self):
        # A tool-call assistant turn legitimately carries content=None per the
        # OpenAI chat schema; Qwen3 on Ollama produces exactly this shape. The
        # next turn's prompt estimate must not crash. Regression for the
        # "TypeError: object of type 'NoneType' has no len()" in issue #276.
        msgs = [
            Message(role=Role.USER, content="What is 17 * 23?"),  # 16 chars
            Message(role=Role.ASSISTANT, content=None),
        ]
        # 16 // 4  +  2 messages * 4 overhead = 4 + 8
        assert estimate_prompt_tokens(msgs) == 12

    def test_none_message_adds_only_overhead(self):
        # A None-content message must contribute its per-message overhead and
        # zero content chars. Pins the fix so a future `len(m.content)`
        # regression (which would re-raise the #276 TypeError) is caught.
        base = [Message(role=Role.USER, content="What is 17 * 23?")]
        with_none = base + [Message(role=Role.ASSISTANT, content=None)]
        assert estimate_prompt_tokens(with_none) - estimate_prompt_tokens(base) == 4
