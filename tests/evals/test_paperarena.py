"""Tests for PaperArena benchmark."""

from unittest.mock import MagicMock

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.datasets.paperarena import PaperArenaDataset
from openjarvis.evals.scorers.paperarena_judge import PaperArenaScorer


def _mock_backend() -> MagicMock:
    backend = MagicMock()
    backend.generate.return_value = "CORRECT"
    return backend


class TestPaperArenaDataset:
    def test_instantiation(self) -> None:
        ds = PaperArenaDataset()
        assert ds.dataset_id == "paperarena"
        assert ds.dataset_name == "PaperArena"

    def test_has_required_methods(self) -> None:
        ds = PaperArenaDataset()
        assert hasattr(ds, "load")
        assert hasattr(ds, "iter_records")
        assert hasattr(ds, "size")


class TestPaperArenaScorer:
    def test_instantiation(self) -> None:
        s = PaperArenaScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "paperarena"

    def test_mc_correct(self) -> None:
        s = PaperArenaScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="pa-1",
            problem="## Question\nWhat is X?\nOptions:\n  A) foo\n  B) bar",
            reference="A",
            category="agentic",
            subject="easy_mc",
            metadata={"question_type": "MC"},
        )
        is_correct, meta = s.score(record, "The answer is A")
        assert is_correct is True
        assert meta["match_type"] == "exact_letter"

    def test_mc_wrong(self) -> None:
        s = PaperArenaScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="pa-2",
            problem="Question",
            reference="B",
            category="agentic",
            subject="medium_mc",
            metadata={"question_type": "MC"},
        )
        is_correct, meta = s.score(record, "The answer is C")
        assert is_correct is False
        assert meta["candidate_letter"] == "C"

    def test_open_answer_judge(self) -> None:
        s = PaperArenaScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="pa-3",
            problem="## Question\nExplain X",
            reference="X is a method for...",
            category="agentic",
            subject="hard_oa",
            metadata={"question_type": "OA"},
        )
        is_correct, meta = s.score(record, "X is a technique used to...")
        assert is_correct is True
        assert meta["match_type"] == "llm_judge"

    def test_closed_answer_judge(self) -> None:
        backend = MagicMock()
        backend.generate.return_value = "INCORRECT"
        s = PaperArenaScorer(backend, "test-model")
        record = EvalRecord(
            record_id="pa-4",
            problem="## Question\nWhat is the value?",
            reference="42.5",
            category="agentic",
            subject="medium_ca",
            metadata={"question_type": "CA"},
        )
        is_correct, meta = s.score(record, "The value is 100")
        assert is_correct is False

    def test_empty_response(self) -> None:
        s = PaperArenaScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="pa-5",
            problem="q",
            reference="a",
            category="agentic",
        )
        is_correct, meta = s.score(record, "")
        assert is_correct is False
        assert meta["reason"] == "empty_response"


class TestPaperArenaCLI:
    def test_in_benchmarks(self) -> None:
        from openjarvis.evals.cli import BENCHMARKS

        assert "paperarena" in BENCHMARKS

    def test_build_dataset(self) -> None:
        from openjarvis.evals.cli import _build_dataset

        ds = _build_dataset("paperarena")
        assert ds.dataset_id == "paperarena"

    def test_build_scorer(self) -> None:
        from openjarvis.evals.cli import _build_scorer

        s = _build_scorer("paperarena", _mock_backend(), "test-model")
        assert s.scorer_id == "paperarena"
