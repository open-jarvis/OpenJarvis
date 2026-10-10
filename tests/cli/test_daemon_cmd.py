"""Tests for ``jarvis start|stop|restart|status`` daemon management commands."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.cli.daemon_cmd import (
    _pid_alive,
    _read_pid,
    _write_pid,
)
from openjarvis.core.utils import terminate_process


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

    @pytest.mark.skipif(sys.platform != "linux", reason="Linux procfs start times")
    def test_pid_reused_after_registration_does_not_block_or_get_signaled(
        self, tmp_path
    ):
        from openjarvis.cli import daemon_cmd

        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        pid_file = tmp_path / "server.pid"
        state_file = tmp_path / "server.json"
        try:
            pid_file.write_text(str(proc.pid))
            os.utime(pid_file, (time.time() - 120, time.time() - 120))
            with (
                patch.object(daemon_cmd, "_PID_FILE", pid_file),
                patch.object(daemon_cmd, "_STATE_FILE", state_file),
            ):
                assert daemon_cmd._read_pid() is None
                assert not pid_file.exists()
                assert proc.poll() is None
                pid_file.write_text(str(proc.pid))
                os.utime(pid_file, (time.time() - 120, time.time() - 120))
                daemon_cmd._write_pid(os.getpid(), "127.0.0.1", 8000)
                assert daemon_cmd._read_pid() == os.getpid()
                assert proc.poll() is None
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
            patch("openjarvis.cli.daemon_cmd._read_pid_unlocked", return_value=None),
            patch("openjarvis.cli.daemon_cmd._state_lock", return_value=nullcontext()),
            patch("openjarvis.cli.daemon_cmd._write_pid_unlocked"),
            patch("openjarvis.cli.daemon_cmd.load_config"),
            patch("openjarvis.cli.daemon_cmd.sys.platform", platform),
            patch("openjarvis.cli.daemon_cmd.DEFAULT_CONFIG_DIR"),
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

    def test_windows_start_registers_spawned_pid_immediately(
        self, tmp_path: Path
    ) -> None:
        """Both direct Python and launchers can protect the startup interval."""
        with (
            patch("openjarvis.cli.daemon_cmd._read_pid", return_value=None),
            patch("openjarvis.cli.daemon_cmd._read_pid_unlocked", return_value=None),
            patch("openjarvis.cli.daemon_cmd._state_lock", return_value=nullcontext()),
            patch("openjarvis.cli.daemon_cmd.load_config"),
            patch("openjarvis.cli.daemon_cmd.subprocess.Popen") as popen,
            patch("openjarvis.cli.daemon_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch("openjarvis.cli.daemon_cmd._LOG_FILE", tmp_path / "server.log"),
            patch("openjarvis.cli.daemon_cmd.sys.platform", "win32"),
            patch("openjarvis.cli.daemon_cmd._write_pid_unlocked") as write_pid,
            patch.object(subprocess, "DETACHED_PROCESS", 0x00000008, create=True),
            patch.object(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, create=True
            ),
        ):
            popen.return_value = MagicMock(pid=4321)

            result = CliRunner().invoke(cli, ["start"])

            assert result.exit_code == 0, result.output
            assert "launch PID 4321" in result.output
            write_pid.assert_called_once()
            assert write_pid.call_args.args[0] == 4321
            assert write_pid.call_args.kwargs["ready"] is False
            token = write_pid.call_args.kwargs["launch_token"]
            assert token
            assert (
                popen.call_args.kwargs["env"]["OPENJARVIS_DAEMON_LAUNCH_TOKEN"] == token
            )

    def test_second_start_rechecks_under_lock(self, tmp_path: Path) -> None:
        """A second start must not spawn after another caller registered."""
        with (
            patch("openjarvis.cli.daemon_cmd._read_pid", return_value=None),
            patch("openjarvis.cli.daemon_cmd._read_pid_unlocked", return_value=4321),
            patch("openjarvis.cli.daemon_cmd._state_lock", return_value=nullcontext()),
            patch("openjarvis.cli.daemon_cmd.load_config"),
            patch("openjarvis.cli.daemon_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch("openjarvis.cli.daemon_cmd.subprocess.Popen") as popen,
        ):
            result = CliRunner().invoke(cli, ["start"])
            assert result.exit_code != 0
            assert "already running" in result.output
            popen.assert_not_called()

    def test_failed_registration_terminates_spawned_tree(self, tmp_path: Path) -> None:
        """A failed launch must clean up its launcher and any descendants."""
        with (
            patch("openjarvis.cli.daemon_cmd._read_pid", return_value=None),
            patch("openjarvis.cli.daemon_cmd._read_pid_unlocked", return_value=None),
            patch("openjarvis.cli.daemon_cmd._state_lock", return_value=nullcontext()),
            patch("openjarvis.cli.daemon_cmd.load_config"),
            patch("openjarvis.cli.daemon_cmd.DEFAULT_CONFIG_DIR", tmp_path),
            patch("openjarvis.cli.daemon_cmd._LOG_FILE", tmp_path / "server.log"),
            patch(
                "openjarvis.cli.daemon_cmd._write_pid_unlocked",
                side_effect=RuntimeError("conflict"),
            ),
            patch(
                "openjarvis.cli.daemon_cmd.subprocess.Popen",
                return_value=MagicMock(pid=4321),
            ),
            patch("openjarvis.cli.daemon_cmd.terminate_process") as terminate,
            patch("openjarvis.cli.daemon_cmd.clear_server_state") as clear,
        ):
            result = CliRunner().invoke(cli, ["start"])
            assert result.exit_code != 0
            assert "conflict" in result.output
            terminate.assert_called_once_with(4321, grace_seconds=10.0)
            clear.assert_called_once_with(4321)

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


def test_subprocess_registers_actual_python_pid(tmp_path: Path, monkeypatch) -> None:
    """A real child registers its PID whether Python is direct or uses a launcher."""
    from openjarvis.cli import daemon_cmd

    pid_file = tmp_path / "server.pid"
    state_file = tmp_path / "server.json"
    child_pid_file = tmp_path / "child.pid"
    ready_file = tmp_path / "child.ready"
    log_file = tmp_path / "child.log"
    token = secrets.token_hex(16)
    monkeypatch.setattr(daemon_cmd, "_PID_FILE", pid_file)
    monkeypatch.setattr(daemon_cmd, "_STATE_FILE", state_file)

    code = """
import os
import time
from pathlib import Path
from openjarvis.cli import daemon_cmd

daemon_cmd._PID_FILE = Path(os.environ["OJ_TEST_PID_FILE"])
daemon_cmd._STATE_FILE = Path(os.environ["OJ_TEST_STATE_FILE"])
pid_file = Path(os.environ["OJ_TEST_CHILD_PID_FILE"])
pid_tmp = pid_file.with_suffix(".tmp")
pid_tmp.write_text(str(os.getpid()))
pid_tmp.replace(pid_file)
try:
    daemon_cmd.record_server_state(os.getpid(), "127.0.0.1", 8899)
    Path(os.environ["OJ_TEST_READY_FILE"]).write_text("ready")
    time.sleep(30)
finally:
    daemon_cmd.clear_server_state(os.getpid())
"""
    env = {
        **os.environ,
        daemon_cmd._LAUNCH_TOKEN_ENV: token,
        "OJ_TEST_PID_FILE": str(pid_file),
        "OJ_TEST_STATE_FILE": str(state_file),
        "OJ_TEST_CHILD_PID_FILE": str(child_pid_file),
        "OJ_TEST_READY_FILE": str(ready_file),
    }
    with log_file.open("w") as log_fh:
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdout=log_fh,
            stderr=log_fh,
            env=env,
        )

    actual_pid = None
    try:
        daemon_cmd._write_pid(proc.pid, "127.0.0.1", 0, ready=False, launch_token=token)
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            if child_pid_file.exists():
                actual_pid = int(child_pid_file.read_text())
            if ready_file.exists():
                break
            time.sleep(0.05)

        assert ready_file.exists(), log_file.read_text()
        assert actual_pid is not None
        assert daemon_cmd._read_pid_file() == actual_pid
        assert daemon_cmd._read_state()["pid"] == actual_pid
        assert daemon_cmd._read_state()["port"] == 8899
        assert daemon_cmd._read_state().get("ready", True)
    finally:
        terminate_process(proc.pid, grace_seconds=2.0)
        if actual_pid is None and child_pid_file.exists():
            actual_pid = int(child_pid_file.read_text())
        if actual_pid is not None and actual_pid != proc.pid:
            terminate_process(actual_pid, grace_seconds=2.0)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)
