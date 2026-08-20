"""Shared test fixtures for the evaluation framework."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import pytest

from openjarvis.evals.core.backend import InferenceBackend
from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord

# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------


class MockBackend(InferenceBackend):
    """Backend that returns canned responses for testing."""

    backend_id = "mock"

    def __init__(self, responses: Optional[Dict[str, str]] = None) -> None:
        self._responses = responses or {}
        self._default_response = "Mock response"
        self._call_count = 0

    def generate(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        self._call_count += 1
        return self._responses.get(prompt, self._default_response)

    def generate_full(
        self,
        prompt: str,
        *,
        model: str,
        system: str = "",
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        content = self.generate(
            prompt,
            model=model,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return {
            "content": content,
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
            },
            "model": model,
            "latency_seconds": 0.1,
            "cost_usd": 0.001,
            "energy_joules": 50.0,
            "power_watts": 250.0,
            "gpu_utilization_pct": 45.0,
            "throughput_tok_per_sec": 38.0,
            "ttft": 0.0,
        }


class MockScorer(Scorer):
    """Scorer that always returns a fixed result."""

    scorer_id = "mock"

    def __init__(self, result: bool = True) -> None:
        self._result = result

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        return self._result, {"mock": True}


class MockDataset(DatasetProvider):
    """Dataset that yields fixed records."""

    dataset_id = "mock"
    dataset_name = "Mock"

    def __init__(self, records: Optional[list[EvalRecord]] = None) -> None:
        self._records = records or []

    def load(self, *, max_samples=None, split=None, seed=None) -> None:
        pass

    def iter_records(self):
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_backend():
    return MockBackend()


@pytest.fixture()
def mock_scorer():
    return MockScorer()


@pytest.fixture()
def sample_records():
    return [
        EvalRecord(
            record_id="test-001",
            problem="What is 2+2?",
            reference="4",
            category="reasoning",
            subject="math",
        ),
        EvalRecord(
            record_id="test-002",
            problem="What is the capital of France?",
            reference="Paris",
            category="reasoning",
            subject="geography",
        ),
        EvalRecord(
            record_id="test-003",
            problem="Hello, how are you?",
            reference="I'm fine, thank you!",
            category="chat",
            subject="greeting",
        ),
    ]


@pytest.fixture()
def mock_dataset(sample_records):
    return MockDataset(sample_records)
