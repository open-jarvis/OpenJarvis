"""Tests for the doc_qa scorer."""

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers.doc_qa import DocQAScorer


def _make_record(required_facts):
    return EvalRecord(
        record_id="test-dq-1",
        problem="Answer using the provided documents.",
        reference="",
        category="agentic",
        metadata={
            "question": "What is VACUUM?",
            "documents": [
                {"title": "Doc A", "content": "..."},
                {"title": "Doc B", "content": "..."},
            ],
            "required_facts": required_facts,
        },
    )


def test_all_facts_with_citations():
    facts = [
        {"fact": "reclaims storage from dead tuples", "source_doc_index": 0},
        {"fact": "must run periodically", "source_doc_index": 0},
    ]
    record = _make_record(facts)
    scorer = DocQAScorer()

    answer = (
        "VACUUM reclaims storage from dead tuples "
        "[Doc 1]. It must run periodically to keep "
        "the database healthy [Doc 1]."
    )
    is_correct, meta = scorer.score(record, answer)
    assert meta["facts_found"] == 2
    assert meta["fact_score"] == 1.0
    assert meta["citation_score"] == 1.0
    assert is_correct is True


def test_facts_without_citations():
    facts = [
        {"fact": "reclaims storage from dead tuples", "source_doc_index": 0},
    ]
    record = _make_record(facts)
    scorer = DocQAScorer()

    # No citations in answer
    answer = "VACUUM reclaims storage from dead tuples."
    is_correct, meta = scorer.score(record, answer)
    assert meta["facts_found"] == 1
    assert meta["fact_score"] == 1.0
    assert meta["citation_score"] == 0.0
    # Without citations, can't reach 0.7 threshold
    assert is_correct is False


def test_partial_facts():
    facts = [
        {"fact": "reclaims storage", "source_doc_index": 0},
        {"fact": "prevents table bloat", "source_doc_index": 0},
        {"fact": "updates visibility map", "source_doc_index": 1},
    ]
    record = _make_record(facts)
    scorer = DocQAScorer()

    answer = "VACUUM reclaims storage [Doc 1]. It also prevents table bloat [Doc 1]."
    is_correct, meta = scorer.score(record, answer)
    assert meta["facts_found"] == 2
    assert 0.6 <= meta["fact_score"] <= 0.7


def test_wrong_citation():
    facts = [
        {"fact": "reclaims storage", "source_doc_index": 0},
    ]
    record = _make_record(facts)
    scorer = DocQAScorer()

    # Cites Doc 2 instead of Doc 1
    answer = "VACUUM reclaims storage [Doc 2]."
    is_correct, meta = scorer.score(record, answer)
    assert meta["facts_found"] == 1
    assert meta["citation_score"] == 0.0


def test_empty_answer():
    facts = [
        {"fact": "something", "source_doc_index": 0},
    ]
    record = _make_record(facts)
    scorer = DocQAScorer()
    is_correct, meta = scorer.score(record, "")
    assert is_correct is False
    assert meta["reason"] == "empty_response"


def test_no_required_facts():
    record = EvalRecord(
        record_id="test-dq-2",
        problem="Answer the question.",
        reference="",
        category="agentic",
        metadata={"required_facts": []},
    )
    scorer = DocQAScorer()
    is_correct, meta = scorer.score(record, "Some answer.")
    assert is_correct is None
    assert meta["reason"] == "no_required_facts"
