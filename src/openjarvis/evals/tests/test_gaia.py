"""Tests for GAIA scorer logic (normalization and exact match)."""

from __future__ import annotations

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers.gaia_exact import (
    GAIAScorer,
    _is_float,
    _normalize_number_str,
    _normalize_str,
    _split_string,
    exact_match,
)
from openjarvis.evals.tests.conftest import MockBackend


class TestNormalization:
    def test_normalize_number_str(self):
        assert _normalize_number_str("1000") == 1000.0
        assert _normalize_number_str("$1,000") == 1000.0
        assert _normalize_number_str("50%") == 50.0
        assert _normalize_number_str("abc") == float("inf")

    def test_normalize_str(self):
        assert _normalize_str("Hello World") == "helloworld"
        assert _normalize_str("Hello, World!", remove_punct=True) == "helloworld"
        assert _normalize_str("Hello, World!", remove_punct=False) == "hello,world!"

    def test_split_string(self):
        assert _split_string("a, b, c") == ["a", " b", " c"]
        assert _split_string("a; b") == ["a", " b"]

    def test_is_float(self):
        assert _is_float("3.14") is True
        assert _is_float("42") is True
        assert _is_float("abc") is False
        assert _is_float(None) is False


class TestExactMatch:
    def test_number_match(self):
        assert exact_match("42", "42") is True
        assert exact_match("$1,000", "1000") is True
        assert exact_match("43", "42") is False

    def test_string_match(self):
        assert exact_match("Paris", "paris") is True
        assert exact_match("  Paris  ", "paris") is True
        assert exact_match("London", "Paris") is False

    def test_list_match(self):
        assert exact_match("1, 2, 3", "1, 2, 3") is True
        assert exact_match("1, 2", "1, 2, 3") is False

    def test_none_answer(self):
        assert exact_match(None, "42") is False

    def test_punctuation_handling(self):
        assert exact_match("Hello!", "Hello") is True
        assert exact_match("test.", "test") is True


class TestGAIAScorer:
    def _make_record(self, reference="42"):
        return EvalRecord(
            record_id="gaia-001",
            problem="What is the answer?",
            reference=reference,
            category="agentic",
            subject="level_1",
        )

    def test_exact_match_correct(self):
        backend = MockBackend()
        scorer = GAIAScorer(backend, "gpt-4o")

        record = self._make_record("42")
        is_correct, meta = scorer.score(record, "42")

        assert is_correct is True
        assert meta["match_type"] == "exact"

    def test_exact_match_with_formatting(self):
        backend = MockBackend()
        scorer = GAIAScorer(backend, "gpt-4o")

        record = self._make_record("1000")
        is_correct, meta = scorer.score(record, "$1,000")

        assert is_correct is True
        assert meta["match_type"] == "exact"

    def test_llm_fallback(self):
        backend = MockBackend()
        backend._default_response = (
            "extracted_final_answer: 42\n"
            "reasoning: The answer is semantically equivalent.\n"
            "correct: yes"
        )
        scorer = GAIAScorer(backend, "gpt-4o")

        record = self._make_record("42")
        is_correct, meta = scorer.score(record, "The answer is forty-two")

        assert is_correct is True
        assert meta["match_type"] == "llm_fallback"

    def test_llm_fallback_incorrect(self):
        backend = MockBackend()
        backend._default_response = (
            "extracted_final_answer: 43\nreasoning: Different number.\ncorrect: no"
        )
        scorer = GAIAScorer(backend, "gpt-4o")

        record = self._make_record("42")
        is_correct, meta = scorer.score(record, "The answer is 43")

        assert is_correct is False

    def test_empty_response(self):
        backend = MockBackend()
        scorer = GAIAScorer(backend, "gpt-4o")

        record = self._make_record("42")
        is_correct, meta = scorer.score(record, "")

        assert is_correct is False
        assert meta["reason"] == "empty_response"

    def test_no_ground_truth(self):
        backend = MockBackend()
        scorer = GAIAScorer(backend, "gpt-4o")

        record = self._make_record("")
        is_correct, meta = scorer.score(record, "42")

        assert is_correct is None
        assert meta["reason"] == "no_ground_truth"
