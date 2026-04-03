"""Integration tests for the TerminalBench Native pipeline.

Validates the three bugs fixed in the native path:
  1. Dataset populates task_dir as a Path (not string).
  2. EvalRunner calls set_current_record() before generate_full().
  3. Scorer reads is_resolved from record.metadata correctly.

Docker and the terminal-bench package are NOT required — the Harness call is
mocked so the full pipeline (dataset → backend → scorer → EvalRunner) can be
exercised on any machine.
"""

from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# Skip entire module if terminal_bench isn't installed.
pytest.importorskip("terminal_bench", reason="terminal_bench not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_dir(tmp_path: Path, task_id: str) -> Path:
    """Create a minimal terminal-bench task directory."""
    task_dir = tmp_path / task_id
    task_dir.mkdir()
    (task_dir / "task.yaml").write_text(
        textwrap.dedent("""\
            instruction: "Echo hello world"
            difficulty: easy
            category: shell
            parser_name: pytest
        """)
    )
    (task_dir / "run-tests.sh").write_text("#!/bin/bash\necho 'ok'\n")
    (task_dir / "docker-compose.yaml").write_text("version: '3'\nservices: {}\n")
    return task_dir


def _make_trial_result(is_resolved: bool):
    """Build a minimal TrialResults-like mock."""
    from terminal_bench.harness.harness import TrialResults, FailureMode

    r = MagicMock(spec=TrialResults)
    r.is_resolved = is_resolved
    r.total_input_tokens = 100
    r.total_output_tokens = 50
    r.parser_results = {}
    r.failure_mode = FailureMode.NONE
    return r


def _make_benchmark_results(is_resolved: bool):
    from terminal_bench import BenchmarkResults

    br = MagicMock(spec=BenchmarkResults)
    br.results = [_make_trial_result(is_resolved)]
    return br


# ---------------------------------------------------------------------------
# Fix 1: Dataset stores task_dir as Path
# ---------------------------------------------------------------------------

class TestDatasetTaskDirIsPath:
    def test_task_dir_is_path(self, tmp_path):
        task_dir = _make_task_dir(tmp_path, "task-001")

        from openjarvis.evals.datasets.terminalbench_native import (
            TerminalBenchNativeDataset,
        )

        ds = TerminalBenchNativeDataset()
        record = ds._convert_task(task_dir, 0)

        assert record is not None
        assert isinstance(
            record.metadata["task_dir"], Path
        ), "task_dir must be a Path, not a string"

    def test_create_task_env_returns_none(self, tmp_path):
        task_dir = _make_task_dir(tmp_path, "task-002")

        from openjarvis.evals.datasets.terminalbench_native import (
            TerminalBenchNativeDataset,
        )
        from openjarvis.evals.core.types import EvalRecord

        ds = TerminalBenchNativeDataset()
        record = ds._convert_task(task_dir, 0)
        assert record is not None

        env = ds.create_task_env(record)
        assert env is None, "Harness handles Docker; create_task_env must return None"


# ---------------------------------------------------------------------------
# Fix 2: Backend set_current_record wires task_dir into generate_full
# ---------------------------------------------------------------------------

class TestBackendSetCurrentRecord:
    def test_set_current_record_routes_to_correct_task(self, tmp_path):
        task_dir = _make_task_dir(tmp_path, "task-003")

        from openjarvis.evals.backends.terminalbench_native import (
            TerminalBenchNativeBackend,
        )
        from openjarvis.evals.core.types import EvalRecord

        record = EvalRecord(
            record_id="terminalbench-native-task-003",
            problem="Echo hello world",
            reference="",
            category="agentic",
            subject="shell",
            metadata={"task_id": "task-003", "task_dir": task_dir},
        )

        backend = TerminalBenchNativeBackend(
            model="claude-3-5-haiku-20241022",
            engine_key="cloud",
            output_dir=str(tmp_path / "results"),
        )
        backend.set_current_record(record)
        assert backend._current_record is record

    def test_generate_full_writes_is_resolved_to_metadata(self, tmp_path):
        task_dir = _make_task_dir(tmp_path, "task-004")

        from openjarvis.evals.backends.terminalbench_native import (
            TerminalBenchNativeBackend,
        )
        from openjarvis.evals.core.types import EvalRecord

        record = EvalRecord(
            record_id="terminalbench-native-task-004",
            problem="Echo hello world",
            reference="",
            category="agentic",
            subject="shell",
            metadata={"task_id": "task-004", "task_dir": task_dir},
        )

        backend = TerminalBenchNativeBackend(
            model="claude-3-5-haiku-20241022",
            engine_key="cloud",
            output_dir=str(tmp_path / "results"),
        )
        backend.set_current_record(record)

        mock_results = _make_benchmark_results(is_resolved=True)

        with patch(
            "openjarvis.evals.backends.terminalbench_native.Harness"
        ) as MockHarness:
            MockHarness.return_value.run.return_value = mock_results
            full = backend.generate_full("Echo hello world", model="claude-3-5-haiku-20241022")

        assert record.metadata["is_resolved"] is True
        assert full["usage"]["prompt_tokens"] == 100
        assert full["usage"]["completion_tokens"] == 50

    def test_generate_full_without_set_current_record_returns_empty(self, tmp_path):
        from openjarvis.evals.backends.terminalbench_native import (
            TerminalBenchNativeBackend,
        )

        backend = TerminalBenchNativeBackend(output_dir=str(tmp_path / "results"))
        result = backend.generate_full("some prompt", model="claude-3-5-haiku-20241022")
        assert result["content"] == ""
        assert result["latency_seconds"] == 0.0


# ---------------------------------------------------------------------------
# Fix 3: Scorer reads is_resolved from record.metadata
# ---------------------------------------------------------------------------

class TestScorerReadsIsResolved:
    def _make_record(self, is_resolved: Optional[bool]):
        from openjarvis.evals.core.types import EvalRecord

        meta: Dict[str, Any] = {"task_id": "t1", "task_dir": Path("/fake")}
        if is_resolved is not None:
            meta["is_resolved"] = is_resolved
        return EvalRecord(
            record_id="tb-t1",
            problem="p",
            reference="",
            category="agentic",
            subject="shell",
            metadata=meta,
        )

    def test_resolved_task_passes(self):
        from openjarvis.evals.scorers.terminalbench_native_structural import (
            TerminalBenchNativeScorer,
        )

        scorer = TerminalBenchNativeScorer()
        record = self._make_record(is_resolved=True)
        is_correct, meta = scorer.score(record, "")
        assert is_correct is True

    def test_unresolved_task_fails(self):
        from openjarvis.evals.scorers.terminalbench_native_structural import (
            TerminalBenchNativeScorer,
        )

        scorer = TerminalBenchNativeScorer()
        record = self._make_record(is_resolved=False)
        is_correct, meta = scorer.score(record, "")
        assert is_correct is False

    def test_missing_is_resolved_returns_indeterminate(self):
        from openjarvis.evals.scorers.terminalbench_native_structural import (
            TerminalBenchNativeScorer,
        )

        scorer = TerminalBenchNativeScorer()
        record = self._make_record(is_resolved=None)
        is_correct, meta = scorer.score(record, "")
        assert is_correct is None
        assert meta["reason"] == "no_test_results"


# ---------------------------------------------------------------------------
# Fix 4: EvalRunner calls set_current_record before generate_full
# ---------------------------------------------------------------------------

class TestRunnerCallsSetCurrentRecord:
    def test_runner_calls_set_current_record(self, tmp_path):
        """EvalRunner must call backend.set_current_record(record) before generate_full."""
        task_dir = _make_task_dir(tmp_path, "task-runner")

        from openjarvis.evals.datasets.terminalbench_native import (
            TerminalBenchNativeDataset,
        )
        from openjarvis.evals.scorers.terminalbench_native_structural import (
            TerminalBenchNativeScorer,
        )
        from openjarvis.evals.backends.terminalbench_native import (
            TerminalBenchNativeBackend,
        )
        from openjarvis.evals.core.runner import EvalRunner
        from openjarvis.evals.core.config import RunConfig

        # Build a minimal dataset with one task.
        ds = TerminalBenchNativeDataset()
        record = ds._convert_task(task_dir, 0)
        assert record is not None

        scorer = TerminalBenchNativeScorer()
        backend = TerminalBenchNativeBackend(
            output_dir=str(tmp_path / "results"),
        )

        records_seen_in_set: list = []
        original_set = backend.set_current_record

        def tracking_set(r):
            records_seen_in_set.append(r)
            original_set(r)

        backend.set_current_record = tracking_set

        mock_results = _make_benchmark_results(is_resolved=False)

        cfg = RunConfig(
            benchmark="terminalbench-native",
            backend="terminalbench-native",
            model="claude-3-5-haiku-20241022",
            engine_key="cloud",
            temperature=0.0,
            max_tokens=1024,
            output_path=str(tmp_path / "out"),
            max_samples=1,
        )

        runner = EvalRunner(cfg, ds, backend, scorer)

        # Patch both _TBDataset (used by dataset.load inside runner.run)
        # and Harness (used by generate_full) for the entire run.
        with patch(
            "openjarvis.evals.datasets.terminalbench_native._TBDataset"
        ) as MockDataset, patch(
            "openjarvis.evals.backends.terminalbench_native.Harness"
        ) as MockHarness:
            MockDataset.return_value.tasks = [task_dir]
            MockHarness.return_value.run.return_value = mock_results
            summary = runner.run()

        # set_current_record must have been called once (for the one task).
        assert len(records_seen_in_set) == 1
        assert records_seen_in_set[0].record_id == record.record_id

        # Summary must reflect the one failed task.
        assert summary.total_samples == 1
        assert summary.correct == 0
