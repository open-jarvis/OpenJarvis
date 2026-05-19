"""Tests for the research_loop agent — focused on loop invariants.

The fixtures use a minimal mock engine so these tests are fast and don't
require a running Ollama daemon.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import MagicMock

import pytest

from openjarvis.agents.research_loop import ResearchAgent


class _MockEngine:
    """Engine stub that lets a test script the per-call response.

    ``responses`` is a list of dicts in ``OllamaEngine.generate`` shape
    (``content``, ``tool_calls``, ``usage``); each call to ``generate``
    consumes the next entry. When the script runs out, the engine repeats
    the final entry — handy for "loop forever" mock behaviors.
    """

    def __init__(self, responses: List[Dict[str, Any]]):
        self._responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def generate(
        self,
        messages: Sequence,
        *,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        num_ctx: int = 8192,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self.calls.append({"tools": tools, "messages": list(messages)})
        if self._responses:
            return (
                self._responses.pop(0)
                if len(self._responses) > 1
                else self._responses[0]
            )
        return {"content": "", "tool_calls": [], "usage": {}}


def _search_call(call_id: str, query: str = "anything") -> Dict[str, Any]:
    return {
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "name": "search",
                "arguments": json.dumps({"query": query}),
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _text_response(text: str) -> Dict[str, Any]:
    return {
        "content": text,
        "tool_calls": [],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
    }


@pytest.fixture()
def stub_search() -> MagicMock:
    """A HybridSearch stand-in whose .search() returns an empty hit list."""
    s = MagicMock()
    s.search.return_value = []
    return s


def test_forced_synthesis_when_budget_exhausts(stub_search: MagicMock) -> None:
    """Loop exits cleanly with a synthesis even when the model keeps tool-calling.

    With max_iterations=1, the budget is exhausted after a single search.
    The next engine call receives ``tools=None`` and is expected to produce
    a text answer; the new forced-synthesis fallback then makes one more
    no-tools call to ensure we always return something usable.
    """
    # Force the loop to fall through to the new forced-synthesis path: every
    # in-loop iteration returns a tool call (so we never take an early text
    # return), and the final post-loop call returns text.
    engine = _MockEngine(
        responses=[
            _search_call("call-1"),
            _search_call("call-2"),
            _text_response("Here is what I found: nothing usable."),
        ]
    )

    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=1)
    result = agent.run("test query")

    assert "Here is what I found" in result.answer
    assert "loop exhausted" not in result.answer.lower()
    # The final call was made with tools=None (the forced-synthesis path).
    assert engine.calls[-1]["tools"] is None
    assert all(t.tool_name == "search" for t in result.tool_calls)


def test_forced_synthesis_returns_sentinel_when_model_stays_silent(
    stub_search: MagicMock,
) -> None:
    """If even the forced final call returns no text, surface a clear sentinel.

    This is the gracefully-degraded case: the loop did its best but the model
    refused to emit text. The contract is still that ``answer`` is a non-empty
    string the caller can show to the user.
    """
    engine = _MockEngine(
        responses=[
            _search_call("call-1"),
            _search_call("call-2"),
            {"content": "", "tool_calls": [], "usage": {}},  # silent forced call
        ]
    )

    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=1)
    result = agent.run("test query")

    assert result.answer  # non-empty
    assert "no synthesis available" in result.answer.lower()


def test_first_turn_text_response_returns_directly(stub_search: MagicMock) -> None:
    """When the model produces text on the very first turn, return it as-is."""
    engine = _MockEngine(responses=[_text_response("Quick answer.")])
    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=5)
    result = agent.run("hello")
    assert result.answer == "Quick answer."
    assert result.tool_calls == []
    # Only one engine call needed.
    assert len(engine.calls) == 1


def test_clarify_before_any_search_is_rejected(stub_search: MagicMock) -> None:
    """clarify() invoked before a search call must return a runtime error result.

    The system prompt asks the planner to search first, but the loop also
    enforces this at runtime so a non-compliant planner can't surprise the
    user with a pre-emptive clarification.
    """
    clarify_calls: List[str] = []

    def fake_clarify(q: str) -> str:
        clarify_calls.append(q)
        return "user response"

    engine = _MockEngine(
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "c1",
                        "name": "clarify",
                        "arguments": json.dumps({"question": "who?"}),
                    }
                ],
                "usage": {},
            },
            _text_response("Final."),
        ]
    )

    agent = ResearchAgent(
        engine, stub_search, model="mock", max_iterations=5,
        clarify_handler=fake_clarify,
    )
    result = agent.run("vague query")

    # Handler must not have been called because the dispatch returned an error.
    assert clarify_calls == []
    # No clarify invocation recorded.
    assert all(t.tool_name != "clarify" for t in result.tool_calls)
    assert result.answer == "Final."
