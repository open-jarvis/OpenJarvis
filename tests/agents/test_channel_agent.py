"""Tests for ChannelAgent and classify_query."""

from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import MagicMock

from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.channel_agent import ChannelAgent, classify_query
from openjarvis.channels._stubs import (
    BaseChannel,
    ChannelHandler,
    ChannelMessage,
    ChannelStatus,
)

# ---------------------------------------------------------------------------
# FakeChannel test helper
# ---------------------------------------------------------------------------


class FakeChannel(BaseChannel):
    """Minimal in-process channel for unit tests."""

    channel_id = "fake"

    def __init__(self) -> None:
        self._handlers: List[ChannelHandler] = []
        self._sent: List[Dict[str, Any]] = []

    # BaseChannel abstract methods
    def connect(self) -> None:  # noqa: D102
        pass

    def disconnect(self) -> None:  # noqa: D102
        pass

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        self._sent.append(
            {
                "channel": channel,
                "content": content,
                "conversation_id": conversation_id,
            }
        )
        return True

    def status(self) -> ChannelStatus:  # noqa: D102
        return ChannelStatus.CONNECTED

    def list_channels(self) -> List[str]:  # noqa: D102
        return ["fake"]

    def on_message(self, handler: ChannelHandler) -> None:  # noqa: D102
        self._handlers.append(handler)

    # Helper for tests
    def simulate_message(self, msg: ChannelMessage) -> None:
        """Invoke all registered handlers with *msg*."""
        for h in self._handlers:
            h(msg)


# ---------------------------------------------------------------------------
# classify_query — 11 tests
# ---------------------------------------------------------------------------


class TestClassifyQuery:
    def test_when_prefix_is_quick(self):
        assert classify_query("When is my next meeting?") == "quick"

    def test_where_prefix_is_quick(self):
        assert classify_query("Where is the design doc?") == "quick"

    def test_find_prefix_is_quick(self):
        assert classify_query("Find the budget spreadsheet") == "quick"

    def test_who_prefix_is_quick(self):
        assert classify_query("Who sent the last email?") == "quick"

    def test_summarize_is_deep(self):
        assert classify_query("Summarize all discussions about pricing") == "deep"

    def test_research_context_is_deep(self):
        assert classify_query("Research the context behind the K8s decision") == "deep"

    def test_context_keyword_is_deep(self):
        assert classify_query("What was the context around the migration?") == "deep"

    def test_time_range_is_deep(self):
        assert classify_query("What happened last month with the project?") == "deep"

    def test_long_query_is_deep(self):
        long_q = (
            "Can you help me understand what has been going on with the backend "
            "services over the past few weeks and whether there are any patterns "
            "that might indicate problems?"
        )
        assert len(long_q.split()) > 20
        assert classify_query(long_q) == "deep"

    def test_whats_prefix_is_quick(self):
        assert classify_query("What's Sarah's email?") == "quick"

    def test_compare_is_deep(self):
        assert (
            classify_query("Compare what Sarah and Mike said about the budget")
            == "deep"
        )


# ---------------------------------------------------------------------------
# ChannelAgent — 6 tests
# ---------------------------------------------------------------------------


def _make_agent(content: str = "Here is your answer.") -> MagicMock:
    agent = MagicMock()
    agent.run.return_value = AgentResult(content=content)
    return agent


def _make_msg(
    content: str = "When is my next meeting?",
    channel: str = "fake",
    sender: str = "user1",
    session_id: str = "sess-001",
) -> ChannelMessage:
    return ChannelMessage(
        channel=channel,
        sender=sender,
        content=content,
        session_id=session_id,
    )


class TestChannelAgent:
    def test_registers_handler_on_channel(self):
        """ChannelAgent must register exactly one handler via on_message."""
        channel = FakeChannel()
        agent = _make_agent()
        ca = ChannelAgent(channel, agent)
        assert len(channel._handlers) == 1
        ca.shutdown()

    def test_quick_query_sends_inline_response(self):
        """Quick query with short response → inline, no escalation link."""
        channel = FakeChannel()
        agent = _make_agent("Here is your answer.")
        ca = ChannelAgent(channel, agent)

        msg = _make_msg("When is my next meeting?")
        channel.simulate_message(msg)
        ca.shutdown()  # waits for background task to complete

        assert len(channel._sent) == 1
        sent_content = channel._sent[0]["content"]
        assert "openjarvis://research/" not in sent_content
        assert "Here is your answer." in sent_content

    def test_deep_query_sends_preview_and_escalation_link(self):
        """Deep query → preview truncated to 300 chars + openjarvis:// link."""
        channel = FakeChannel()
        agent = _make_agent("Deep analysis result.")
        ca = ChannelAgent(channel, agent)

        msg = _make_msg("Summarize all discussions about the pricing strategy")
        channel.simulate_message(msg)
        ca.shutdown()

        assert len(channel._sent) == 1
        sent_content = channel._sent[0]["content"]
        assert "openjarvis://research/" in sent_content
        assert "Full report ready" in sent_content

    def test_agent_error_sends_friendly_message(self):
        """If agent.run() raises, a friendly error message is sent."""
        channel = FakeChannel()
        agent = MagicMock()
        agent.run.side_effect = RuntimeError("model unavailable")
        ca = ChannelAgent(channel, agent)

        msg = _make_msg("Find the latest report")
        channel.simulate_message(msg)
        ca.shutdown()

        assert len(channel._sent) == 1
        sent_content = channel._sent[0]["content"]
        assert "error" in sent_content.lower()

    def test_quick_query_calls_agent_run(self):
        """agent.run() is called exactly once with the message content."""
        channel = FakeChannel()
        agent = _make_agent()
        ca = ChannelAgent(channel, agent)

        msg = _make_msg("Who sent the last email?")
        channel.simulate_message(msg)
        ca.shutdown()

        agent.run.assert_called_once_with(msg.content)

    def test_handler_does_not_block(self):
        """_handle_message must return in <0.5 s even if agent takes 2 s."""
        import threading

        channel = FakeChannel()

        # Agent that sleeps 2 s
        slow_agent = MagicMock()
        barrier = threading.Event()

        def _slow_run(text: str) -> AgentResult:
            barrier.wait(timeout=5)
            return AgentResult(content="done")

        slow_agent.run.side_effect = _slow_run
        ca = ChannelAgent(channel, slow_agent)

        msg = _make_msg("When is my next meeting?")
        t0 = time.monotonic()
        channel.simulate_message(msg)
        elapsed = time.monotonic() - t0

        assert elapsed < 0.5, f"handler blocked for {elapsed:.2f}s"

        # Unblock the background thread so shutdown doesn't hang forever
        barrier.set()
        ca.shutdown()

    def test_long_response_triggers_escalation(self):
        """Even a quick query gets escalated when the response exceeds 500 chars."""
        channel = FakeChannel()
        long_response = "x" * 600
        agent = _make_agent(long_response)
        ca = ChannelAgent(channel, agent)

        msg = _make_msg("When is my next meeting?")
        channel.simulate_message(msg)
        ca.shutdown()

        assert len(channel._sent) == 1
        sent_content = channel._sent[0]["content"]
        assert "openjarvis://research/" in sent_content
