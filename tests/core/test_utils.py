"""Tests for cross-platform process helpers in ``openjarvis.core.utils``."""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import sys
import time
from unittest.mock import MagicMock, call, patch

import pytest

from openjarvis.core.utils import (
    _windows_process_alive,
    process_alive,
    terminate_process,
)


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

    @pytest.mark.skipif(platform.system() == "Windows", reason="POSIX-only")
    def test_unreaped_zombie_is_not_alive(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        try:
            for _ in range(100):
                if not process_alive(proc.pid):
                    break
                time.sleep(0.01)
            assert process_alive(proc.pid) is False
        finally:
            proc.wait(timeout=5)

    def test_permission_error_is_conservatively_alive(self) -> None:
        with (
            patch("openjarvis.core.utils.platform.system", return_value="Linux"),
            patch("openjarvis.core.utils.os.kill", side_effect=PermissionError),
            patch("openjarvis.core.utils._posix_process_state", return_value=None),
        ):
            assert process_alive(1234) is True

    def test_windows_path_never_calls_os_kill(self) -> None:
        with (
            patch("openjarvis.core.utils.platform.system", return_value="Windows"),
            patch(
                "openjarvis.core.utils._windows_process_alive", return_value=True
            ) as win_alive,
            patch("openjarvis.core.utils.os.kill") as os_kill,
        ):
            assert process_alive(4321) is True
        win_alive.assert_called_once_with(4321)
        os_kill.assert_not_called()


class TestWindowsProcessAlive:
    @staticmethod
    def _kernel(open_result: int, wait_result: int = 0) -> MagicMock:
        kernel32 = MagicMock()
        kernel32.OpenProcess.return_value = open_result
        kernel32.WaitForSingleObject.return_value = wait_result
        return kernel32

    def test_missing_pid(self) -> None:
        import ctypes

        kernel32 = self._kernel(0)
        with (
            patch.object(ctypes, "WinDLL", return_value=kernel32, create=True),
            patch.object(ctypes, "get_last_error", return_value=87, create=True),
        ):
            assert _windows_process_alive(1234) is False

    def test_access_denied_is_conservatively_alive(self) -> None:
        import ctypes

        kernel32 = self._kernel(0)
        with (
            patch.object(ctypes, "WinDLL", return_value=kernel32, create=True),
            patch.object(ctypes, "get_last_error", return_value=5, create=True),
        ):
            assert _windows_process_alive(1234) is True

    @pytest.mark.parametrize(
        ("wait_result", "expected"), [(0x00000000, False), (0x00000102, True)]
    )
    def test_process_handle_state(self, wait_result: int, expected: bool) -> None:
        import ctypes

        kernel32 = self._kernel(99, wait_result)
        with patch.object(ctypes, "WinDLL", return_value=kernel32, create=True):
            assert _windows_process_alive(1234) is expected
        kernel32.CloseHandle.assert_called_once_with(99)


class TestTerminateProcess:
    def _spawn_sleeper(self) -> subprocess.Popen:
        # Portable long-running child: sleeps well beyond the test's lifetime.
        return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])

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

    def test_posix_escalates_to_sigkill(self) -> None:
        with (
            patch("openjarvis.core.utils.platform.system", return_value="Linux"),
            patch("openjarvis.core.utils.process_alive", return_value=True),
            patch("openjarvis.core.utils.os.kill") as os_kill,
        ):
            terminate_process(1234, grace_seconds=0)
        assert os_kill.call_args_list == [
            call(1234, signal.SIGTERM),
            call(1234, signal.SIGKILL),
        ]

    def test_windows_graceful_taskkill(self) -> None:
        with (
            patch("openjarvis.core.utils.platform.system", return_value="Windows"),
            patch("openjarvis.core.utils.process_alive", side_effect=[True, False]),
            patch("openjarvis.core.utils.subprocess.run") as run,
        ):
            terminate_process(1234, grace_seconds=1)
        run.assert_called_once_with(
            ["taskkill", "/PID", "1234"], capture_output=True, check=False
        )

    def test_windows_escalates_to_forced_tree_kill(self) -> None:
        with (
            patch("openjarvis.core.utils.platform.system", return_value="Windows"),
            patch("openjarvis.core.utils.process_alive", return_value=True),
            patch("openjarvis.core.utils.subprocess.run") as run,
        ):
            terminate_process(1234, grace_seconds=0)
        assert run.call_args_list == [
            call(
                ["taskkill", "/PID", "1234"],
                capture_output=True,
                check=False,
            ),
            call(
                ["taskkill", "/F", "/T", "/PID", "1234"],
                capture_output=True,
                check=False,
            ),
        ]
