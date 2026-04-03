"""Tests for TerminalBenchTaskEnv (mocked terminal_bench dependency)."""

from __future__ import annotations

import pytest

from openjarvis.evals.execution.terminalbench_env import TerminalBenchTaskEnv

# terminal_bench is an optional dep — skip all tests if unavailable
terminal_bench = pytest.importorskip(
    "terminal_bench", reason="terminal_bench not installed"
)


class TestTerminalBenchTaskEnv:
    def test_init(self):
        metadata = {"task_id": "test-1"}
        env = TerminalBenchTaskEnv(metadata)
        assert env._metadata is metadata
        assert env._terminal is None

    def test_enter_without_task_raises(self):
        metadata = {"task_id": "test-1"}
        env = TerminalBenchTaskEnv(metadata)
        with pytest.raises(ValueError, match="Task metadata missing"):
            env.__enter__()

    def test_exit_cleans_metadata(self):
        metadata = {
            "task_id": "test-1",
            "terminal": "fake_terminal",
            "session": "fake_session",
            "container": "fake_container",
        }
        env = TerminalBenchTaskEnv(metadata)
        env.__exit__(None, None, None)
        assert "terminal" not in metadata
        assert "session" not in metadata
        assert "container" not in metadata

    def test_run_tests_without_terminal(self):
        metadata = {"task": "mock_task", "task_paths": "mock_paths"}
        env = TerminalBenchTaskEnv(metadata)
        env._terminal = None
        is_resolved, results = env.run_tests()
        assert is_resolved is False
        assert results["error"] == "terminal_not_running"
        assert metadata["is_resolved"] is False
