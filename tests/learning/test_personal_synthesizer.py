"""Tests for the personal benchmark system."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from openjarvis.core.types import Trace
from openjarvis.evals.core.types import EvalRecord
from openjarvis.learning.optimize.personal.dataset import PersonalBenchmarkDataset
from openjarvis.learning.optimize.personal.scorer import PersonalBenchmarkScorer
from openjarvis.learning.optimize.personal.synthesizer import (
    PersonalBenchmark,
    PersonalBenchmarkSample,
    PersonalBenchmarkSynthesizer,
)
from openjarvis.traces.store import TraceStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trace(
    trace_id: str = "t1",
    query: str = "What is 2+2?",
    agent: str = "simple",
    result: str = "4",
    feedback: float | None = 0.9,
    model: str = "test-model",
    engine: str = "test-engine",
    metadata: Dict[str, Any] | None = None,
) -> Trace:
    return Trace(
        trace_id=trace_id,
        query=query,
        agent=agent,
        result=result,
        feedback=feedback,
        model=model,
        engine=engine,
        metadata=metadata or {},
    )


@pytest.fixture()
def trace_store(tmp_path: Path) -> TraceStore:
    """Provide a fresh TraceStore backed by a temporary SQLite database."""
    return TraceStore(tmp_path / "traces.db")


# ---------------------------------------------------------------------------
# PersonalBenchmarkSample defaults
# ---------------------------------------------------------------------------


class TestPersonalBenchmarkSampleDefaults:
    def test_default_category(self) -> None:
        sample = PersonalBenchmarkSample(
            trace_id="t1",
            query="hello",
            reference_answer="world",
        )
        assert sample.category == "chat"

    def test_default_agent_empty(self) -> None:
        sample = PersonalBenchmarkSample(
            trace_id="t1",
            query="q",
            reference_answer="a",
        )
        assert sample.agent == ""

    def test_default_feedback_score_zero(self) -> None:
        sample = PersonalBenchmarkSample(
            trace_id="t1",
            query="q",
            reference_answer="a",
        )
        assert sample.feedback_score == 0.0

    def test_default_metadata_empty(self) -> None:
        sample = PersonalBenchmarkSample(
            trace_id="t1",
            query="q",
            reference_answer="a",
        )
        assert sample.metadata == {}


# ---------------------------------------------------------------------------
# PersonalBenchmarkSynthesizer
# ---------------------------------------------------------------------------


class TestPersonalBenchmarkSynthesizer:
    def test_synthesize_creates_benchmark_from_traces(
        self,
        trace_store: TraceStore,
    ) -> None:
        trace_store.save(_make_trace(trace_id="t1", feedback=0.9))
        trace_store.save(_make_trace(trace_id="t2", query="What is 3+3?", feedback=0.8))
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize(workflow_id="wf1")
        assert bm.workflow_id == "wf1"
        assert len(bm.samples) == 2
        assert bm.created_at > 0

    def test_filter_by_min_feedback(self, trace_store: TraceStore) -> None:
        trace_store.save(_make_trace(trace_id="t1", feedback=0.9))
        trace_store.save(_make_trace(trace_id="t2", feedback=0.5))
        trace_store.save(_make_trace(trace_id="t3", feedback=0.3))
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize(min_feedback=0.7)
        assert len(bm.samples) == 1
        assert bm.samples[0].trace_id == "t1"

    def test_none_feedback_excluded(self, trace_store: TraceStore) -> None:
        trace_store.save(_make_trace(trace_id="t1", feedback=None))
        trace_store.save(_make_trace(trace_id="t2", feedback=0.8))
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize(min_feedback=0.5)
        assert len(bm.samples) == 1
        assert bm.samples[0].trace_id == "t2"

    def test_grouping_by_query_class(self, trace_store: TraceStore) -> None:
        """Same agent + same query prefix -> same group, so only one sample."""
        trace_store.save(
            _make_trace(
                trace_id="t1",
                query="What is 2+2?",
                agent="simple",
                feedback=0.8,
            )
        )
        trace_store.save(
            _make_trace(
                trace_id="t2",
                query="What is 2+2?",
                agent="simple",
                feedback=0.95,
            )
        )
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize()
        # Should collapse into one sample (same group)
        assert len(bm.samples) == 1

    def test_picks_highest_feedback_per_group(self, trace_store: TraceStore) -> None:
        trace_store.save(
            _make_trace(
                trace_id="t1",
                query="Tell me a joke",
                agent="simple",
                feedback=0.7,
                result="bad joke",
            )
        )
        trace_store.save(
            _make_trace(
                trace_id="t2",
                query="Tell me a joke",
                agent="simple",
                feedback=0.99,
                result="great joke",
            )
        )
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize()
        assert len(bm.samples) == 1
        assert bm.samples[0].trace_id == "t2"
        assert bm.samples[0].reference_answer == "great joke"
        assert bm.samples[0].feedback_score == 0.99

    def test_different_agents_separate_groups(self, trace_store: TraceStore) -> None:
        trace_store.save(
            _make_trace(trace_id="t1", query="Hello", agent="simple", feedback=0.9),
        )
        trace_store.save(
            _make_trace(
                trace_id="t2",
                query="Hello",
                agent="orchestrator",
                feedback=0.8,
            )
        )
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize()
        assert len(bm.samples) == 2

    def test_max_samples_limit(self, trace_store: TraceStore) -> None:
        for i in range(10):
            trace_store.save(
                _make_trace(
                    trace_id=f"t{i}",
                    query=f"Unique question number {i}",
                    feedback=0.8 + i * 0.01,
                ),
            )
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize(max_samples=3)
        assert len(bm.samples) == 3

    def test_empty_traces_returns_empty_benchmark(
        self,
        trace_store: TraceStore,
    ) -> None:
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize()
        assert bm.samples == []
        assert bm.workflow_id == "default"

    def test_category_inferred_from_agent(self, trace_store: TraceStore) -> None:
        trace_store.save(
            _make_trace(trace_id="t1", agent="orchestrator", feedback=0.9),
        )
        trace_store.save(
            _make_trace(
                trace_id="t2",
                query="Different query",
                agent="simple",
                feedback=0.9,
            ),
        )
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize()
        categories = {s.agent: s.category for s in bm.samples}
        assert categories["orchestrator"] == "agentic"
        assert categories["simple"] == "chat"

    def test_samples_sorted_by_feedback_desc(self, trace_store: TraceStore) -> None:
        trace_store.save(
            _make_trace(trace_id="t1", query="Q1", feedback=0.75),
        )
        trace_store.save(
            _make_trace(trace_id="t2", query="Q2", feedback=0.95),
        )
        trace_store.save(
            _make_trace(trace_id="t3", query="Q3", feedback=0.85),
        )
        synth = PersonalBenchmarkSynthesizer(trace_store)
        bm = synth.synthesize(min_feedback=0.7)
        scores = [s.feedback_score for s in bm.samples]
        assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# PersonalBenchmarkDataset
# ---------------------------------------------------------------------------


class TestPersonalBenchmarkDataset:
    def _make_benchmark(self) -> PersonalBenchmark:
        return PersonalBenchmark(
            workflow_id="test",
            samples=[
                PersonalBenchmarkSample(
                    trace_id=f"t{i}",
                    query=f"Query {i}",
                    reference_answer=f"Answer {i}",
                    agent="simple",
                    category="chat",
                    feedback_score=0.9,
                )
                for i in range(5)
            ],
        )

    def test_load_creates_records(self) -> None:
        ds = PersonalBenchmarkDataset(self._make_benchmark())
        ds.load()
        assert ds.size() == 5

    def test_iter_records(self) -> None:
        ds = PersonalBenchmarkDataset(self._make_benchmark())
        ds.load()
        records = list(ds.iter_records())
        assert len(records) == 5
        assert all(isinstance(r, EvalRecord) for r in records)

    def test_record_fields_mapped(self) -> None:
        ds = PersonalBenchmarkDataset(self._make_benchmark())
        ds.load()
        rec = list(ds.iter_records())[0]
        assert rec.record_id == "t0"
        assert rec.problem == "Query 0"
        assert rec.reference == "Answer 0"
        assert rec.category == "chat"
        assert rec.subject == "simple"

    def test_max_samples(self) -> None:
        ds = PersonalBenchmarkDataset(self._make_benchmark())
        ds.load(max_samples=2)
        assert ds.size() == 2

    def test_size_before_load(self) -> None:
        ds = PersonalBenchmarkDataset(self._make_benchmark())
        assert ds.size() == 0

    def test_dataset_id_and_name(self) -> None:
        ds = PersonalBenchmarkDataset(self._make_benchmark())
        assert ds.dataset_id == "personal"
        assert ds.dataset_name == "Personal Benchmark"

    def test_empty_benchmark(self) -> None:
        bm = PersonalBenchmark(workflow_id="empty")
        ds = PersonalBenchmarkDataset(bm)
        ds.load()
        assert ds.size() == 0
        assert list(ds.iter_records()) == []

    def test_subject_defaults_to_general(self) -> None:
        bm = PersonalBenchmark(
            workflow_id="test",
            samples=[
                PersonalBenchmarkSample(
                    trace_id="t1",
                    query="q",
                    reference_answer="a",
                    agent="",  # empty agent
                ),
            ],
        )
        ds = PersonalBenchmarkDataset(bm)
        ds.load()
        rec = list(ds.iter_records())[0]
        assert rec.subject == "general"


# ---------------------------------------------------------------------------
# PersonalBenchmarkScorer
# ---------------------------------------------------------------------------


class TestPersonalBenchmarkScorer:
    def _make_scorer(self, judge_response: str) -> PersonalBenchmarkScorer:
        backend = MagicMock()
        backend.generate.return_value = judge_response
        return PersonalBenchmarkScorer(backend, "judge-model")

    def _make_record(self) -> EvalRecord:
        return EvalRecord(
            record_id="r1",
            problem="What is 2+2?",
            reference="4",
            category="chat",
        )

    def test_score_yes(self) -> None:
        scorer = self._make_scorer("YES\nThe answer is correct.")
        is_correct, meta = scorer.score(self._make_record(), "4")
        assert is_correct is True
        assert "judge_response" in meta

    def test_score_no(self) -> None:
        scorer = self._make_scorer("NO\nThe answer is incorrect.")
        is_correct, meta = scorer.score(self._make_record(), "5")
        assert is_correct is False
        assert "judge_response" in meta

    def test_score_yes_case_insensitive(self) -> None:
        scorer = self._make_scorer("yes, the answer is good")
        is_correct, _ = scorer.score(self._make_record(), "4")
        assert is_correct is True

    def test_score_no_multiline(self) -> None:
        scorer = self._make_scorer("NO\nLine2\nLine3")
        is_correct, _ = scorer.score(self._make_record(), "wrong")
        assert is_correct is False

    def test_judge_receives_prompt_with_query_and_reference(self) -> None:
        backend = MagicMock()
        backend.generate.return_value = "YES"
        scorer = PersonalBenchmarkScorer(backend, "judge-model")
        record = self._make_record()
        scorer.score(record, "4")
        call_args = backend.generate.call_args
        prompt = call_args[0][0]
        assert "What is 2+2?" in prompt
        assert "4" in prompt  # reference

    def test_scorer_id(self) -> None:
        scorer = self._make_scorer("YES")
        assert scorer.scorer_id == "personal_judge"

    def test_score_empty_response_treated_as_no(self) -> None:
        scorer = self._make_scorer("")
        is_correct, _ = scorer.score(self._make_record(), "4")
        assert is_correct is False
