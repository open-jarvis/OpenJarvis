"""Tests for the shared binary checklist scorer."""

from __future__ import annotations

from openjarvis.evals.scorers._checklist import (
    ChecklistScorer,
    contains_key_phrases,
    normalize_str,
)


def test_normalize_str_basic():
    assert normalize_str("Hello, World!") == "hello world"


def test_normalize_str_whitespace():
    assert normalize_str("  lots   of   spaces  ") == "lots of spaces"


def test_contains_key_phrases_above_threshold():
    answer = "The system uses SQLite and FAISS for memory storage."
    reference = "SQLite; FAISS; BM25; hybrid"
    # 2 of 4 phrases = 50%, meets default threshold
    assert contains_key_phrases(answer, reference) is True


def test_contains_key_phrases_below_threshold():
    answer = "The system uses PostgreSQL."
    reference = "SQLite; FAISS; BM25; hybrid"
    assert contains_key_phrases(answer, reference) is False


def test_contains_key_phrases_empty_reference():
    assert contains_key_phrases("anything", "") is False


class FakeJudgeBackend:
    """Mock backend that returns a canned checklist evaluation."""

    def __init__(self, response: str):
        self._response = response

    def generate(self, prompt, **kwargs):
        return self._response


def test_checklist_scorer_all_pass():
    response = (
        "1. yes — The response mentions Redis\n"
        "2. yes — The response mentions port 6379\n"
    )
    backend = FakeJudgeBackend(response)
    scorer = ChecklistScorer(backend, "test-model")
    score, details = scorer.score_checklist(
        model_answer="Redis runs on port 6379 by default.",
        checklist=[
            "The response mentions Redis",
            "The response mentions port 6379",
        ],
    )
    assert score == 1.0
    assert len(details) == 2
    assert all(d["passed"] for d in details)


def test_checklist_scorer_partial():
    response = "1. yes — Redis is mentioned\n2. no — Port number not found\n"
    backend = FakeJudgeBackend(response)
    scorer = ChecklistScorer(backend, "test-model")
    score, details = scorer.score_checklist(
        model_answer="Redis is a key-value store.",
        checklist=[
            "The response mentions Redis",
            "The response mentions port 6379",
        ],
    )
    assert score == 0.5
    assert details[0]["passed"] is True
    assert details[1]["passed"] is False


def test_checklist_scorer_empty_answer():
    backend = FakeJudgeBackend("")
    scorer = ChecklistScorer(backend, "test-model")
    score, details = scorer.score_checklist(
        model_answer="",
        checklist=["Something"],
    )
    assert score == 0.0
