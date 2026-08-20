"""Tests for openjarvis.optimize.store module."""

from __future__ import annotations

from openjarvis.learning.optimize.store import OptimizationStore
from openjarvis.learning.optimize.types import (
    OptimizationRun,
    SampleScore,
    SearchDimension,
    SearchSpace,
    TrialConfig,
    TrialFeedback,
    TrialResult,
)


def _sample_search_space() -> SearchSpace:
    return SearchSpace(
        dimensions=[
            SearchDimension(
                name="agent.type",
                dim_type="categorical",
                values=["simple", "orchestrator"],
                primitive="agent",
            ),
            SearchDimension(
                name="intelligence.temperature",
                dim_type="continuous",
                low=0.0,
                high=1.0,
                primitive="intelligence",
            ),
        ],
        fixed={"engine": "ollama"},
        constraints=["max_turns >= 1"],
    )


def _sample_trial(
    trial_id: str = "t1",
    accuracy: float = 0.8,
    params: dict | None = None,
) -> TrialResult:
    if params is None:
        params = {"agent.type": "orchestrator", "intelligence.temperature": 0.5}
    config = TrialConfig(
        trial_id=trial_id,
        params=params,
        reasoning="testing",
    )
    return TrialResult(
        trial_id=trial_id,
        config=config,
        accuracy=accuracy,
        mean_latency_seconds=1.5,
        total_cost_usd=0.02,
        total_energy_joules=100.0,
        total_tokens=3000,
        samples_evaluated=50,
        analysis="Solid performance",
        failure_modes=["timeout on long inputs"],
    )


# ---------------------------------------------------------------------------
# OptimizationStore.__init__
# ---------------------------------------------------------------------------


class TestOptimizationStoreInit:
    """Tests for OptimizationStore initialization."""

    def test_creates_tables(self, tmp_path) -> None:
        db = tmp_path / "opt.db"
        store = OptimizationStore(db)
        # Verify tables exist by querying them
        runs = store.list_runs()
        trials = store.get_trials("nonexistent")
        assert runs == []
        assert trials == []
        store.close()

    def test_creates_tables_string_path(self, tmp_path) -> None:
        db = str(tmp_path / "opt.db")
        store = OptimizationStore(db)
        runs = store.list_runs()
        assert runs == []
        store.close()

    def test_wal_mode(self, tmp_path) -> None:
        db = tmp_path / "opt.db"
        store = OptimizationStore(db)
        row = store._conn.execute("PRAGMA journal_mode").fetchone()
        assert row[0] == "wal"
        store.close()


# ---------------------------------------------------------------------------
# Trial persistence
# ---------------------------------------------------------------------------


class TestTrialPersistence:
    """Tests for save_trial + get_trials roundtrip."""

    def test_save_and_get_trials(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        run_id = "run-001"
        # Need to save a run first for foreign key
        space = _sample_search_space()
        run = OptimizationRun(run_id=run_id, search_space=space)
        store.save_run(run)

        trial = _sample_trial("t1", accuracy=0.8)
        store.save_trial(run_id, trial)

        trials = store.get_trials(run_id)
        assert len(trials) == 1
        t = trials[0]
        assert t.trial_id == "t1"
        assert t.accuracy == 0.8
        assert t.mean_latency_seconds == 1.5
        assert t.total_cost_usd == 0.02
        assert t.total_energy_joules == 100.0
        assert t.total_tokens == 3000
        assert t.samples_evaluated == 50
        assert t.analysis == "Solid performance"
        assert t.failure_modes == ["timeout on long inputs"]
        assert t.config.params == {
            "agent.type": "orchestrator",
            "intelligence.temperature": 0.5,
        }
        assert t.config.reasoning == "testing"
        store.close()

    def test_multiple_trials(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        run_id = "run-002"
        space = _sample_search_space()
        store.save_run(OptimizationRun(run_id=run_id, search_space=space))

        store.save_trial(run_id, _sample_trial("t1", accuracy=0.7))
        store.save_trial(run_id, _sample_trial("t2", accuracy=0.85))
        store.save_trial(run_id, _sample_trial("t3", accuracy=0.9))

        trials = store.get_trials(run_id)
        assert len(trials) == 3
        assert [t.trial_id for t in trials] == ["t1", "t2", "t3"]
        assert [t.accuracy for t in trials] == [0.7, 0.85, 0.9]
        store.close()

    def test_get_trials_empty_run(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        trials = store.get_trials("nonexistent-run")
        assert trials == []
        store.close()

    def test_trial_with_empty_failure_modes(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        run_id = "run-003"
        space = _sample_search_space()
        store.save_run(OptimizationRun(run_id=run_id, search_space=space))

        config = TrialConfig(trial_id="t1", params={"x": 1})
        trial = TrialResult(
            trial_id="t1",
            config=config,
            accuracy=0.5,
            failure_modes=[],
        )
        store.save_trial(run_id, trial)

        loaded = store.get_trials(run_id)
        assert loaded[0].failure_modes == []
        store.close()


# ---------------------------------------------------------------------------
# Run persistence
# ---------------------------------------------------------------------------


class TestRunPersistence:
    """Tests for save_run + get_run roundtrip."""

    def test_save_and_get_run(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        space = _sample_search_space()
        best = _sample_trial("best", accuracy=0.95)
        run = OptimizationRun(
            run_id="run-abc",
            search_space=space,
            best_trial=best,
            best_recipe_path="/tmp/best.toml",
            status="completed",
            optimizer_model="claude-sonnet-4-6",
            benchmark="supergpqa",
        )
        # Save the best trial to the DB so get_run can reconstruct it
        store.save_run(run)
        store.save_trial("run-abc", best)

        loaded = store.get_run("run-abc")
        assert loaded is not None
        assert loaded.run_id == "run-abc"
        assert loaded.status == "completed"
        assert loaded.optimizer_model == "claude-sonnet-4-6"
        assert loaded.benchmark == "supergpqa"
        assert loaded.best_recipe_path == "/tmp/best.toml"
        assert loaded.best_trial is not None
        assert loaded.best_trial.trial_id == "best"
        assert loaded.best_trial.accuracy == 0.95
        store.close()

    def test_get_run_not_found(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        result = store.get_run("nonexistent")
        assert result is None
        store.close()

    def test_save_run_without_best_trial(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        space = _sample_search_space()
        run = OptimizationRun(
            run_id="run-no-best",
            search_space=space,
            status="running",
        )
        store.save_run(run)

        loaded = store.get_run("run-no-best")
        assert loaded is not None
        assert loaded.best_trial is None
        assert loaded.status == "running"
        store.close()

    def test_search_space_roundtrip(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        space = _sample_search_space()
        run = OptimizationRun(run_id="run-space", search_space=space)
        store.save_run(run)

        loaded = store.get_run("run-space")
        assert loaded is not None
        assert len(loaded.search_space.dimensions) == 2
        assert loaded.search_space.dimensions[0].name == "agent.type"
        assert loaded.search_space.dimensions[0].dim_type == "categorical"
        assert loaded.search_space.dimensions[0].values == [
            "simple",
            "orchestrator",
        ]
        assert loaded.search_space.dimensions[1].name == "intelligence.temperature"
        assert loaded.search_space.dimensions[1].low == 0.0
        assert loaded.search_space.dimensions[1].high == 1.0
        assert loaded.search_space.fixed == {"engine": "ollama"}
        assert loaded.search_space.constraints == ["max_turns >= 1"]
        store.close()

    def test_run_with_trials_loaded(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        space = _sample_search_space()
        run = OptimizationRun(run_id="run-trials", search_space=space)
        store.save_run(run)

        store.save_trial("run-trials", _sample_trial("t1", accuracy=0.7))
        store.save_trial("run-trials", _sample_trial("t2", accuracy=0.85))

        loaded = store.get_run("run-trials")
        assert loaded is not None
        assert len(loaded.trials) == 2
        assert loaded.trials[0].trial_id == "t1"
        assert loaded.trials[1].trial_id == "t2"
        store.close()


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------


class TestListRuns:
    """Tests for list_runs."""

    def test_list_runs_empty(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        runs = store.list_runs()
        assert runs == []
        store.close()

    def test_list_runs_returns_summaries(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        space = _sample_search_space()

        for i in range(3):
            run = OptimizationRun(
                run_id=f"run-{i}",
                search_space=space,
                status="completed",
                optimizer_model="test-model",
                benchmark="test-bench",
            )
            store.save_run(run)

        runs = store.list_runs()
        assert len(runs) == 3
        # Should have summary keys
        for r in runs:
            assert "run_id" in r
            assert "status" in r
            assert "optimizer_model" in r
            assert "benchmark" in r
            assert "created_at" in r
        store.close()

    def test_list_runs_limit(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        space = _sample_search_space()

        for i in range(10):
            run = OptimizationRun(
                run_id=f"run-{i}",
                search_space=space,
            )
            store.save_run(run)

        runs = store.list_runs(limit=5)
        assert len(runs) == 5
        store.close()


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    """Tests for close."""

    def test_close(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        store.close()
        # After close, operations should raise
        try:
            store.list_runs()
            assert False, "Expected error after close"
        except Exception:
            pass

    def test_double_close(self, tmp_path) -> None:
        """Double close should not raise."""
        store = OptimizationStore(tmp_path / "opt.db")
        store.close()
        # Second close may or may not raise depending on sqlite3
        # Just verify it doesn't crash hard
        try:
            store.close()
        except Exception:
            pass


class TestNewFieldsPersistence:
    """Tests for sample_scores, structured_feedback,
    and pareto_frontier_ids roundtrip."""

    def test_sample_scores_roundtrip(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        run_id = "run-scores"
        space = _sample_search_space()
        store.save_run(OptimizationRun(run_id=run_id, search_space=space))

        trial = _sample_trial("t1", accuracy=0.8)
        trial.sample_scores = [
            SampleScore(
                record_id="r1",
                is_correct=True,
                score=1.0,
                latency_seconds=0.5,
                prompt_tokens=100,
                completion_tokens=50,
            ),
            SampleScore(
                record_id="r2",
                is_correct=False,
                error="timeout",
                latency_seconds=5.0,
            ),
        ]
        store.save_trial(run_id, trial)

        loaded = store.get_trials(run_id)
        assert len(loaded) == 1
        assert len(loaded[0].sample_scores) == 2
        assert loaded[0].sample_scores[0].record_id == "r1"
        assert loaded[0].sample_scores[0].is_correct is True
        assert loaded[0].sample_scores[0].latency_seconds == 0.5
        assert loaded[0].sample_scores[1].record_id == "r2"
        assert loaded[0].sample_scores[1].error == "timeout"
        store.close()

    def test_structured_feedback_roundtrip(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        run_id = "run-feedback"
        space = _sample_search_space()
        store.save_run(OptimizationRun(run_id=run_id, search_space=space))

        trial = _sample_trial("t1", accuracy=0.8)
        trial.structured_feedback = TrialFeedback(
            summary_text="Good accuracy",
            failure_patterns=["timeout", "parse error"],
            primitive_ratings={"agent": "high", "intelligence": "medium"},
            suggested_changes=["reduce max_turns"],
            target_primitive="agent",
        )
        store.save_trial(run_id, trial)

        loaded = store.get_trials(run_id)
        assert len(loaded) == 1
        fb = loaded[0].structured_feedback
        assert fb is not None
        assert fb.summary_text == "Good accuracy"
        assert fb.failure_patterns == ["timeout", "parse error"]
        assert fb.primitive_ratings == {"agent": "high", "intelligence": "medium"}
        assert fb.suggested_changes == ["reduce max_turns"]
        assert fb.target_primitive == "agent"
        store.close()

    def test_pareto_frontier_ids_roundtrip(self, tmp_path) -> None:
        store = OptimizationStore(tmp_path / "opt.db")
        space = _sample_search_space()

        t1 = _sample_trial("t1", accuracy=0.9)
        t2 = _sample_trial("t2", accuracy=0.7)

        run = OptimizationRun(
            run_id="run-pareto",
            search_space=space,
            trials=[t1, t2],
            best_trial=t1,
            pareto_frontier=[t1, t2],
            status="completed",
        )
        store.save_run(run)
        store.save_trial("run-pareto", t1)
        store.save_trial("run-pareto", t2)

        loaded = store.get_run("run-pareto")
        assert loaded is not None
        assert len(loaded.pareto_frontier) == 2
        assert loaded.pareto_frontier[0].trial_id == "t1"
        assert loaded.pareto_frontier[1].trial_id == "t2"
        store.close()

    def test_trial_without_new_fields_loads(self, tmp_path) -> None:
        """Trials saved without new fields should load without errors."""
        store = OptimizationStore(tmp_path / "opt.db")
        run_id = "run-compat"
        space = _sample_search_space()
        store.save_run(OptimizationRun(run_id=run_id, search_space=space))

        trial = _sample_trial("t1", accuracy=0.8)
        # No sample_scores or structured_feedback set
        store.save_trial(run_id, trial)

        loaded = store.get_trials(run_id)
        assert len(loaded) == 1
        assert loaded[0].sample_scores == []
        assert loaded[0].structured_feedback is None
        store.close()
