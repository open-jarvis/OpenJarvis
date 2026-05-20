"""Tests for the research_loop agent — focused on loop invariants.

The fixtures use a minimal mock engine so these tests are fast and don't
require a running Ollama daemon.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence
from unittest.mock import MagicMock

import pytest

from openjarvis.agents.research_loop import (
    SEARCH_TOOL_SPEC,
    SYSTEM_PROMPT,
    ResearchAgent,
    _hit_url,
    build_sources_for_client,
)
from openjarvis.connectors.hybrid_search import SearchHit


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


# ---------------------------------------------------------------------------
# _hit_url — Slack permalink reconstruction
# ---------------------------------------------------------------------------


def test_hit_url_slack_full_workspace() -> None:
    """A workspace-qualified doc_id produces an ``{team}.slack.com`` permalink."""
    url = _hit_url("slack", "slack:acme:C123:1710500000.000100")
    assert url == "https://acme.slack.com/archives/C123/p1710500000000100"


def test_hit_url_slack_legacy_two_segment_doc_id() -> None:
    """Legacy ``slack:{channel}:{ts}`` ids fall back to the docless form."""
    url = _hit_url("slack", "slack:C123:1710500000.000100")
    assert url == "https://slack.com/archives/C123/p1710500000000100"


def test_hit_url_slack_empty_team_domain() -> None:
    """Empty workspace segment still produces a usable docless permalink."""
    url = _hit_url("slack", "slack::C123:1710500000.000100")
    assert url == "https://slack.com/archives/C123/p1710500000000100"


def test_hit_url_unknown_source_returns_empty() -> None:
    """Unsupported sources don't get a guessed URL."""
    assert _hit_url("notion", "notion:abc") == ""
    assert _hit_url("", "") == ""


def _mk_hit(
    *,
    source: str = "granola",
    document_id: str = "granola:not_abc12345678901",
    url: str = "",
    title: str = "Sprint Planning",
) -> SearchHit:
    """Tiny SearchHit factory for URL-routing tests."""
    return SearchHit(
        chunk_id="c1",
        document_id=document_id,
        chunk_idx=0,
        title=title,
        content_snippet="...",
        source=source,
        timestamp="2024-03-15T10:00:00",
        participants=["alice@co.com"],
        score=0.5,
        bm25_score=0.5,
        vector_score=0.5,
        url=url,
    )


def test_build_sources_prefers_stored_url_over_reconstruction() -> None:
    """When the connector stored a URL, the client gets it verbatim.

    The doc_id-based reconstruction is a *fallback* — sources like Granola
    that supply the URL at ingest time must surface it unchanged.
    """
    stored = "https://notes.granola.ai/d/e98b5d85-ff57-46ac-a0ce-849fc68d086f"
    sources = build_sources_for_client([_mk_hit(url=stored)])
    assert sources[0]["url"] == stored


def test_build_sources_falls_back_to_reconstruction_when_url_missing() -> None:
    """Slack/Gmail still work without a stored URL — reconstructed from doc_id."""
    sources = build_sources_for_client(
        [
            _mk_hit(
                source="slack",
                document_id="slack:acme:C123:1710500000.000100",
                url="",
                title="#general",
            )
        ]
    )
    assert (
        sources[0]["url"]
        == "https://acme.slack.com/archives/C123/p1710500000000100"
    )


def test_hit_url_granola_not_reconstructible() -> None:
    """Granola doc_ids cannot reconstruct a web URL.

    The Granola web app uses a UUID that is different from the API
    ``note_id`` embedded in our doc_id. Citation URLs for Granola must
    come from the stored ``SearchHit.url`` (populated at ingest time from
    the API's ``web_url`` field). ``_hit_url`` therefore returns empty.
    """
    assert _hit_url("granola", "granola:not_abc12345678901") == ""
    assert _hit_url("granola", "granola:") == ""
    assert _hit_url("granola", "") == ""


# ---------------------------------------------------------------------------
# Sources filter — propagated through _execute_search to HybridSearch.search
# ---------------------------------------------------------------------------


def test_search_with_sources_filter_is_passed_through(
    stub_search: MagicMock,
) -> None:
    """A search tool call carrying ``sources=['granola']`` reaches HybridSearch.

    Without this propagation, "tell me about my Granola notes" returns Gmail
    emails that mention Granola instead of actual meeting notes.
    """
    engine = _MockEngine(
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "s1",
                        "name": "search",
                        "arguments": json.dumps(
                            {
                                "query": "recent meetings",
                                "sources": ["granola"],
                            }
                        ),
                    }
                ],
                "usage": {},
            },
            _text_response("Here are your recent meetings."),
        ]
    )

    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=2)
    result = agent.run("tell me about my recent meetings from Granola")

    stub_search.search.assert_called_once()
    kwargs = stub_search.search.call_args.kwargs
    assert kwargs.get("sources") == ["granola"]
    # And the loop terminates with the synthesized answer.
    assert "Here are your recent meetings." in result.answer


def test_search_sources_coerces_scalar_to_list(stub_search: MagicMock) -> None:
    """If the model sends ``sources='slack'`` (string), wrap it as ``['slack']``."""
    engine = _MockEngine(
        responses=[
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "s1",
                        "name": "search",
                        "arguments": json.dumps(
                            {"query": "anything", "sources": "slack"}
                        ),
                    }
                ],
                "usage": {},
            },
            _text_response("done"),
        ]
    )
    agent = ResearchAgent(engine, stub_search, model="mock", max_iterations=2)
    agent.run("anything in slack")

    kwargs = stub_search.search.call_args.kwargs
    assert kwargs.get("sources") == ["slack"]


# ---------------------------------------------------------------------------
# Prompt + tool schema — the planner must see the sources directive
# ---------------------------------------------------------------------------


def test_tool_schema_sources_lists_known_connectors() -> None:
    """The ``sources`` parameter description enumerates the common connector IDs.

    Without explicit IDs in the description the planner makes up names like
    "Granola" or "Slack workspace" instead of the lowercase connector IDs the
    backend filter actually matches against.
    """
    sources_prop = SEARCH_TOOL_SPEC["function"]["parameters"]["properties"]["sources"]
    desc = sources_prop["description"]
    for connector_id in ("granola", "slack", "gmail", "notion"):
        assert connector_id in desc


def test_system_prompt_mandates_sources_extraction() -> None:
    """The system prompt has a directive telling the planner to extract sources.

    Without it, the model treats "from my Granola notes" as a topical cue
    rather than a hard filter, and returns email about Granola instead of
    Granola records.
    """
    assert "sources=" in SYSTEM_PROMPT
    # Synonym mapping for the most-common alias.
    assert "granola" in SYSTEM_PROMPT.lower()
    assert "meeting notes" in SYSTEM_PROMPT.lower()
