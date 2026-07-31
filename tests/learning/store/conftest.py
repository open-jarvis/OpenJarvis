from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from openjarvis.learning.candidates import (
    CandidateExtractor,
    ExtractionResult,
)
from openjarvis.learning.evaluation import TraceEvaluation
from openjarvis.learning.store import LearningRepository, SQLiteLearningDatabase
from tests.learning.candidates.conftest import NOW, envelope, make_evaluation


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    return (tmp_path / "learning.sqlite3").resolve()


@pytest.fixture
def repository(database_path: Path) -> LearningRepository:
    value = LearningRepository(SQLiteLearningDatabase(database_path))
    value.initialize()
    return value


@pytest.fixture
def extraction_factory() -> Callable[..., tuple[TraceEvaluation, ExtractionResult]]:
    def factory(
        **evaluation_changes: object,
    ) -> tuple[TraceEvaluation, ExtractionResult]:
        evaluation = make_evaluation(**evaluation_changes)
        result = CandidateExtractor().extract(
            (envelope(evaluation),),
            created_at=NOW,
        )
        return evaluation, result

    return factory


def ingest(
    repository: LearningRepository,
    evaluation: TraceEvaluation,
    result: ExtractionResult,
    *,
    key: str = "idempotency_ingest",
):
    return repository.ingest(
        result,
        (evaluation,),
        idempotency_key=key,
        correlation_id=f"correlation_{key}",
    )


def clone_run(result: ExtractionResult, run_id: str) -> ExtractionResult:
    payload = {
        field_name: getattr(result, field_name)
        for field_name in type(result).model_fields
    }
    payload["run_id"] = run_id
    return ExtractionResult.model_validate(payload)


__all__ = [
    "NOW",
    "clone_run",
    "envelope",
    "ingest",
    "make_evaluation",
]
