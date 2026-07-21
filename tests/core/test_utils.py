"""Tests for cross-platform process helpers in ``openjarvis.core.utils``."""

from __future__ import annotations

import os
import subprocess
import sys
import time

from openjarvis.core.utils import process_alive, terminate_process


class TestProcessAlive:
    def test_current_process_is_alive(self) -> None:
        assert process_alive(os.getpid()) is True

    def test_bogus_pid_not_alive(self) -> None:
        assert process_alive(999_999_999) is False

    def test_none_pid_not_alive(self) -> None:
        assert process_alive(None) is False

    def test_nonpositive_pid_not_alive(self) -> None:
        assert process_alive(0) is False
        assert process_alive(-1) is False


class TestTerminateProcess:
    def _spawn_sleeper(self) -> subprocess.Popen:
        # Portable long-running child: sleeps well beyond the test's lifetime.
        return subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )

    def test_terminates_running_process(self) -> None:
        proc = self._spawn_sleeper()
        try:
            # Give the interpreter a moment to come up.
            for _ in range(20):
                if process_alive(proc.pid):
                    break
                time.sleep(0.05)
            assert process_alive(proc.pid) is True

            terminate_process(proc.pid, grace_seconds=5.0)

            # Should be gone shortly after terminate returns.
            for _ in range(20):
                if not process_alive(proc.pid):
                    break
                time.sleep(0.05)
            assert process_alive(proc.pid) is False
        finally:
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    def test_terminate_bogus_pid_no_crash(self) -> None:
        # Must be a no-op, never raise, on any platform.
        terminate_process(999_999_999)

    def test_terminate_none_no_crash(self) -> None:
        terminate_process(None)
