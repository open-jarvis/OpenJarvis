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
        """Write a PID, then read it back with a successful liveness probe."""
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
    """Regression coverage for Windows-safe PID liveness checks."""

    def test_pid_alive_current_process(self) -> None:
        assert _pid_alive(os.getpid()) is True

    def test_pid_alive_nonpositive(self) -> None:
        assert _pid_alive(0) is False
        assert _pid_alive(-1) is False

    def test_pid_alive_dead_pid(self) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()

        for _ in range(20):
            if not _pid_alive(proc.pid):
                break
            time.sleep(0.1)

        assert _pid_alive(proc.pid) is False

    def test_read_pid_stale_pid_returns_none(self, tmp_path: Path) -> None:
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        pid_file = tmp_path / "server.pid"
        pid_file.write_text(str(proc.pid))

        with patch("openjarvis.cli.daemon_cmd._PID_FILE", pid_file):
            assert _read_pid() is None

        assert not pid_file.exists()

    def test_read_pid_live_pid_returns_it(self, tmp_path: Path) -> None:
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


class TestDaemonDetachment:
    """The spawned server must outlive the console that started it.

    ``start_new_session`` is POSIX-only — CPython's Windows ``_execute_child``
    names the parameter ``unused_start_new_session``. Relying on it there leaves
    the server sharing its parent's console, so closing that console (or logging
    off) delivers CTRL_CLOSE_EVENT and kills the daemon.
    """

    @staticmethod
    def _spawn_kwargs(platform: str) -> dict:
        """Return the kwargs ``start`` passes to Popen when spawning the server.

        ``load_config`` is stubbed because it shells out for GPU detection —
        patching Popen wholesale would otherwise break config loading before
        the spawn is reached.
        """
        with (
            patch("openjarvis.cli.daemon_cmd._read_pid", return_value=None),
            patch("openjarvis.cli.daemon_cmd._write_pid"),
            patch("openjarvis.cli.daemon_cmd.load_config"),
            patch("openjarvis.cli.daemon_cmd.sys.platform", platform),
            patch("openjarvis.cli.daemon_cmd.subprocess.Popen") as popen,
            patch("builtins.open", MagicMock()),
        ):
            popen.return_value = MagicMock(pid=4321)
            result = CliRunner().invoke(cli, ["start"])
            assert result.exit_code == 0, result.output
            spawns = [
                c for c in popen.call_args_list if c.args and "serve" in c.args[0]
            ]
            assert spawns, f"start did not spawn the server: {popen.call_args_list}"
            return spawns[-1].kwargs

    def test_windows_spawn_is_detached_from_the_console(self) -> None:
        # These constants are only exported by ``subprocess`` on Windows.
        # Supply their documented values so the simulated Windows branch is
        # still exercised by the POSIX test job.
        detached_process = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        create_new_process_group = getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
        )
        with (
            patch.object(
                subprocess,
                "DETACHED_PROCESS",
                detached_process,
                create=True,
            ),
            patch.object(
                subprocess,
                "CREATE_NEW_PROCESS_GROUP",
                create_new_process_group,
                create=True,
            ),
        ):
            kwargs = self._spawn_kwargs("win32")

        flags = kwargs.get("creationflags", 0)
        assert flags & detached_process, (
            "server must be spawned with DETACHED_PROCESS on Windows, otherwise "
            "closing the launching console kills it"
        )
        assert flags & create_new_process_group, (
            "server must be in its own process group so Ctrl-C in the parent "
            "console does not propagate to it"
        )
        assert not kwargs.get("start_new_session"), (
            "start_new_session is ignored on Windows; it must not be relied on"
        )

    def test_posix_spawn_still_uses_start_new_session(self) -> None:
        kwargs = self._spawn_kwargs("linux")
        assert kwargs.get("start_new_session") is True
        assert "creationflags" not in kwargs or kwargs["creationflags"] == 0
