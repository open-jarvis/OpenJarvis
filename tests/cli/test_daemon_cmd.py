"""Tests for ``jarvis start|stop|restart|status`` daemon management commands."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.cli.daemon_cmd import _pid_alive, _read_pid, _write_pid


class TestDaemonCommands:
    """Core daemon CLI tests."""

    def test_start_command_exists(self) -> None:
        """``jarvis start --help`` succeeds."""
        result = CliRunner().invoke(cli, ["start", "--help"])
        assert result.exit_code == 0
        out = result.output.lower()
        assert "daemon" in out or "start" in out or "background" in out

    def test_stop_no_server(self) -> None:
        """``jarvis stop`` when no PID file shows 'not running'."""
        with patch("openjarvis.cli.daemon_cmd._read_pid", return_value=None):
            result = CliRunner().invoke(cli, ["stop"])
        assert result.exit_code != 0
        assert "No running server" in result.output

    def test_status_no_server(self) -> None:
        """``jarvis status`` when no PID file shows 'not running'."""
        with patch("openjarvis.cli.daemon_cmd._read_pid", return_value=None):
            result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "not running" in result.output

    def test_read_pid_no_file(self, tmp_path: Path) -> None:
        """``_read_pid()`` returns None when no PID file exists."""
        with patch(
            "openjarvis.cli.daemon_cmd._PID_FILE",
            tmp_path / "nonexistent.pid",
        ):
            assert _read_pid() is None

    def test_write_and_read_pid(self, tmp_path: Path) -> None:
        """Write a PID, then read it back (mock the liveness probe to succeed)."""
        pid_file = tmp_path / "server.pid"
        with (
            patch("openjarvis.cli.daemon_cmd._PID_FILE", pid_file),
            patch("openjarvis.cli.daemon_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch("openjarvis.cli.daemon_cmd._pid_alive", return_value=True),
        ):
            _write_pid(12345)
            assert pid_file.exists()
            assert _read_pid() == 12345

    def test_status_shows_running(self) -> None:
        """``jarvis status`` shows running info when PID exists."""
        mock_config = MagicMock()
        mock_config.server.host = "127.0.0.1"
        mock_config.server.port = 8000

        with (
            patch("openjarvis.cli.daemon_cmd._read_pid", return_value=9999),
            patch(
                "openjarvis.cli.daemon_cmd.load_config",
                return_value=mock_config,
            ),
        ):
            result = CliRunner().invoke(cli, ["status"])
        assert result.exit_code == 0
        assert "running" in result.output
        assert "9999" in result.output

    def test_start_already_running(self) -> None:
        """``jarvis start`` exits with error when a server is already running."""
        with patch("openjarvis.cli.daemon_cmd._read_pid", return_value=42):
            result = CliRunner().invoke(cli, ["start"])
        assert result.exit_code != 0
        assert "already running" in result.output


class TestPidLiveness:
    """Regression tests for the Windows ``os.kill(pid, 0)`` liveness bug.

    On Windows signal ``0`` is ``CTRL_C_EVENT``, so ``os.kill(pid, 0)`` raised
    ``OSError`` (WinError 87) instead of acting as a liveness probe — which made
    ``jarvis status`` crash / misreport a running server as dead. These tests
    use REAL pids (no ``os.kill`` mock) so they exercise the real platform code
    path on both Windows and POSIX.
    """

    def test_pid_alive_current_process(self) -> None:
        assert _pid_alive(os.getpid()) is True

    def test_pid_alive_nonpositive(self) -> None:
        assert _pid_alive(0) is False
        assert _pid_alive(-1) is False

    def test_pid_alive_dead_pid(self) -> None:
        """A reaped child's pid reports dead, without raising."""
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        for _ in range(20):
            if not _pid_alive(proc.pid):
                break
            time.sleep(0.1)
        assert _pid_alive(proc.pid) is False

    def test_read_pid_stale_pid_returns_none(self, tmp_path: Path) -> None:
        """PID file → dead process: returns None (no raise) and removes the file."""
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        time.sleep(0.2)
        pid_file = tmp_path / "server.pid"
        pid_file.write_text(str(proc.pid))
        with patch("openjarvis.cli.daemon_cmd._PID_FILE", pid_file):
            # Previously raised OSError(WinError 87) on Windows.
            assert _read_pid() is None
        assert not pid_file.exists()

    def test_read_pid_live_pid_returns_it(self, tmp_path: Path) -> None:
        """PID file → live process: returns that pid and keeps the file."""
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
        try:
            pid_file = tmp_path / "server.pid"
            pid_file.write_text(str(proc.pid))
            with patch("openjarvis.cli.daemon_cmd._PID_FILE", pid_file):
                assert _read_pid() == proc.pid
            assert pid_file.exists()
        finally:
            proc.terminate()
            proc.wait()
