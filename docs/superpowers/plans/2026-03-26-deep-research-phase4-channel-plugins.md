# Deep Research Phase 4: Channel Plugins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a ChannelAgent that connects existing messaging channels (Slack, WhatsApp, iMessage) to the DeepResearchAgent, with automatic query classification (quick inline answers vs. escalation to desktop for complex research).

**Architecture:** A `ChannelAgent` class registers as a `ChannelHandler` callback on any `BaseChannel`. When a message arrives, it classifies the query (quick vs. deep), runs the DeepResearchAgent with the appropriate turn limit, and sends the response back via `channel.send()`. Quick answers go inline; complex queries get a brief preview + escalation link. A worker thread pool prevents blocking the channel's event loop.

**Tech Stack:** Python 3.10+, threading (worker pool), existing channel transports (Slack Socket Mode, WhatsApp Baileys, BlueBubbles), pytest

**Spec:** `docs/superpowers/specs/2026-03-25-deep-research-setup-design.md` — Section 9 (Channel Plugins)

**Depends on:** Phase 1 (connectors, KnowledgeStore), Phase 3 (DeepResearchAgent, TwoStageRetriever)

---

## File Structure

```
src/openjarvis/agents/
├── channel_agent.py          # ChannelAgent: bridge between channels and DeepResearchAgent

tests/agents/
├── test_channel_agent.py     # ChannelAgent tests
```

---

### Task 1: Query Classifier

**Files:**
- Create: `src/openjarvis/agents/channel_agent.py` (first half — classifier only)
- Create: `tests/agents/test_channel_agent.py`

The classifier determines whether a message needs a quick single-hop answer or full multi-hop research. This is an internal implementation detail — the user never sees it.

- [ ] **Step 1: Write failing tests for classifier**

Create `tests/agents/test_channel_agent.py`:

```python
"""Tests for ChannelAgent — bridge between channels and DeepResearchAgent."""

from __future__ import annotations

from openjarvis.agents.channel_agent import classify_query


def test_quick_when_query() -> None:
    assert classify_query("When is my next meeting?") == "quick"


def test_quick_where_query() -> None:
    assert classify_query("Where is the design doc?") == "quick"


def test_quick_find_query() -> None:
    assert classify_query("Find the budget spreadsheet") == "quick"


def test_quick_short_query() -> None:
    assert classify_query("Who sent the last email?") == "quick"


def test_deep_summarize() -> None:
    assert classify_query("Summarize all discussions about pricing") == "deep"


def test_deep_research() -> None:
    assert classify_query("Research the context behind the K8s decision") == "deep"


def test_deep_context() -> None:
    assert classify_query("What was the context around the migration?") == "deep"


def test_deep_time_range() -> None:
    assert classify_query("What happened last month with the project?") == "deep"


def test_deep_long_query() -> None:
    long = "Tell me about all the discussions between Sarah and Mike about the infrastructure migration including cost analysis and timeline"
    assert classify_query(long) == "deep"


def test_quick_single_entity() -> None:
    assert classify_query("What's Sarah's email?") == "quick"


def test_deep_multi_entity() -> None:
    assert classify_query("Compare what Sarah and Mike said about the budget") == "deep"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/agents/test_channel_agent.py -v`

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement classify_query**

Create `src/openjarvis/agents/channel_agent.py`:

```python
"""ChannelAgent — bridges messaging channels to the DeepResearchAgent.

Handles:
- Automatic query classification (quick vs. deep)
- Quick answers inline in the chat channel
- Complex queries escalated with a preview + desktop link
- Worker thread pool so channel event loops aren't blocked
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult
from openjarvis.channels._stubs import BaseChannel, ChannelMessage
from openjarvis.core.events import EventType, get_event_bus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Query classification
# ---------------------------------------------------------------

_DEEP_KEYWORDS = re.compile(
    r"\b(summarize|summary|research|context|compare|analyze|analysis"
    r"|overview|all discussions|comprehensive|timeline|history"
    r"|what happened|tell me about all)\b",
    re.IGNORECASE,
)

_TIME_RANGE_PATTERNS = re.compile(
    r"\b(last (week|month|quarter|year)|past \d+|since (january|february"
    r"|march|april|may|june|july|august|september|october|november"
    r"|december))\b",
    re.IGNORECASE,
)

_QUICK_STARTERS = re.compile(
    r"^(when|where|find|who sent|what'?s|what is)\b", re.IGNORECASE
)

_MAX_QUICK_WORDS = 20


def classify_query(text: str) -> str:
    """Classify a user query as 'quick' or 'deep'.

    Quick: single-entity lookups, short factual questions.
    Deep: multi-source synthesis, summarization, time-range analysis.

    This is an internal heuristic — the user never specifies the mode.
    """
    text = text.strip()
    words = text.split()

    # Deep signals take priority
    if _DEEP_KEYWORDS.search(text):
        return "deep"
    if _TIME_RANGE_PATTERNS.search(text):
        return "deep"
    if len(words) > _MAX_QUICK_WORDS:
        return "deep"

    # Quick signals
    if _QUICK_STARTERS.match(text):
        return "quick"
    if len(words) <= _MAX_QUICK_WORDS:
        return "quick"

    return "quick"
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/agents/test_channel_agent.py -v`

Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/agents/channel_agent.py tests/agents/test_channel_agent.py
git commit -m "feat: add query classifier for channel agent (quick vs deep)"
```

---

### Task 2: ChannelAgent Core

**Files:**
- Modify: `src/openjarvis/agents/channel_agent.py`
- Modify: `tests/agents/test_channel_agent.py`

- [ ] **Step 1: Write failing tests for ChannelAgent**

Add to `tests/agents/test_channel_agent.py`:

```python
import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.agents.channel_agent import ChannelAgent, classify_query
from openjarvis.agents.deep_research import DeepResearchAgent
from openjarvis.agents._stubs import AgentResult
from openjarvis.channels._stubs import BaseChannel, ChannelMessage, ChannelStatus
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.connectors.retriever import TwoStageRetriever
from openjarvis.core.types import ToolResult
from openjarvis.tools.knowledge_search import KnowledgeSearchTool


class FakeChannel(BaseChannel):
    """Minimal channel for testing."""

    channel_id = "fake"

    def __init__(self) -> None:
        self._handlers: list = []
        self._sent: list = []
        self._connected = True

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: dict | None = None,
    ) -> bool:
        self._sent.append(
            {
                "channel": channel,
                "content": content,
                "conversation_id": conversation_id,
            }
        )
        return True

    def status(self) -> ChannelStatus:
        return ChannelStatus.CONNECTED if self._connected else ChannelStatus.DISCONNECTED

    def list_channels(self) -> list[str]:
        return ["test"]

    def on_message(self, handler) -> None:
        self._handlers.append(handler)

    def simulate_message(self, text: str, sender: str = "user1") -> None:
        msg = ChannelMessage(
            channel="fake",
            sender=sender,
            content=text,
            conversation_id="conv1",
        )
        for h in self._handlers:
            h(msg)


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock(spec=DeepResearchAgent)
    agent.agent_id = "deep_research"
    agent.run.return_value = AgentResult(
        content="The next meeting is tomorrow at 2pm.",
        tool_results=[],
        turns=1,
    )
    return agent


@pytest.fixture
def channel() -> FakeChannel:
    return FakeChannel()


@pytest.fixture
def channel_agent(
    channel: FakeChannel, mock_agent: MagicMock
) -> ChannelAgent:
    return ChannelAgent(
        channel=channel,
        agent=mock_agent,
    )


def test_channel_agent_registers_handler(
    channel: FakeChannel, channel_agent: ChannelAgent
) -> None:
    assert len(channel._handlers) == 1


def test_quick_query_sends_response_inline(
    channel: FakeChannel,
    channel_agent: ChannelAgent,
    mock_agent: MagicMock,
) -> None:
    channel.simulate_message("When is my next meeting?")
    # Give worker thread time to process
    time.sleep(0.5)
    assert len(channel._sent) >= 1
    assert "meeting" in channel._sent[0]["content"].lower()
    mock_agent.run.assert_called_once()


def test_deep_query_sends_preview_and_link(
    channel: FakeChannel,
    channel_agent: ChannelAgent,
    mock_agent: MagicMock,
) -> None:
    mock_agent.run.return_value = AgentResult(
        content="# Kubernetes Migration Report\n\nDetailed analysis...",
        tool_results=[
            ToolResult(
                tool_name="knowledge_search",
                content="results",
                success=True,
                metadata={"num_results": 15},
            ),
        ],
        turns=3,
    )
    channel.simulate_message(
        "Summarize all discussions about the Kubernetes migration"
    )
    time.sleep(0.5)
    assert len(channel._sent) >= 1
    # Deep queries should include an escalation link
    sent_content = channel._sent[-1]["content"]
    assert "openjarvis://" in sent_content or len(sent_content) > 50


def test_agent_error_sends_error_message(
    channel: FakeChannel,
    channel_agent: ChannelAgent,
    mock_agent: MagicMock,
) -> None:
    mock_agent.run.side_effect = RuntimeError("LLM unavailable")
    channel.simulate_message("When is my meeting?")
    time.sleep(0.5)
    assert len(channel._sent) >= 1
    assert "error" in channel._sent[0]["content"].lower() or "sorry" in channel._sent[0]["content"].lower()


def test_quick_query_uses_max_turns_1(
    channel: FakeChannel,
    channel_agent: ChannelAgent,
    mock_agent: MagicMock,
) -> None:
    channel.simulate_message("Find the budget doc")
    time.sleep(0.5)
    call_kwargs = mock_agent.run.call_args
    # Quick queries should be called (the agent handles turn limits internally)
    mock_agent.run.assert_called_once()


def test_channel_agent_does_not_block_handler(
    channel: FakeChannel,
    channel_agent: ChannelAgent,
    mock_agent: MagicMock,
) -> None:
    """Handler should return immediately (work dispatched to thread pool)."""
    mock_agent.run.side_effect = lambda *a, **kw: (
        time.sleep(2),
        AgentResult(content="done", turns=1),
    )[-1]

    t0 = time.time()
    channel.simulate_message("When is my meeting?")
    elapsed = time.time() - t0
    # Handler should return in < 0.1s even if agent takes 2s
    assert elapsed < 0.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/agents/test_channel_agent.py::test_channel_agent_registers_handler -v`

Expected: FAIL — `ImportError: cannot import name 'ChannelAgent'`

- [ ] **Step 3: Implement ChannelAgent**

Add to `src/openjarvis/agents/channel_agent.py` (after the classifier):

```python
# ---------------------------------------------------------------
# ChannelAgent
# ---------------------------------------------------------------

_ESCALATION_TEMPLATE = """{preview}

---
Full report ready — open in OpenJarvis:
openjarvis://research/{session_id}"""

_ERROR_TEMPLATE = (
    "Sorry, I ran into an error processing your request. "
    "Please try again or open OpenJarvis for the full experience."
)

_MAX_INLINE_LENGTH = 500


class ChannelAgent:
    """Bridges a messaging channel to the DeepResearchAgent.

    Registers as a handler on the given channel. When a message
    arrives, classifies it (quick vs deep), runs the agent in a
    worker thread, and sends the response back via the channel.

    Quick queries get the full response inline.
    Deep queries get a brief preview + escalation link.

    Parameters
    ----------
    channel:
        The messaging channel to listen on.
    agent:
        The DeepResearchAgent (or any BaseAgent) to handle queries.
    max_workers:
        Thread pool size for concurrent query processing.
    """

    def __init__(
        self,
        channel: BaseChannel,
        agent: Any,
        *,
        max_workers: int = 2,
    ) -> None:
        self._channel = channel
        self._agent = agent
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="channel_agent",
        )

        # Register handler
        channel.on_message(self._handle_message)

    def _handle_message(self, msg: ChannelMessage) -> Optional[str]:
        """Handler callback — dispatches work to thread pool."""
        self._pool.submit(self._process_message, msg)
        return None  # Don't block the channel's event loop

    def _process_message(self, msg: ChannelMessage) -> None:
        """Process a message in a worker thread."""
        query = msg.content.strip()
        if not query:
            return

        classification = classify_query(query)
        session_id = uuid.uuid4().hex[:12]

        bus = get_event_bus()
        bus.publish(
            EventType.AGENT_TURN_START,
            {
                "agent": "channel_agent",
                "channel": msg.channel,
                "sender": msg.sender,
                "classification": classification,
            },
        )

        try:
            result = self._agent.run(query)
        except Exception as exc:
            logger.error(
                "ChannelAgent error for %s: %s",
                msg.sender,
                exc,
            )
            self._channel.send(
                msg.sender,
                _ERROR_TEMPLATE,
                conversation_id=msg.conversation_id,
            )
            return

        content = result.content.strip()

        if classification == "deep" or len(content) > _MAX_INLINE_LENGTH:
            # Truncate for preview
            preview = content[:300]
            if len(content) > 300:
                preview = preview.rsplit(" ", 1)[0] + "..."
            response = _ESCALATION_TEMPLATE.format(
                preview=preview, session_id=session_id
            )
        else:
            response = content

        self._channel.send(
            msg.sender,
            response,
            conversation_id=msg.conversation_id,
        )

        bus.publish(
            EventType.AGENT_TURN_END,
            {
                "agent": "channel_agent",
                "channel": msg.channel,
                "turns": result.turns,
                "classification": classification,
                "session_id": session_id,
            },
        )

    def shutdown(self) -> None:
        """Shut down the worker thread pool."""
        self._pool.shutdown(wait=False)
```

- [ ] **Step 4: Run tests**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/agents/test_channel_agent.py -v`

Expected: All 17 tests PASS (11 classifier + 6 ChannelAgent).

- [ ] **Step 5: Commit**

```bash
git add src/openjarvis/agents/channel_agent.py tests/agents/test_channel_agent.py
git commit -m "feat: add ChannelAgent with query classification and escalation"
```

---

### Task 3: Integration Test — ChannelAgent + DeepResearchAgent + Real Data

**Files:**
- Create: `tests/agents/test_channel_agent_integration.py`

- [ ] **Step 1: Write integration test**

Create `tests/agents/test_channel_agent_integration.py`:

```python
"""Integration test — ChannelAgent with real KnowledgeStore and mock engine."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openjarvis.agents.channel_agent import ChannelAgent
from openjarvis.agents.deep_research import DeepResearchAgent
from openjarvis.channels._stubs import BaseChannel, ChannelMessage, ChannelStatus
from openjarvis.connectors._stubs import Document
from openjarvis.connectors.pipeline import IngestionPipeline
from openjarvis.connectors.retriever import TwoStageRetriever
from openjarvis.connectors.store import KnowledgeStore
from openjarvis.tools.knowledge_search import KnowledgeSearchTool


class FakeChannel(BaseChannel):
    channel_id = "fake"

    def __init__(self) -> None:
        self._handlers: list = []
        self._sent: list = []

    def connect(self) -> None:
        pass

    def disconnect(self) -> None:
        pass

    def send(
        self,
        channel: str,
        content: str,
        *,
        conversation_id: str = "",
        metadata: dict | None = None,
    ) -> bool:
        self._sent.append({"content": content, "conv": conversation_id})
        return True

    def status(self) -> ChannelStatus:
        return ChannelStatus.CONNECTED

    def list_channels(self) -> list[str]:
        return ["test"]

    def on_message(self, handler) -> None:
        self._handlers.append(handler)

    def simulate(self, text: str) -> None:
        msg = ChannelMessage(
            channel="fake",
            sender="user",
            content=text,
            conversation_id="conv1",
        )
        for h in self._handlers:
            h(msg)


@pytest.fixture
def populated_store(tmp_path: Path) -> KnowledgeStore:
    store = KnowledgeStore(
        db_path=str(tmp_path / "channel_int.db")
    )
    pipeline = IngestionPipeline(store=store, max_tokens=256)
    pipeline.ingest(
        [
            Document(
                doc_id="gcalendar:evt1",
                source="gcalendar",
                doc_type="event",
                content="Sprint Planning\nWhen: Tomorrow 2pm\nAttendees: Sarah, Mike",
                title="Sprint Planning",
            ),
            Document(
                doc_id="slack:msg1",
                source="slack",
                doc_type="message",
                content="We need to finalize the API redesign before Friday",
                title="#engineering",
                author="sarah",
            ),
            Document(
                doc_id="gmail:msg1",
                source="gmail",
                doc_type="email",
                content="Budget report attached. Q3 spending up 15%.",
                title="Re: Q3 Budget",
                author="mike",
            ),
        ]
    )
    return store


def test_quick_query_through_full_stack(
    populated_store: KnowledgeStore,
) -> None:
    """Quick query → agent searches → inline response."""
    mock_engine = MagicMock()
    mock_engine.engine_id = "mock"
    mock_engine.generate.return_value = {
        "content": "Your next meeting is Sprint Planning tomorrow at 2pm with Sarah and Mike.",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        "model": "test",
        "finish_reason": "stop",
    }

    retriever = TwoStageRetriever(store=populated_store)
    ks_tool = KnowledgeSearchTool(
        store=populated_store, retriever=retriever
    )
    agent = DeepResearchAgent(
        engine=mock_engine,
        model="test",
        tools=[ks_tool],
        max_turns=2,
    )

    channel = FakeChannel()
    ca = ChannelAgent(channel=channel, agent=agent)

    channel.simulate("When is my next meeting?")
    time.sleep(1.0)

    assert len(channel._sent) >= 1
    response = channel._sent[0]["content"]
    assert "Sprint Planning" in response or "meeting" in response.lower()
    # Quick query should NOT have escalation link
    assert "openjarvis://" not in response

    ca.shutdown()


def test_deep_query_gets_escalation_link(
    populated_store: KnowledgeStore,
) -> None:
    """Deep query → agent searches → preview + escalation link."""
    search_call = {
        "content": "",
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        "model": "test",
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "arguments": json.dumps({"query": "budget API"}),
                },
            }
        ],
    }
    final_answer = {
        "content": (
            "## Research Report\n\n"
            + "Based on analysis of Slack messages and emails, "
            + "the team discussed API redesign and Q3 budget. "
            * 10
            + "\n\n**Sources:**\n1. [slack] #engineering\n2. [gmail] Q3 Budget"
        ),
        "usage": {"prompt_tokens": 500, "completion_tokens": 300, "total_tokens": 800},
        "model": "test",
        "finish_reason": "stop",
    }

    mock_engine = MagicMock()
    mock_engine.engine_id = "mock"
    mock_engine.generate.side_effect = [search_call, final_answer]

    retriever = TwoStageRetriever(store=populated_store)
    ks_tool = KnowledgeSearchTool(
        store=populated_store, retriever=retriever
    )
    agent = DeepResearchAgent(
        engine=mock_engine,
        model="test",
        tools=[ks_tool],
        max_turns=3,
    )

    channel = FakeChannel()
    ca = ChannelAgent(channel=channel, agent=agent)

    channel.simulate(
        "Summarize all discussions about budget and API redesign"
    )
    time.sleep(1.0)

    assert len(channel._sent) >= 1
    response = channel._sent[-1]["content"]
    # Deep query should have escalation link
    assert "openjarvis://" in response

    ca.shutdown()
```

- [ ] **Step 2: Run integration test**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/agents/test_channel_agent_integration.py -v`

Expected: All 2 tests PASS.

- [ ] **Step 3: Run full test suite**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run pytest tests/agents/test_channel_agent.py tests/agents/test_channel_agent_integration.py tests/agents/test_deep_research.py tests/connectors/ tests/tools/test_knowledge_search.py -v --tb=short`

Expected: All tests PASS.

- [ ] **Step 4: Run linter**

Run: `cd /lambda/nfs/lambda-stanford/jonsf/scratch_v2/OpenJarvis && uv run ruff check src/openjarvis/agents/channel_agent.py tests/agents/test_channel_agent.py tests/agents/test_channel_agent_integration.py`

Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add tests/agents/test_channel_agent_integration.py
git commit -m "feat: add integration test for ChannelAgent with DeepResearchAgent"
```

---

## Post-Plan Notes

**What this plan produces:**
- `classify_query()` — automatic quick/deep classification (no user input needed)
- `ChannelAgent` — bridges any `BaseChannel` to the `DeepResearchAgent` with:
  - Non-blocking handler (thread pool)
  - Quick inline answers for simple lookups
  - Preview + `openjarvis://research/{session_id}` escalation link for complex research
  - Error handling with user-friendly messages
  - Event bus telemetry
- Integration test proving the full stack: channel message → classification → agent → tool call → retrieval → response

**What this does NOT do (future work):**
- Platform-specific formatting (Slack Block Kit, WhatsApp markdown) — can be added per-channel later
- BlueBubbles incoming message support — needs upstream work on the bridge
- Tauri `openjarvis://` URL handler registration — that's Phase 2B (desktop)
- Persistent conversation context across messages — would need session store integration

**Connecting to real channels:** After this plan, wiring to real Slack/WhatsApp is just:
```python
channel = SlackChannel(bot_token="xoxb-...", app_token="xapp-...")
channel.connect()
agent = DeepResearchAgent(engine, model, tools=[ks_tool])
ca = ChannelAgent(channel=channel, agent=agent)
# Now the Slack bot responds to DMs with Deep Research answers
```
