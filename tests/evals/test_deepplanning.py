"""Tests for DeepPlanning benchmark."""

from unittest.mock import MagicMock

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.datasets.deepplanning import DeepPlanningDataset
from openjarvis.evals.scorers.deepplanning_scorer import DeepPlanningScorer


def _mock_backend() -> MagicMock:
    backend = MagicMock()
    backend.generate.return_value = "CORRECT"
    return backend


class TestDeepPlanningDataset:
    def test_instantiation(self) -> None:
        ds = DeepPlanningDataset()
        assert ds.dataset_id == "deepplanning"
        assert ds.dataset_name == "DeepPlanning"

    def test_has_required_methods(self) -> None:
        ds = DeepPlanningDataset()
        assert hasattr(ds, "load")
        assert hasattr(ds, "iter_records")
        assert hasattr(ds, "size")


class TestDeepPlanningScorer:
    def test_instantiation(self) -> None:
        s = DeepPlanningScorer(_mock_backend(), "test-model")
        assert s.scorer_id == "deepplanning"

    def test_correct_plan(self) -> None:
        s = DeepPlanningScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="dp-1",
            problem="## Task (travel)\nPlan a trip to Paris",
            reference="Day 1: Flight to Paris...",
            category="agentic",
            subject="travel",
            metadata={"task_type": "travel"},
        )
        is_correct, meta = s.score(record, "Day 1: Fly to Paris, visit Eiffel Tower")
        assert is_correct is True
        assert meta["match_type"] == "llm_judge"

    def test_incorrect_plan(self) -> None:
        backend = MagicMock()
        backend.generate.return_value = "INCORRECT - Missing budget constraint"
        s = DeepPlanningScorer(backend, "test-model")
        record = EvalRecord(
            record_id="dp-2",
            problem="## Task (shopping)\nBuild a cart",
            reference="Cart: item A, item B, total $50",
            category="agentic",
            subject="shopping",
            metadata={"task_type": "shopping"},
        )
        is_correct, meta = s.score(record, "Cart: item C, total $100")
        assert is_correct is False

    def test_empty_response(self) -> None:
        s = DeepPlanningScorer(_mock_backend(), "test-model")
        record = EvalRecord(
            record_id="dp-3",
            problem="task",
            reference="answer",
            category="agentic",
        )
        is_correct, meta = s.score(record, "")
        assert is_correct is False
        assert meta["reason"] == "empty_response"


class TestDeepPlanningCLI:
    def test_in_benchmarks(self) -> None:
        from openjarvis.evals.cli import BENCHMARKS

        assert "deepplanning" in BENCHMARKS

    def test_build_dataset(self) -> None:
        from openjarvis.evals.cli import _build_dataset

        ds = _build_dataset("deepplanning")
        assert ds.dataset_id == "deepplanning"

    def test_build_scorer(self) -> None:
        from openjarvis.evals.cli import _build_scorer

        s = _build_scorer("deepplanning", _mock_backend(), "test-model")
        assert s.scorer_id == "deepplanning"
