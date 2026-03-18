"""Tests for eval result trackers (W&B + Google Sheets)."""

from __future__ import annotations

import sys
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.evals.core.tracker import ResultTracker
from openjarvis.evals.core.types import EvalResult, RunConfig, RunSummary

# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


class RecordingTracker(ResultTracker):
    """Records all lifecycle calls for testing."""

    def __init__(self) -> None:
        self.calls: List[str] = []
        self.results: List[EvalResult] = []
        self.summary: RunSummary | None = None

    def on_run_start(self, config: RunConfig) -> None:
        self.calls.append("on_run_start")

    def on_result(self, result: EvalResult, config: RunConfig) -> None:
        self.calls.append("on_result")
        self.results.append(result)

    def on_summary(self, summary: RunSummary) -> None:
        self.calls.append("on_summary")
        self.summary = summary

    def on_run_end(self) -> None:
        self.calls.append("on_run_end")


class CrashingTracker(ResultTracker):
    """Raises on every lifecycle call."""

    def on_run_start(self, config: RunConfig) -> None:
        raise RuntimeError("boom start")

    def on_result(self, result: EvalResult, config: RunConfig) -> None:
        raise RuntimeError("boom result")

    def on_summary(self, summary: RunSummary) -> None:
        raise RuntimeError("boom summary")

    def on_run_end(self) -> None:
        raise RuntimeError("boom end")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> RunConfig:
    defaults = dict(benchmark="test", backend="jarvis-direct", model="test-model")
    defaults.update(overrides)
    return RunConfig(**defaults)


def _make_summary(**overrides) -> RunSummary:
    defaults = dict(
        benchmark="test",
        category="chat",
        backend="jarvis-direct",
        model="test-model",
        total_samples=10,
        scored_samples=10,
        correct=8,
        accuracy=0.8,
        errors=0,
        mean_latency_seconds=1.0,
        total_cost_usd=0.01,
    )
    defaults.update(overrides)
    return RunSummary(**defaults)


def _make_result(**overrides) -> EvalResult:
    defaults = dict(record_id="r1", model_answer="answer", is_correct=True)
    defaults.update(overrides)
    return EvalResult(**defaults)


# ---------------------------------------------------------------------------
# RecordingTracker through EvalRunner lifecycle
# ---------------------------------------------------------------------------


class TestRecordingTrackerIntegration:
    """Test that trackers receive all lifecycle calls through EvalRunner."""

    def test_tracker_lifecycle(self, tmp_path):
        """RecordingTracker receives start, result, summary, end calls."""
        from openjarvis.evals.core.runner import EvalRunner

        # Minimal stubs
        dataset = MagicMock(spec=["load", "iter_records"])
        record = MagicMock()
        record.record_id = "r1"
        record.problem = "What is 1+1?"
        record.reference = "2"
        record.category = "chat"
        record.subject = ""
        dataset.load = MagicMock()
        dataset.iter_records = MagicMock(return_value=[record])

        backend = MagicMock()
        backend.generate_full = MagicMock(
            return_value={
                "content": "2",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "latency_seconds": 0.5,
            }
        )

        scorer = MagicMock()
        scorer.score = MagicMock(return_value=(True, {}))

        tracker = RecordingTracker()
        config = _make_config(output_path=str(tmp_path / "out.jsonl"))

        runner = EvalRunner(config, dataset, backend, scorer, trackers=[tracker])
        runner.run()

        assert "on_run_start" in tracker.calls
        assert "on_result" in tracker.calls
        assert "on_summary" in tracker.calls
        assert "on_run_end" in tracker.calls
        # Order matters
        assert tracker.calls.index("on_run_start") < tracker.calls.index("on_result")
        assert tracker.calls.index("on_result") < tracker.calls.index("on_summary")
        assert tracker.calls.index("on_summary") < tracker.calls.index("on_run_end")
        assert len(tracker.results) == 1
        assert tracker.summary is not None

    def test_crashing_tracker_does_not_abort(self, tmp_path):
        """A tracker that raises exceptions must not prevent JSONL output."""
        from openjarvis.evals.core.runner import EvalRunner

        dataset = MagicMock(spec=["load", "iter_records"])
        record = MagicMock()
        record.record_id = "r1"
        record.problem = "What?"
        record.reference = "yes"
        record.category = "chat"
        record.subject = ""
        dataset.load = MagicMock()
        dataset.iter_records = MagicMock(return_value=[record])

        backend = MagicMock()
        backend.generate_full = MagicMock(
            return_value={
                "content": "yes",
                "usage": {},
                "latency_seconds": 0.1,
            }
        )

        scorer = MagicMock()
        scorer.score = MagicMock(return_value=(True, {}))

        output = tmp_path / "out.jsonl"
        config = _make_config(output_path=str(output))

        crasher = CrashingTracker()
        runner = EvalRunner(config, dataset, backend, scorer, trackers=[crasher])
        summary = runner.run()

        # Run completed, JSONL written despite crashing tracker
        assert summary.total_samples == 1
        assert output.exists()
        assert output.read_text().strip() != ""


# ---------------------------------------------------------------------------
# WandbTracker unit tests
# ---------------------------------------------------------------------------


class TestWandbTracker:
    """Unit tests for WandbTracker (mocked wandb module)."""

    def test_import_error_when_wandb_missing(self):
        """WandbTracker raises ImportError when wandb is not installed."""
        with patch.dict(sys.modules, {"wandb": None}):
            import openjarvis.evals.trackers.wandb_tracker as wt_mod

            original = wt_mod.wandb
            wt_mod.wandb = None
            try:
                with pytest.raises(ImportError, match="wandb is not installed"):
                    wt_mod.WandbTracker(project="test")
            finally:
                wt_mod.wandb = original

    def test_on_result_calls_wandb_log(self):
        """on_result calls wandb.log with sample/ prefixed keys."""
        import openjarvis.evals.trackers.wandb_tracker as wt_mod

        mock_wandb = MagicMock()
        mock_run = MagicMock()
        mock_wandb.init = MagicMock(return_value=mock_run)
        original = wt_mod.wandb
        wt_mod.wandb = mock_wandb
        try:
            tracker = wt_mod.WandbTracker(project="test-proj")
            config = _make_config()
            tracker.on_run_start(config)

            result = _make_result(latency_seconds=0.5, energy_joules=1.0)
            tracker.on_result(result, config)

            mock_wandb.log.assert_called_once()
            call_args = mock_wandb.log.call_args
            log_data = call_args[0][0]
            assert "sample/is_correct" in log_data
            assert "sample/latency_seconds" in log_data
            assert log_data["sample/is_correct"] == 1.0
            assert call_args[1]["step"] == 1

            tracker.on_run_end()
        finally:
            wt_mod.wandb = original

    def test_on_summary_updates_run_summary(self):
        """on_summary calls wandb.run.summary.update with flat dict."""
        import openjarvis.evals.trackers.wandb_tracker as wt_mod

        mock_wandb = MagicMock()
        mock_run = MagicMock()
        mock_wandb.init = MagicMock(return_value=mock_run)
        mock_wandb.run = mock_run
        original = wt_mod.wandb
        wt_mod.wandb = mock_wandb
        try:
            tracker = wt_mod.WandbTracker(project="test-proj")
            config = _make_config()
            tracker.on_run_start(config)

            summary = _make_summary()
            tracker.on_summary(summary)

            mock_run.summary.update.assert_called_once()
            flat = mock_run.summary.update.call_args[0][0]
            assert flat["accuracy"] == 0.8
            assert flat["total_samples"] == 10

            tracker.on_run_end()
        finally:
            wt_mod.wandb = original

    def test_reinit_true_for_suite_mode(self):
        """wandb.init is called with reinit=True."""
        import openjarvis.evals.trackers.wandb_tracker as wt_mod

        mock_wandb = MagicMock()
        mock_run = MagicMock()
        mock_wandb.init = MagicMock(return_value=mock_run)
        original = wt_mod.wandb
        wt_mod.wandb = mock_wandb
        try:
            tracker = wt_mod.WandbTracker(project="test-proj", entity="team")
            config = _make_config()
            tracker.on_run_start(config)

            call_kwargs = mock_wandb.init.call_args[1]
            assert call_kwargs["reinit"] is True
            assert call_kwargs["project"] == "test-proj"
            assert call_kwargs["entity"] == "team"

            tracker.on_run_end()
        finally:
            wt_mod.wandb = original


# ---------------------------------------------------------------------------
# SheetsTracker unit tests
# ---------------------------------------------------------------------------


class TestSheetsTracker:
    """Unit tests for SheetsTracker."""

    def test_import_error_when_gspread_missing(self):
        """SheetsTracker raises ImportError when gspread not installed."""
        import openjarvis.evals.trackers.sheets_tracker as st_mod

        original = st_mod.gspread
        st_mod.gspread = None
        try:
            with pytest.raises(ImportError, match="gspread is not installed"):
                st_mod.SheetsTracker(spreadsheet_id="abc123")
        finally:
            st_mod.gspread = original

    def test_on_result_is_noop(self):
        """on_result does nothing (no API calls for individual samples)."""
        import openjarvis.evals.trackers.sheets_tracker as st_mod

        mock_gspread = MagicMock()
        original = st_mod.gspread
        st_mod.gspread = mock_gspread
        original_creds = st_mod.Credentials
        st_mod.Credentials = MagicMock()
        try:
            tracker = st_mod.SheetsTracker(spreadsheet_id="abc123")
            result = _make_result()
            config = _make_config()

            # on_result should not call any external API
            tracker.on_result(result, config)
            mock_gspread.authorize.assert_not_called()
        finally:
            st_mod.gspread = original
            st_mod.Credentials = original_creds

    def test_build_row_matches_columns(self):
        """_build_row returns a list matching SHEET_COLUMNS length."""
        import openjarvis.evals.trackers.sheets_tracker as st_mod

        mock_gspread = MagicMock()
        original = st_mod.gspread
        st_mod.gspread = mock_gspread
        original_creds = st_mod.Credentials
        st_mod.Credentials = MagicMock()
        try:
            tracker = st_mod.SheetsTracker(spreadsheet_id="abc123")
            summary = _make_summary()
            row = tracker._build_row(summary)
            assert len(row) == len(st_mod.SHEET_COLUMNS), (
                f"Row length {len(row)} != columns length {len(st_mod.SHEET_COLUMNS)}"
            )
        finally:
            st_mod.gspread = original
            st_mod.Credentials = original_creds
