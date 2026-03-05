"""Smoke tests for ``jarvis optimize`` and ``jarvis feedback`` CLI commands,
plus unit tests for OptimizeConfig, new event types, and TraceStore.update_feedback.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli


class TestOptimizeCmd:
    """CLI smoke tests for the optimize command group."""

    def test_optimize_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["optimize", "--help"])
        assert result.exit_code == 0
        assert "optimization" in result.output.lower()

    def test_optimize_run_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["optimize", "run", "--help"])
        assert result.exit_code == 0
        assert "--benchmark" in result.output
        assert "--trials" in result.output
        assert "--optimizer-model" in result.output
        assert "--max-samples" in result.output
        assert "--output-dir" in result.output

    def test_optimize_status_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["optimize", "status", "--help"])
        assert result.exit_code == 0
        assert "status" in result.output.lower()

    def test_optimize_results_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["optimize", "results", "--help"])
        assert result.exit_code == 0
        assert "RUN_ID" in result.output

    def test_optimize_best_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["optimize", "best", "--help"])
        assert result.exit_code == 0
        assert "RUN_ID" in result.output
        assert "--output" in result.output

    def test_optimize_personal_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["optimize", "personal", "--help"])
        assert result.exit_code == 0
        assert "synthesize" in result.output
        assert "--workflow" in result.output


class TestFeedbackCmd:
    """CLI smoke tests for the feedback command group."""

    def test_feedback_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["feedback", "--help"])
        assert result.exit_code == 0
        assert "feedback" in result.output.lower()

    def test_feedback_score_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["feedback", "score", "--help"])
        assert result.exit_code == 0
        assert "TRACE_ID" in result.output
        assert "--score" in result.output

    def test_feedback_thumbs_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["feedback", "thumbs", "--help"])
        assert result.exit_code == 0
        assert "--last" in result.output
        assert "--up" in result.output

    def test_feedback_evaluate_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["feedback", "evaluate", "--help"])
        assert result.exit_code == 0
        assert "--since" in result.output

    def test_feedback_stats_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["feedback", "stats", "--help"])
        assert result.exit_code == 0


class TestOptimizeConfig:
    """Tests for OptimizeConfig in JarvisConfig."""

    def test_optimize_config_in_jarvis_config(self):
        from openjarvis.core.config import JarvisConfig, OptimizeConfig

        cfg = JarvisConfig()
        assert isinstance(cfg.optimize, OptimizeConfig)
        assert cfg.optimize.max_trials == 20
        assert cfg.optimize.early_stop_patience == 5
        assert cfg.optimize.optimizer_model == "claude-sonnet-4-6"
        assert cfg.optimize.optimizer_provider == "anthropic"
        assert cfg.optimize.benchmark == ""
        assert cfg.optimize.max_samples == 50

    def test_optimize_config_defaults(self):
        from openjarvis.core.config import OptimizeConfig

        cfg = OptimizeConfig()
        assert cfg.max_trials == 20
        assert cfg.early_stop_patience == 5
        assert cfg.optimizer_model == "claude-sonnet-4-6"
        assert cfg.judge_model == "gpt-5-mini-2025-08-07"


class TestNewEventTypes:
    """Tests for new event types added in Phase 25."""

    def test_optimize_event_types_exist(self):
        from openjarvis.core.events import EventType

        assert EventType.OPTIMIZE_RUN_START == "optimize_run_start"
        assert EventType.OPTIMIZE_TRIAL_START == "optimize_trial_start"
        assert EventType.OPTIMIZE_TRIAL_END == "optimize_trial_end"
        assert EventType.OPTIMIZE_RUN_END == "optimize_run_end"

    def test_feedback_event_type_exists(self):
        from openjarvis.core.events import EventType

        assert EventType.FEEDBACK_RECEIVED == "feedback_received"


class TestTraceStoreUpdateFeedback:
    """Tests for TraceStore.update_feedback."""

    def test_update_feedback_success(self, tmp_path):
        from openjarvis.core.types import Trace
        from openjarvis.traces.store import TraceStore

        store = TraceStore(tmp_path / "traces.db")
        trace = Trace(trace_id="test123", query="hello")
        store.save(trace)

        assert store.update_feedback("test123", 0.9)
        updated = store.get("test123")
        assert updated is not None
        assert updated.feedback == pytest.approx(0.9)
        store.close()

    def test_update_feedback_nonexistent(self, tmp_path):
        from openjarvis.traces.store import TraceStore

        store = TraceStore(tmp_path / "traces.db")
        assert not store.update_feedback("nonexistent", 0.5)
        store.close()

    def test_update_feedback_overwrite(self, tmp_path):
        from openjarvis.core.types import Trace
        from openjarvis.traces.store import TraceStore

        store = TraceStore(tmp_path / "traces.db")
        trace = Trace(trace_id="test456", query="test", feedback=0.3)
        store.save(trace)

        assert store.update_feedback("test456", 0.8)
        updated = store.get("test456")
        assert updated is not None
        assert updated.feedback == pytest.approx(0.8)
        store.close()
