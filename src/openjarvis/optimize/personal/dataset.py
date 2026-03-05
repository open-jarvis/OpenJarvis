"""DatasetProvider adapter for personal benchmarks."""

from __future__ import annotations

from typing import Iterable, List, Optional

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.types import EvalRecord
from openjarvis.optimize.personal.synthesizer import PersonalBenchmark


class PersonalBenchmarkDataset(DatasetProvider):
    """Wraps a PersonalBenchmark as a DatasetProvider for EvalRunner."""

    dataset_id: str = "personal"
    dataset_name: str = "Personal Benchmark"

    def __init__(self, benchmark: PersonalBenchmark) -> None:
        self._benchmark = benchmark
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        """Convert :class:`PersonalBenchmarkSample` instances to :class:`EvalRecord`."""
        samples = self._benchmark.samples
        if max_samples is not None:
            samples = samples[:max_samples]
        self._records = [
            EvalRecord(
                record_id=s.trace_id,
                problem=s.query,
                reference=s.reference_answer,
                category=s.category,
                subject=s.agent or "general",
                metadata=s.metadata,
            )
            for s in samples
        ]

    def iter_records(self) -> Iterable[EvalRecord]:
        """Iterate over loaded records."""
        return iter(self._records)

    def size(self) -> int:
        """Return the number of loaded records."""
        return len(self._records)


__all__ = ["PersonalBenchmarkDataset"]
