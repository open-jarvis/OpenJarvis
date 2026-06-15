"""Tests for TerminalBenchTaskEnv (mocked terminal_bench dependency).

These tests install a fake ``terminal_bench`` module tree into
``sys.modules`` so they run without the real package or a Docker daemon
(terminal-bench is an undeclared optional dep that CI never installs).
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from openjarvis.evals.core.environment import TaskEnvironmentError
from openjarvis.evals.execution.terminalbench_env import TerminalBenchTaskEnv

# ---------------------------------------------------------------------------
# Fake terminal_bench seam
# ---------------------------------------------------------------------------


@dataclass
class FakeExecResult:
    exit_code: int = 0
    output: bytes = b""


@dataclass
class FakeContainer:
    """Container stub whose exec_run results are configurable per binary."""

    exec_results: Dict[str, FakeExecResult] = field(default_factory=dict)
    exec_calls: List[List[str]] = field(default_factory=list)

    def exec_run(self, cmd: List[str]) -> FakeExecResult:
        self.exec_calls.append(list(cmd))
        return self.exec_results.get(cmd[0], FakeExecResult())


class FakeTerminal:
    def __init__(self, events: List[str], container: FakeContainer) -> None:
        self._events = events
        self.container = container
        self.create_session_error: Exception | None = None

    def create_session(self, name: str, **_kwargs: Any) -> str:
        self._events.append(f"create_session({name})")
        if self.create_session_error is not None:
            raise self.create_session_error
        return f"session-{name}"


@pytest.fixture()
def fake_tb(monkeypatch, tmp_path):
    """Install a fake terminal_bench tree; return the shared test state."""
    events: List[str] = []
    container = FakeContainer()
    terminal = FakeTerminal(events, container)
    state = SimpleNamespace(
        events=events,
        container=container,
        terminal=terminal,
        spin_up_error=None,
    )

    @contextmanager
    def spin_up_terminal(**kwargs: Any):
        events.append("compose_up")
        try:
            if state.spin_up_error is not None:
                raise state.spin_up_error
            yield terminal
        finally:
            events.append("compose_down")

    mod_tb = types.ModuleType("terminal_bench")
    mod_terminal_pkg = types.ModuleType("terminal_bench.terminal")
    mod_terminal = types.ModuleType("terminal_bench.terminal.terminal")
    mod_terminal.spin_up_terminal = spin_up_terminal
    mod_tb.terminal = mod_terminal_pkg
    mod_terminal_pkg.terminal = mod_terminal
    monkeypatch.setitem(sys.modules, "terminal_bench", mod_tb)
    monkeypatch.setitem(sys.modules, "terminal_bench.terminal", mod_terminal_pkg)
    monkeypatch.setitem(sys.modules, "terminal_bench.terminal.terminal", mod_terminal)

    state.metadata = {
        "task_id": "hello.world",
        "task": SimpleNamespace(disable_asciinema=True),
        "task_paths": SimpleNamespace(docker_compose_path=tmp_path / "compose.yaml"),
    }
    return state


# ---------------------------------------------------------------------------
# Existing behavior (now running without the real terminal_bench package)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Exception-safe __enter__ / preflight / teardown
# ---------------------------------------------------------------------------


class TestEnterExceptionSafety:
    def test_success_path(self, fake_tb):
        env = TerminalBenchTaskEnv(fake_tb.metadata)
        with env:
            assert fake_tb.metadata["terminal"] is fake_tb.terminal
            assert fake_tb.metadata["session"] == "session-agent"
            assert fake_tb.metadata["container"] == "oj-hello-world"
            assert "compose_down" not in fake_tb.events
        assert fake_tb.events.count("compose_down") == 1
        assert "terminal" not in fake_tb.metadata

    def test_create_session_failure_tears_down_terminal(self, fake_tb):
        """(a) tmux failure in __enter__ -> terminal torn down, loud error."""
        fake_tb.terminal.create_session_error = RuntimeError(
            "tmux is not installed in the container."
        )
        env = TerminalBenchTaskEnv(fake_tb.metadata)

        with pytest.raises(TaskEnvironmentError) as excinfo:
            env.__enter__()

        # No leak: compose project downed BEFORE the exception escaped.
        assert "compose_down" in fake_tb.events
        # Actionable: names the task, the image, and the failure.
        message = str(excinfo.value)
        assert "hello.world" in message
        assert "tb__hello-world__client" in message
        assert "tmux is not installed" in message
        # Recorded for the runner / scorers; handles cleared.
        assert fake_tb.metadata["harness_error"] == message
        assert "terminal" not in fake_tb.metadata
        assert "session" not in fake_tb.metadata
        assert "container" not in fake_tb.metadata
        assert env._terminal is None
        assert env._terminal_cm is None
        assert env._logs_tmpdir is None

    def test_preflight_catches_missing_tmux(self, fake_tb):
        """(b) preflight catches missing tmux, naming the task image."""
        fake_tb.container.exec_results["tmux"] = FakeExecResult(
            exit_code=127,
            output=b'exec: "tmux": executable file not found in $PATH',
        )
        env = TerminalBenchTaskEnv(fake_tb.metadata)

        with pytest.raises(TaskEnvironmentError) as excinfo:
            env.__enter__()

        message = str(excinfo.value)
        assert "tmux" in message
        assert "tb__hello-world__client" in message  # task image named
        assert "127" in message
        # Fired BEFORE the agent session was created.
        assert not any(e.startswith("create_session") for e in fake_tb.events)
        assert "compose_down" in fake_tb.events
        assert fake_tb.metadata["harness_error"] == message

    def test_preflight_checks_asciinema_when_recording(self, fake_tb):
        fake_tb.metadata["task"] = SimpleNamespace(disable_asciinema=False)
        fake_tb.container.exec_results["asciinema"] = FakeExecResult(exit_code=127)
        env = TerminalBenchTaskEnv(fake_tb.metadata)

        with pytest.raises(TaskEnvironmentError, match="asciinema"):
            env.__enter__()
        assert "disable_asciinema" in fake_tb.metadata["harness_error"]
        assert "compose_down" in fake_tb.events

    def test_preflight_skips_asciinema_when_disabled(self, fake_tb):
        fake_tb.container.exec_results["asciinema"] = FakeExecResult(exit_code=127)
        env = TerminalBenchTaskEnv(fake_tb.metadata)
        with env:
            pass
        assert ["asciinema", "--version"] not in fake_tb.container.exec_calls

    def test_compose_up_failure_includes_stderr(self, fake_tb):
        import subprocess

        fake_tb.spin_up_error = subprocess.CalledProcessError(
            returncode=1,
            cmd=["docker", "compose", "up"],
            stderr="no space left on device",
        )
        env = TerminalBenchTaskEnv(fake_tb.metadata)

        with pytest.raises(TaskEnvironmentError) as excinfo:
            env.__enter__()
        assert "no space left on device" in str(excinfo.value)

    def test_keyboard_interrupt_not_masked(self, fake_tb):
        fake_tb.terminal.create_session_error = KeyboardInterrupt()
        env = TerminalBenchTaskEnv(fake_tb.metadata)

        with pytest.raises(KeyboardInterrupt):
            env.__enter__()
        # Still cleaned up, but the interrupt is not wrapped.
        assert "compose_down" in fake_tb.events

    def test_teardown_is_idempotent(self, fake_tb):
        env = TerminalBenchTaskEnv(fake_tb.metadata)
        env.__enter__()
        env.__exit__(None, None, None)
        env.__exit__(None, None, None)
        assert fake_tb.events.count("compose_down") == 1
