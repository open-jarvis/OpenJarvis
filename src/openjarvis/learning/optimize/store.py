"""SQLite-backed storage for optimization runs and trials."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from openjarvis.learning.optimize.types import (
    BenchmarkScore,
    OptimizationRun,
    SampleScore,
    SearchSpace,
    TrialConfig,
    TrialFeedback,
    TrialResult,
)

logger = logging.getLogger(__name__)

_CREATE_RUNS = """\
CREATE TABLE IF NOT EXISTS optimization_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    search_space TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'running',
    optimizer_model TEXT NOT NULL DEFAULT '',
    benchmark TEXT NOT NULL DEFAULT '',
    best_trial_id TEXT,
    best_recipe_path TEXT,
    created_at REAL NOT NULL DEFAULT 0.0,
    updated_at REAL NOT NULL DEFAULT 0.0
);
"""

_CREATE_TRIALS = """\
CREATE TABLE IF NOT EXISTS trial_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trial_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    reasoning TEXT NOT NULL DEFAULT '',
    accuracy REAL NOT NULL DEFAULT 0.0,
    mean_latency_seconds REAL NOT NULL DEFAULT 0.0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    total_energy_joules REAL NOT NULL DEFAULT 0.0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    samples_evaluated INTEGER NOT NULL DEFAULT 0,
    analysis TEXT NOT NULL DEFAULT '',
    failure_modes TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY (run_id) REFERENCES optimization_runs(run_id)
);
"""

_INSERT_RUN = """\
INSERT OR REPLACE INTO optimization_runs (
    run_id, search_space, status, optimizer_model, benchmark,
    best_trial_id, best_recipe_path, created_at, updated_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_INSERT_TRIAL = """\
INSERT OR REPLACE INTO trial_results (
    trial_id, run_id, config, reasoning, accuracy,
    mean_latency_seconds, total_cost_usd, total_energy_joules,
    total_tokens, samples_evaluated, analysis, failure_modes,
    created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


_MIGRATE_TRIALS = [
    "ALTER TABLE trial_results ADD COLUMN sample_scores TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE trial_results ADD COLUMN "
    "structured_feedback TEXT NOT NULL DEFAULT '{}'",
    "ALTER TABLE trial_results ADD COLUMN per_benchmark TEXT NOT NULL DEFAULT '[]'",
]

_MIGRATE_RUNS = [
    "ALTER TABLE optimization_runs ADD COLUMN "
    "pareto_frontier_ids TEXT NOT NULL DEFAULT '[]'",
    "ALTER TABLE optimization_runs ADD COLUMN benchmarks TEXT NOT NULL DEFAULT '[]'",
]


class OptimizationStore:
    """SQLite-backed storage for optimization runs and trials."""

    def __init__(self, db_path: Union[str, Path]) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_RUNS)
        self._conn.execute(_CREATE_TRIALS)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Add new columns to existing databases gracefully."""
        for stmt in _MIGRATE_TRIALS + _MIGRATE_RUNS:
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # Column already exists — safe to ignore
        self._conn.commit()

    # ------------------------------------------------------------------
    # Runs
    # ------------------------------------------------------------------

    def save_run(self, run: OptimizationRun) -> None:
        """Persist an optimization run (insert or update)."""
        now = time.time()
        search_space_json = self._search_space_to_json(run.search_space)
        best_trial_id = run.best_trial.trial_id if run.best_trial else None
        pareto_ids = json.dumps([t.trial_id for t in run.pareto_frontier])
        self._conn.execute(
            _INSERT_RUN,
            (
                run.run_id,
                search_space_json,
                run.status,
                run.optimizer_model,
                run.benchmark,
                best_trial_id,
                run.best_recipe_path,
                now,
                now,
            ),
        )
        benchmarks_json = json.dumps(run.benchmarks)
        # Update pareto_frontier_ids and benchmarks separately
        self._conn.execute(
            "UPDATE optimization_runs SET pareto_frontier_ids = ?, "
            "benchmarks = ? WHERE run_id = ?",
            (pareto_ids, benchmarks_json, run.run_id),
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> Optional[OptimizationRun]:
        """Retrieve an optimization run by id, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM optimization_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return summary dicts of recent optimization runs."""
        rows = self._conn.execute(
            "SELECT * FROM optimization_runs ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "run_id": row[1],
                    "status": row[3],
                    "optimizer_model": row[4],
                    "benchmark": row[5],
                    "best_trial_id": row[6],
                    "best_recipe_path": row[7],
                    "created_at": row[8],
                    "updated_at": row[9],
                }
            )
        return result

    # ------------------------------------------------------------------
    # Trials
    # ------------------------------------------------------------------

    def save_trial(self, run_id: str, trial: TrialResult) -> None:
        """Persist a single trial result."""
        now = time.time()
        # Serialize sample_scores
        scores_json = json.dumps(
            [
                {
                    "record_id": s.record_id,
                    "is_correct": s.is_correct,
                    "score": s.score,
                    "latency_seconds": s.latency_seconds,
                    "prompt_tokens": s.prompt_tokens,
                    "completion_tokens": s.completion_tokens,
                    "cost_usd": s.cost_usd,
                    "error": s.error,
                    "ttft": s.ttft,
                    "energy_joules": s.energy_joules,
                    "power_watts": s.power_watts,
                    "gpu_utilization_pct": s.gpu_utilization_pct,
                    "throughput_tok_per_sec": s.throughput_tok_per_sec,
                    "mfu_pct": s.mfu_pct,
                    "mbu_pct": s.mbu_pct,
                    "ipw": s.ipw,
                    "ipj": s.ipj,
                    "energy_per_output_token_joules": s.energy_per_output_token_joules,
                    "throughput_per_watt": s.throughput_per_watt,
                    "mean_itl_ms": s.mean_itl_ms,
                }
                for s in trial.sample_scores
            ]
        )
        # Serialize structured_feedback
        fb = trial.structured_feedback
        fb_json = (
            json.dumps(
                {
                    "summary_text": fb.summary_text,
                    "failure_patterns": fb.failure_patterns,
                    "primitive_ratings": fb.primitive_ratings,
                    "suggested_changes": fb.suggested_changes,
                    "target_primitive": fb.target_primitive,
                }
            )
            if fb
            else "{}"
        )

        self._conn.execute(
            _INSERT_TRIAL,
            (
                trial.trial_id,
                run_id,
                json.dumps(trial.config.params),
                trial.config.reasoning,
                trial.accuracy,
                trial.mean_latency_seconds,
                trial.total_cost_usd,
                trial.total_energy_joules,
                trial.total_tokens,
                trial.samples_evaluated,
                trial.analysis,
                json.dumps(trial.failure_modes),
                now,
            ),
        )
        # Serialize per_benchmark
        pb_json = json.dumps(
            [
                {
                    "benchmark": b.benchmark,
                    "accuracy": b.accuracy,
                    "mean_latency_seconds": b.mean_latency_seconds,
                    "total_cost_usd": b.total_cost_usd,
                    "total_energy_joules": b.total_energy_joules,
                    "total_tokens": b.total_tokens,
                    "samples_evaluated": b.samples_evaluated,
                    "errors": b.errors,
                    "weight": b.weight,
                }
                for b in trial.per_benchmark
            ]
        )

        # Update new columns separately
        self._conn.execute(
            "UPDATE trial_results SET sample_scores = ?, "
            "structured_feedback = ?, per_benchmark = ? "
            "WHERE trial_id = ? AND run_id = ?",
            (scores_json, fb_json, pb_json, trial.trial_id, run_id),
        )
        self._conn.commit()

    def get_trials(self, run_id: str) -> List[TrialResult]:
        """Retrieve all trial results for a given run."""
        rows = self._conn.execute(
            "SELECT * FROM trial_results WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [self._row_to_trial(r) for r in rows]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _search_space_to_json(space: SearchSpace) -> str:
        """Serialize a SearchSpace to JSON."""
        dims = []
        for d in space.dimensions:
            dims.append(
                {
                    "name": d.name,
                    "dim_type": d.dim_type,
                    "values": d.values,
                    "low": d.low,
                    "high": d.high,
                    "description": d.description,
                    "primitive": d.primitive,
                }
            )
        return json.dumps(
            {
                "dimensions": dims,
                "fixed": space.fixed,
                "constraints": space.constraints,
            }
        )

    @staticmethod
    def _json_to_search_space(raw: str) -> SearchSpace:
        """Deserialize a SearchSpace from JSON."""
        from openjarvis.learning.optimize.types import SearchDimension

        data = json.loads(raw)
        dims = []
        for d in data.get("dimensions", []):
            dims.append(
                SearchDimension(
                    name=d.get("name", ""),
                    dim_type=d.get("dim_type", "categorical"),
                    values=d.get("values", []),
                    low=d.get("low"),
                    high=d.get("high"),
                    description=d.get("description", ""),
                    primitive=d.get("primitive", ""),
                )
            )
        return SearchSpace(
            dimensions=dims,
            fixed=data.get("fixed", {}),
            constraints=data.get("constraints", []),
        )

    def _row_to_run(self, row: tuple) -> OptimizationRun:
        """Convert a database row to an OptimizationRun."""
        run_id = row[1]
        search_space = self._json_to_search_space(row[2])
        status = row[3]
        optimizer_model = row[4]
        benchmark = row[5]
        best_trial_id = row[6]
        best_recipe_path = row[7]

        # Load trials for this run
        trials = self.get_trials(run_id)

        # Find the best trial
        best_trial: Optional[TrialResult] = None
        if best_trial_id:
            for t in trials:
                if t.trial_id == best_trial_id:
                    best_trial = t
                    break

        # Reconstruct benchmarks list
        benchmarks: List[str] = []
        if len(row) > 11:
            try:
                benchmarks = json.loads(row[11]) if row[11] else []
            except (json.JSONDecodeError, TypeError) as exc:
                logger.debug("Failed to parse stored JSON: %s", exc)

        # Reconstruct pareto frontier from IDs
        pareto_frontier: List[TrialResult] = []
        if len(row) > 10:
            try:
                frontier_ids = json.loads(row[10]) if row[10] else []
                trial_map = {t.trial_id: t for t in trials}
                pareto_frontier = [
                    trial_map[tid] for tid in frontier_ids if tid in trial_map
                ]
            except (json.JSONDecodeError, TypeError) as exc:
                logger.debug("Failed to parse stored JSON: %s", exc)

        return OptimizationRun(
            run_id=run_id,
            search_space=search_space,
            trials=trials,
            best_trial=best_trial,
            best_recipe_path=best_recipe_path,
            status=status,
            optimizer_model=optimizer_model,
            benchmark=benchmark,
            benchmarks=benchmarks,
            pareto_frontier=pareto_frontier,
        )

    @staticmethod
    def _row_to_trial(row: tuple) -> TrialResult:
        """Convert a database row to a TrialResult."""
        trial_id = row[1]
        # row[2] = run_id (not stored on TrialResult)
        params = json.loads(row[3])
        reasoning = row[4]
        accuracy = row[5]
        mean_latency = row[6]
        cost = row[7]
        energy = row[8]
        tokens = row[9]
        samples = row[10]
        analysis = row[11]
        failure_modes = json.loads(row[12])
        # row[13] = created_at

        # New columns (may be absent in old DBs)
        sample_scores: List[SampleScore] = []
        structured_feedback: Optional[TrialFeedback] = None

        if len(row) > 14:
            try:
                raw_scores = json.loads(row[14]) if row[14] else []
                sample_scores = [
                    SampleScore(
                        record_id=s.get("record_id", ""),
                        is_correct=s.get("is_correct"),
                        score=s.get("score"),
                        latency_seconds=s.get("latency_seconds", 0.0),
                        prompt_tokens=s.get("prompt_tokens", 0),
                        completion_tokens=s.get("completion_tokens", 0),
                        cost_usd=s.get("cost_usd", 0.0),
                        error=s.get("error"),
                        ttft=s.get("ttft", 0.0),
                        energy_joules=s.get("energy_joules", 0.0),
                        power_watts=s.get("power_watts", 0.0),
                        gpu_utilization_pct=s.get("gpu_utilization_pct", 0.0),
                        throughput_tok_per_sec=s.get("throughput_tok_per_sec", 0.0),
                        mfu_pct=s.get("mfu_pct", 0.0),
                        mbu_pct=s.get("mbu_pct", 0.0),
                        ipw=s.get("ipw", 0.0),
                        ipj=s.get("ipj", 0.0),
                        energy_per_output_token_joules=s.get(
                            "energy_per_output_token_joules",
                            0.0,
                        ),
                        throughput_per_watt=s.get("throughput_per_watt", 0.0),
                        mean_itl_ms=s.get("mean_itl_ms", 0.0),
                    )
                    for s in raw_scores
                ]
            except (json.JSONDecodeError, TypeError) as exc:
                logger.debug("Failed to parse stored JSON: %s", exc)

        if len(row) > 15:
            try:
                raw_fb = json.loads(row[15]) if row[15] else {}
                if raw_fb and raw_fb.get("summary_text", "") != "":
                    structured_feedback = TrialFeedback(
                        summary_text=raw_fb.get("summary_text", ""),
                        failure_patterns=raw_fb.get("failure_patterns", []),
                        primitive_ratings=raw_fb.get("primitive_ratings", {}),
                        suggested_changes=raw_fb.get("suggested_changes", []),
                        target_primitive=raw_fb.get("target_primitive", ""),
                    )
            except (json.JSONDecodeError, TypeError) as exc:
                logger.debug("Failed to parse stored JSON: %s", exc)

        # per_benchmark column
        per_benchmark: List[BenchmarkScore] = []
        if len(row) > 16:
            try:
                raw_pb = json.loads(row[16]) if row[16] else []
                per_benchmark = [
                    BenchmarkScore(
                        benchmark=b.get("benchmark", ""),
                        accuracy=b.get("accuracy", 0.0),
                        mean_latency_seconds=b.get("mean_latency_seconds", 0.0),
                        total_cost_usd=b.get("total_cost_usd", 0.0),
                        total_energy_joules=b.get("total_energy_joules", 0.0),
                        total_tokens=b.get("total_tokens", 0),
                        samples_evaluated=b.get("samples_evaluated", 0),
                        errors=b.get("errors", 0),
                        weight=b.get("weight", 1.0),
                    )
                    for b in raw_pb
                ]
            except (json.JSONDecodeError, TypeError) as exc:
                logger.debug("Failed to parse stored JSON: %s", exc)

        config = TrialConfig(
            trial_id=trial_id,
            params=params,
            reasoning=reasoning,
        )
        return TrialResult(
            trial_id=trial_id,
            config=config,
            accuracy=accuracy,
            mean_latency_seconds=mean_latency,
            total_cost_usd=cost,
            total_energy_joules=energy,
            total_tokens=tokens,
            samples_evaluated=samples,
            analysis=analysis,
            failure_modes=failure_modes,
            sample_scores=sample_scores,
            structured_feedback=structured_feedback,
            per_benchmark=per_benchmark,
        )


__all__ = ["OptimizationStore"]
