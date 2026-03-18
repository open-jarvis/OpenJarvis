"""Tests for openjarvis.optimize.feedback.collector module."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.core.types import Trace
from openjarvis.optimize.feedback.collector import FeedbackCollector
from openjarvis.optimize.feedback.judge import TraceJudge


def _make_trace(trace_id: str = "trace-001") -> Trace:
    return Trace(trace_id=trace_id, query="Hello", result="Hi there")


# ---------------------------------------------------------------------------
# record_explicit
# ---------------------------------------------------------------------------


class TestRecordExplicit:
    """FeedbackCollector.record_explicit stores records."""

    def test_stores_record(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.8)
        records = fc.get_records()
        assert len(records) == 1
        assert records[0]["trace_id"] == "t1"
        assert records[0]["score"] == 0.8
        assert records[0]["source"] == "api"

    def test_custom_source(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.5, source="human")
        assert fc.get_records()[0]["source"] == "human"

    def test_clamps_score_above_one(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 1.5)
        assert fc.get_records()[0]["score"] == 1.0

    def test_clamps_score_below_zero(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", -0.5)
        assert fc.get_records()[0]["score"] == 0.0

    def test_has_timestamp(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.7)
        assert "timestamp" in fc.get_records()[0]
        assert fc.get_records()[0]["timestamp"] > 0

    def test_multiple_records(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.5)
        fc.record_explicit("t2", 0.9)
        assert len(fc.get_records()) == 2


# ---------------------------------------------------------------------------
# record_thumbs
# ---------------------------------------------------------------------------


class TestRecordThumbs:
    """FeedbackCollector.record_thumbs converts boolean to score."""

    def test_thumbs_up_is_one(self) -> None:
        fc = FeedbackCollector()
        fc.record_thumbs("t1", thumbs_up=True)
        assert fc.get_records()[0]["score"] == 1.0

    def test_thumbs_down_is_zero(self) -> None:
        fc = FeedbackCollector()
        fc.record_thumbs("t1", thumbs_up=False)
        assert fc.get_records()[0]["score"] == 0.0

    def test_source_is_thumbs(self) -> None:
        fc = FeedbackCollector()
        fc.record_thumbs("t1", thumbs_up=True)
        assert fc.get_records()[0]["source"] == "thumbs"


# ---------------------------------------------------------------------------
# evaluate_traces
# ---------------------------------------------------------------------------


class TestEvaluateTraces:
    """FeedbackCollector.evaluate_traces uses the judge."""

    def test_returns_new_records(self) -> None:
        backend = MagicMock()
        backend.generate.return_value = "Score: 0.85\nGood"
        judge = TraceJudge(backend=backend, model="m")

        fc = FeedbackCollector()
        traces = [_make_trace("t1"), _make_trace("t2")]
        new = fc.evaluate_traces(traces, judge)

        assert len(new) == 2
        assert new[0]["trace_id"] == "t1"
        assert new[1]["trace_id"] == "t2"

    def test_records_stored_internally(self) -> None:
        backend = MagicMock()
        backend.generate.return_value = "0.7\nOk"
        judge = TraceJudge(backend=backend, model="m")

        fc = FeedbackCollector()
        fc.evaluate_traces([_make_trace("t1")], judge)

        assert len(fc.get_records()) == 1
        assert fc.get_records()[0]["source"] == "judge"

    def test_record_has_feedback_text(self) -> None:
        backend = MagicMock()
        backend.generate.return_value = "Score: 0.6\nNeeds improvement"
        judge = TraceJudge(backend=backend, model="m")

        fc = FeedbackCollector()
        fc.evaluate_traces([_make_trace()], judge)

        record = fc.get_records()[0]
        assert "feedback" in record
        assert "Needs improvement" in record["feedback"]

    def test_empty_traces_returns_empty(self) -> None:
        judge = MagicMock(spec=TraceJudge)
        fc = FeedbackCollector()
        result = fc.evaluate_traces([], judge)
        assert result == []


# ---------------------------------------------------------------------------
# get_records
# ---------------------------------------------------------------------------


class TestGetRecords:
    """FeedbackCollector.get_records filters by trace_id."""

    def test_all_records_when_no_filter(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.5)
        fc.record_explicit("t2", 0.8)
        assert len(fc.get_records()) == 2

    def test_filter_by_trace_id(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.5)
        fc.record_explicit("t2", 0.8)
        fc.record_explicit("t1", 0.9)

        records = fc.get_records(trace_id="t1")
        assert len(records) == 2
        assert all(r["trace_id"] == "t1" for r in records)

    def test_filter_returns_empty_for_unknown_id(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.5)
        assert fc.get_records(trace_id="unknown") == []

    def test_returns_copies(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.5)
        records = fc.get_records()
        records.clear()
        assert len(fc.get_records()) == 1


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestStats:
    """FeedbackCollector.stats returns aggregate statistics."""

    def test_empty_stats(self) -> None:
        fc = FeedbackCollector()
        s = fc.stats()
        assert s["count"] == 0
        assert s["mean_score"] == 0.0
        assert s["distribution"] == {"low": 0, "medium": 0, "high": 0}

    def test_count(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.5)
        fc.record_explicit("t2", 0.9)
        assert fc.stats()["count"] == 2

    def test_mean_score(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.4)
        fc.record_explicit("t2", 0.8)
        assert abs(fc.stats()["mean_score"] - 0.6) < 1e-6

    def test_distribution_low(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.1)
        fc.record_explicit("t2", 0.2)
        s = fc.stats()
        assert s["distribution"]["low"] == 2
        assert s["distribution"]["medium"] == 0
        assert s["distribution"]["high"] == 0

    def test_distribution_medium(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.5)
        fc.record_explicit("t2", 0.6)
        s = fc.stats()
        assert s["distribution"]["medium"] == 2

    def test_distribution_high(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("t1", 0.8)
        fc.record_explicit("t2", 1.0)
        s = fc.stats()
        assert s["distribution"]["high"] == 2

    def test_distribution_mixed(self) -> None:
        fc = FeedbackCollector()
        fc.record_explicit("a", 0.1)  # low
        fc.record_explicit("b", 0.5)  # medium
        fc.record_explicit("c", 0.9)  # high
        s = fc.stats()
        assert s["distribution"]["low"] == 1
        assert s["distribution"]["medium"] == 1
        assert s["distribution"]["high"] == 1

    def test_stats_with_thumbs(self) -> None:
        fc = FeedbackCollector()
        fc.record_thumbs("t1", thumbs_up=True)
        fc.record_thumbs("t2", thumbs_up=False)
        s = fc.stats()
        assert s["count"] == 2
        assert abs(s["mean_score"] - 0.5) < 1e-6
