"""Daemon registrations survive clock changes without accepting recycled PIDs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from openjarvis.cli import daemon_cmd


def _posix(path) -> str:
    """Render a path with forward slashes.

    WindowsPath turns "/proc/x" into "\\proc\\x", but the simulated procfs
    paths are POSIX strings, so both sides must be normalised.
    """
    return str(path).replace("\\", "/")


@pytest.fixture
def linux_process(tmp_path, monkeypatch):
    """Provide deterministic procfs data while using real registration files."""
    monkeypatch.setattr(daemon_cmd, "_PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(daemon_cmd, "_STATE_FILE", tmp_path / "server.json")
    monkeypatch.setattr(daemon_cmd, "DEFAULT_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(daemon_cmd.sys, "platform", "linux")
    monkeypatch.setattr(daemon_cmd, "_pid_alive", lambda pid: True)
    process = {
        "boot_id": "70ec59ac-d41e-48ea-81a4-673a7d1f996b",
        "starts": {4321: 10000, 9876: 20000},
        "argv": ["/usr/bin/python3", "-m", "openjarvis.cli", "serve"],
        "readable": True,
    }
    read_text = Path.read_text
    read_bytes = Path.read_bytes

    def proc_text(path, *args, **kwargs):
        if _posix(path).startswith("/proc/"):
            if not process["readable"]:
                raise PermissionError("procfs unavailable")
            if _posix(path) == "/proc/sys/kernel/random/boot_id":
                return process["boot_id"] + "\n"
            if path.name == "stat" and path.parent.name.isdecimal():
                pid = int(path.parent.name)
                # Fields 4..21 follow state; field 22 is the start tick count.
                fields = ["S", *(["0"] * 18), str(process["starts"][pid])]
                return f"{pid} (python (worker)) " + " ".join(fields)
            raise AssertionError(f"Unexpected wall-clock procfs read: {path}")
        return read_text(path, *args, **kwargs)

    def proc_bytes(path, *args, **kwargs):
        if _posix(path).startswith("/proc/"):
            if not process["readable"]:
                raise PermissionError("procfs unavailable")
            assert path.name == "cmdline"
            return b"\0".join(os.fsencode(arg) for arg in process["argv"]) + b"\0"
        return read_bytes(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", proc_text)
    monkeypatch.setattr(Path, "read_bytes", proc_bytes)
    return process


@pytest.mark.parametrize("mtime", [1, 1700000100.5, 2000000000])
def test_clock_adjustment_does_not_discard_registered_daemon(linux_process, mtime):
    daemon_cmd._write_pid(4321, "127.0.0.1", 8899)
    identity = daemon_cmd._read_pid_identity()
    assert identity == {
        "pid": 4321,
        "boot_id": linux_process["boot_id"],
        "start_ticks": 10000,
    }

    os.utime(daemon_cmd._PID_FILE, (mtime, mtime))

    assert daemon_cmd._read_pid() == 4321
    assert daemon_cmd._bound_address() == ("127.0.0.1", 8899)
    assert daemon_cmd._read_pid_identity() == identity


def test_recycled_pid_is_never_signaled(linux_process, monkeypatch):
    daemon_cmd._write_pid(4321, "127.0.0.1", 8899)
    # A one-tick difference is enough, even in the same wall-clock second.
    linux_process["starts"][4321] += 1
    terminate = Mock()
    monkeypatch.setattr(daemon_cmd, "terminate_process", terminate)

    result = CliRunner().invoke(daemon_cmd.stop)

    assert result.exit_code == 1
    assert "No running server" in result.output
    terminate.assert_not_called()
    assert not daemon_cmd._PID_FILE.exists()
    assert not daemon_cmd._STATE_FILE.exists()
    assert daemon_cmd._read_pid_identity() == {}
    daemon_cmd._write_pid(9876, "127.0.0.1", 8900)
    assert daemon_cmd._read_pid() == 9876


def test_reboot_rejects_even_an_identical_pid_and_start_tick(linux_process):
    daemon_cmd._write_pid(4321, "127.0.0.1", 8899)
    linux_process["boot_id"] = "f7a07684-5a47-475b-b3da-0f507296996a"

    assert daemon_cmd._read_pid() is None
    assert not daemon_cmd._PID_FILE.exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["/venv/bin/jarvis", "serve"],
        ["/venv/bin/jarvis", "--quiet", "serve"],
        ["/venv/bin/jarvis", "--verbose", "--pick-model", "--", "serve"],
        ["/venv/bin/python3", "/venv/bin/jarvis", "--quiet", "serve"],
        ["/venv/bin/python3", "-u", "/venv/bin/jarvis", "serve"],
        ["/venv/bin/python3", "-uO", "-Wignore", "-Xdev", "/venv/bin/jarvis", "serve"],
        ["/venv/bin/python3", "--", "/venv/bin/jarvis", "serve"],
        ["/venv/bin/python3", "-u", "-m", "openjarvis.cli", "serve"],
        ["/venv/bin/python3", "-mopenjarvis.cli", "serve"],
        ["/venv/bin/python3", "-W", "", "-m", "openjarvis.cli", "serve"],
        [
            "/venv/bin/python3",
            "-W",
            "ignore",
            "-X",
            "dev",
            "-m",
            "openjarvis.cli",
            "serve",
        ],
    ],
)
def test_live_legacy_daemon_is_migrated_without_wall_clock(linux_process, argv):
    daemon_cmd._PID_FILE.write_text("4321")
    os.utime(daemon_cmd._PID_FILE, (1, 1))
    linux_process["argv"] = argv

    assert daemon_cmd._read_pid() == 4321
    assert daemon_cmd._read_pid_identity()["start_ticks"] == 10000
    linux_process["starts"][4321] += 1
    assert daemon_cmd._read_pid() is None


@pytest.mark.parametrize(
    "argv",
    [
        ["/usr/bin/python3", "-c", "import time; time.sleep(30)"],
        ["/usr/bin/python3", "/tmp/worker.py", "-m", "openjarvis.cli", "serve"],
        ["/usr/bin/python3", "-u", "/tmp/worker.py", "-m", "openjarvis.cli", "serve"],
        ["/usr/bin/python3", "-c", "pass", "-m", "openjarvis.cli", "serve"],
        ["/usr/bin/python3", "--", "-m", "openjarvis.cli", "serve"],
        ["/usr/bin/python3", "-W", "-m", "openjarvis.cli", "serve"],
        [
            "/usr/bin/python3",
            "-W",
            "",
            "/tmp/worker.py",
            "-m",
            "openjarvis.cli",
            "serve",
        ],
        ["/usr/bin/not-python", "-m", "openjarvis.cli", "serve"],
        ["/venv/bin/jarvis", "ask", "serve"],
        ["/venv/bin/jarvis", "--help", "serve"],
        ["/usr/bin/python3", "-m", "other", "-m", "openjarvis.cli", "serve"],
    ],
)
def test_legacy_unrelated_process_is_not_adopted_or_signaled(
    linux_process, monkeypatch, argv
):
    daemon_cmd._PID_FILE.write_text("4321")
    linux_process["argv"] = argv
    terminate = Mock()
    monkeypatch.setattr(daemon_cmd, "terminate_process", terminate)

    result = CliRunner().invoke(daemon_cmd.stop)

    assert result.exit_code == 1
    terminate.assert_not_called()
    assert not daemon_cmd._PID_FILE.exists()


@pytest.mark.parametrize("legacy", [False, True])
def test_unavailable_procfs_does_not_orphan_a_live_daemon(linux_process, legacy):
    if legacy:
        daemon_cmd._PID_FILE.write_text("4321")
    else:
        daemon_cmd._write_pid(4321, "127.0.0.1", 8899)
    identity = daemon_cmd._read_pid_identity()
    linux_process["readable"] = False

    assert daemon_cmd._read_pid() == 4321
    assert daemon_cmd._read_pid_identity() == identity


def test_legacy_migration_rechecks_identity_after_reading_command(
    linux_process, monkeypatch
):
    daemon_cmd._PID_FILE.write_text("4321")
    read_bytes = Path.read_bytes

    def recycled_after_read(path, *args, **kwargs):
        result = read_bytes(path, *args, **kwargs)
        if _posix(path) == "/proc/4321/cmdline":
            linux_process["starts"][4321] += 1
        return result

    monkeypatch.setattr(Path, "read_bytes", recycled_after_read)

    assert daemon_cmd._read_pid() is None
    assert daemon_cmd._read_pid_identity() == {}


def test_legacy_migration_write_failure_keeps_verified_daemon(
    linux_process, monkeypatch
):
    daemon_cmd._PID_FILE.write_text("4321")
    daemon_cmd._STATE_FILE.write_text(
        json.dumps({"pid": 4321, "host": "127.0.0.1", "port": 8899})
    )
    monkeypatch.setattr(
        daemon_cmd,
        "secure_write_json",
        Mock(side_effect=PermissionError("state directory is read-only")),
    )
    terminate = Mock()
    monkeypatch.setattr(daemon_cmd, "terminate_process", terminate)

    status = CliRunner().invoke(daemon_cmd.status)
    assert status.exit_code == 0, status.output
    assert "Server is running" in status.output
    assert daemon_cmd._PID_FILE.read_text() == "4321"
    assert daemon_cmd._read_pid_identity() == {}
    terminate.assert_not_called()

    stopped = CliRunner().invoke(daemon_cmd.stop)
    assert stopped.exit_code == 0, stopped.output
    terminate.assert_called_once_with(4321, grace_seconds=10.0)
    assert not daemon_cmd._PID_FILE.exists()


def test_child_promotion_preserves_the_child_identity(linux_process):
    daemon_cmd._write_pid(4321, "127.0.0.1", 0, ready=False, launch_token="launch-a")
    daemon_cmd._write_pid(9876, "127.0.0.1", 8899, launch_token="launch-a")
    daemon_cmd._write_pid(4321, "127.0.0.1", 0, ready=False, launch_token="launch-a")

    assert daemon_cmd._read_pid() == 9876
    assert daemon_cmd._read_pid_identity()["start_ticks"] == 20000
    assert daemon_cmd._bound_address() == ("127.0.0.1", 8899)
    daemon_cmd.clear_server_state(4321)
    assert daemon_cmd._read_pid_identity()["pid"] == 9876


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_non_linux_legacy_liveness_is_unchanged(linux_process, monkeypatch, platform):
    # The mocked lock must still use this test host's filesystem locking API.
    monkeypatch.setattr(daemon_cmd.sys, "platform", platform)
    linux_process["readable"] = False
    daemon_cmd._write_pid(4321, "127.0.0.1", 8899)

    assert daemon_cmd._read_pid() == 4321
    assert daemon_cmd._read_pid_identity() == {}


@pytest.mark.parametrize(
    "identity", [[], {"pid": True}, {"pid": 4321, "boot_id": "boot", "start_ticks": -1}]
)
def test_corrupt_identity_uses_legacy_verification(linux_process, identity):
    daemon_cmd._PID_FILE.write_text("4321")
    daemon_cmd._PID_FILE.with_suffix(".identity.json").write_text(json.dumps(identity))
    linux_process["argv"] = ["/usr/bin/sleep", "100"]

    assert daemon_cmd._read_pid() is None
