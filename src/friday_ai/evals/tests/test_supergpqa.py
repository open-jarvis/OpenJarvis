"""Tests for SuperGPQA scorer logic."""

from __future__ import annotations

from friday_ai.evals.core.types import EvalRecord
from friday_ai.evals.tests.conftest import MockBackend


class TestSuperGPQAScorer:
    def _make_record(self, answer="B", options=None):
        if options is None:
            options = ["Option A", "Option B", "Option C", "Option D"]
        return EvalRecord(
            record_id="sgpqa-1",
            problem=(
                "What is X?\n\nOptions:\n"
                "A. Option A\nB. Option B\n"
                "C. Option C\nD. Option D\n\n"
                "Respond with the correct letter only."
            ),
            reference=answer,
            category="reasoning",
            subject="math",
            metadata={"options": options},
        )

    def test_correct_extraction(self):
        from friday_ai.evals.scorers.supergpqa_mcq import SuperGPQAScorer

        backend = MockBackend(responses={})
        backend._default_response = "B"
        scorer = SuperGPQAScorer(backend, "gpt-4o")

        record = self._make_record(answer="B")
        is_correct, meta = scorer.score(record, "The answer is B")

        assert is_correct is True
        assert meta["reference_letter"] == "B"
        assert meta["candidate_letter"] == "B"

    def test_incorrect_extraction(self):
        from friday_ai.evals.scorers.supergpqa_mcq import SuperGPQAScorer

        backend = MockBackend()
        backend._default_response = "A"
        scorer = SuperGPQAScorer(backend, "gpt-4o")

        record = self._make_record(answer="B")
        is_correct, meta = scorer.score(record, "I think A")

        assert is_correct is False
        assert meta["candidate_letter"] == "A"

    def test_missing_reference(self):
        from friday_ai.evals.scorers.supergpqa_mcq import SuperGPQAScorer

        backend = MockBackend()
        scorer = SuperGPQAScorer(backend, "gpt-4o")

        record = self._make_record(answer="")
        is_correct, meta = scorer.score(record, "B")

        assert is_correct is None
        assert meta["reason"] == "missing_reference_letter"

    def test_no_extraction(self):
        from friday_ai.evals.scorers.supergpqa_mcq import SuperGPQAScorer

        backend = MockBackend()
        backend._default_response = "NONE"
        scorer = SuperGPQAScorer(backend, "gpt-4o")

        record = self._make_record(answer="B")
        is_correct, meta = scorer.score(record, "I don't know")

        assert is_correct is None
        assert meta["reason"] == "no_choice_letter_extracted"

    def test_valid_letters_from_options(self):
        from friday_ai.evals.scorers.supergpqa_mcq import SuperGPQAScorer

        backend = MockBackend()
        scorer = SuperGPQAScorer(backend, "gpt-4o")

        # 5 options
        metadata = {"options": ["A", "B", "C", "D", "E"]}
        letters = scorer._valid_letters_from_options(metadata)
        assert letters == "ABCDE"

        # No options
        letters = scorer._valid_letters_from_options({})
        assert letters == "ABCD"

    def test_extraction_with_verbose_response(self):
        from friday_ai.evals.scorers.supergpqa_mcq import SuperGPQAScorer

        backend = MockBackend()
        backend._default_response = "THE ANSWER IS: C"
        scorer = SuperGPQAScorer(backend, "gpt-4o")

        record = self._make_record(answer="C")
        is_correct, meta = scorer.score(record, "After analysis, C is correct")

        assert is_correct is True
        assert meta["candidate_letter"] == "C"
