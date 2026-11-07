"""Tests for FRAMES scorer (judge prompt formatting and verdict parsing)."""

from __future__ import annotations

from friday_ai.evals.core.types import EvalRecord
from friday_ai.evals.scorers.frames_judge import _GRADER_TEMPLATE, FRAMESScorer
from friday_ai.evals.tests.conftest import MockBackend


class TestGraderTemplate:
    def test_template_formatting(self):
        result = _GRADER_TEMPLATE.format(
            question="What is the capital?",
            ground_truth="Paris",
            predicted_answer="The capital is Paris",
        )
        assert "What is the capital?" in result
        assert "Paris" in result
        assert "The capital is Paris" in result
        assert "correct: <yes or no>" in result

    def test_template_has_required_sections(self):
        assert "## Question" in _GRADER_TEMPLATE
        assert "## Ground Truth Answer" in _GRADER_TEMPLATE
        assert "## Predicted Answer" in _GRADER_TEMPLATE
        assert "extracted_final_answer:" in _GRADER_TEMPLATE


class TestFRAMESScorer:
    def _make_record(self, reference="Paris"):
        return EvalRecord(
            record_id="frames-1",
            problem="What is the capital of France?",
            reference=reference,
            category="rag",
            subject="general",
        )

    def test_correct_answer(self):
        backend = MockBackend()
        backend._default_response = (
            "extracted_final_answer: Paris\n"
            "reasoning: The answer correctly identifies Paris as the capital.\n"
            "correct: yes"
        )
        scorer = FRAMESScorer(backend, "gpt-4o")

        record = self._make_record("Paris")
        is_correct, meta = scorer.score(record, "The capital is Paris")

        assert is_correct is True
        assert "raw_judge_output" in meta
        assert meta["extracted_answer"] == "Paris"

    def test_incorrect_answer(self):
        backend = MockBackend()
        backend._default_response = (
            "extracted_final_answer: London\n"
            "reasoning: London is not the capital of France.\n"
            "correct: no"
        )
        scorer = FRAMESScorer(backend, "gpt-4o")

        record = self._make_record("Paris")
        is_correct, meta = scorer.score(record, "London")

        assert is_correct is False

    def test_empty_response(self):
        backend = MockBackend()
        scorer = FRAMESScorer(backend, "gpt-4o")

        record = self._make_record("Paris")
        is_correct, meta = scorer.score(record, "")

        assert is_correct is False
        assert meta["reason"] == "empty_response"

    def test_no_ground_truth(self):
        backend = MockBackend()
        scorer = FRAMESScorer(backend, "gpt-4o")

        record = self._make_record("")
        is_correct, meta = scorer.score(record, "Paris")

        assert is_correct is None
        assert meta["reason"] == "no_ground_truth"

    def test_fallback_true_false_parsing(self):
        backend = MockBackend()
        backend._default_response = "The prediction is TRUE"
        scorer = FRAMESScorer(backend, "gpt-4o")

        record = self._make_record("Paris")
        is_correct, _ = scorer.score(record, "Paris")

        assert is_correct is True

    def test_judge_error(self):
        class ErrorBackend(MockBackend):
            def generate(self, prompt, **kw):
                raise RuntimeError("API error")

        backend = ErrorBackend()
        scorer = FRAMESScorer(backend, "gpt-4o")

        record = self._make_record("Paris")
        is_correct, meta = scorer.score(record, "Paris")

        assert is_correct is None
        assert "error" in meta
