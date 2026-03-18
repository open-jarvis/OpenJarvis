"""Tests for the browser_assistant scorer."""

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers.browser_assistant import (
    BrowserAssistantScorer,
)


def _make_record(exact_facts=None, semantic_facts=None):
    all_facts = []
    if exact_facts:
        all_facts += [{"fact": f, "type": "exact"} for f in exact_facts]
    if semantic_facts:
        all_facts += [{"fact": f, "type": "semantic"} for f in semantic_facts]
    return EvalRecord(
        record_id="test-ba-1",
        problem="Research this topic.",
        reference="",
        category="agentic",
        metadata={
            "question": "Test question",
            "expected_facts": all_facts,
            "exact_facts": exact_facts or [],
            "semantic_facts": semantic_facts or [],
        },
    )


def test_exact_facts_found():
    record = _make_record(exact_facts=["128K tokens", "5432"])
    scorer = BrowserAssistantScorer()

    answer = (
        "The context window is 128K tokens. "
        "PostgreSQL runs on port 5432. "
        "Source: official documentation."
    )
    is_correct, meta = scorer.score(record, answer)
    assert meta["exact_found"] == 2
    assert meta["exact_score"] == 1.0
    assert meta["sources_cited"] is True


def test_partial_exact_match():
    record = _make_record(exact_facts=["128K tokens", "H200"])
    scorer = BrowserAssistantScorer()

    answer = "The context window is 128K tokens."
    is_correct, meta = scorer.score(record, answer)
    assert meta["exact_found"] == 1
    assert meta["exact_score"] == 0.5


def test_semantic_facts_heuristic():
    record = _make_record(
        semantic_facts=[
            "Podman is daemonless",
            "Docker uses client-server architecture",
        ],
    )
    scorer = BrowserAssistantScorer()

    answer = (
        "Podman runs without a daemon (daemonless). "
        "Docker uses a client-server architecture with "
        "dockerd. Source: official docs."
    )
    is_correct, meta = scorer.score(record, answer)
    assert meta["semantic_passed"] >= 1
    assert meta["sources_cited"] is True


def test_sources_with_url():
    record = _make_record(exact_facts=["5432"])
    scorer = BrowserAssistantScorer()

    answer = "Port 5432. See https://www.postgresql.org/docs/"
    is_correct, meta = scorer.score(record, answer)
    assert meta["sources_cited"] is True


def test_empty_answer():
    record = _make_record(exact_facts=["something"])
    scorer = BrowserAssistantScorer()
    is_correct, meta = scorer.score(record, "")
    assert is_correct is False
    assert meta["reason"] == "empty_response"


def test_no_facts():
    record = EvalRecord(
        record_id="test-ba-2",
        problem="Research something.",
        reference="",
        category="agentic",
        metadata={
            "expected_facts": [],
            "exact_facts": [],
            "semantic_facts": [],
        },
    )
    scorer = BrowserAssistantScorer()
    is_correct, meta = scorer.score(record, "Some answer.")
    assert is_correct is None
    assert meta["reason"] == "no_expected_facts"
