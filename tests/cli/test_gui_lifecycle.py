"""Frontend cleanup must target owned processes and release invocation hooks."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from contextlib import nullcontext
from unittest import mock

import click
import psutil
import pytest
from click.testing import CliRunner

from openjarvis.cli import daemon_cmd, gui_cmd


@pytest.fixture(autouse=True)
def frontend_state(tmp_path, monkeypatch):
    path = tmp_path / "frontend.json"
    monkeypatch.setattr(gui_cmd, "_FRONTEND_STATE_FILE", path)
    return path


def _saved_state(pid=4321, token="launch-a", identity=None):
    return {
        "pid": pid,
        "port": 5173,
        "launch_token": token,
        "process_group": pid,
        "processes": [
            {"pid": pid, "identity": identity or {"pid": pid, "created_at": 100.0}}
        ],
    }


def test_recycled_pid_is_not_signaled(frontend_state, monkeypatch):
    frontend_state.write_text(json.dumps(_saved_state()))
    process = mock.Mock(spec=psutil.Process)
    process.pid = 4321
    monkeypatch.setattr(gui_cmd.psutil, "Process", lambda pid: process)
    monkeypatch.setattr(
        gui_cmd, "_process_identity", lambda p: {"pid": p.pid, "created_at": 200.0}
    )

    assert gui_cmd.stop_frontend() is None
    process.terminate.assert_not_called()
    process.kill.assert_not_called()
    assert not frontend_state.exists()


def test_legacy_pid_only_state_is_not_authority_to_kill(frontend_state, monkeypatch):
    frontend_state.write_text(json.dumps({"pid": 4321, "port": 5173}))
    process = mock.Mock()
    monkeypatch.setattr(gui_cmd.psutil, "Process", process)

    assert gui_cmd.stop_frontend() is None
    process.assert_not_called()


@pytest.mark.parametrize("unavailable", ["permission", "metadata"])
def test_unreadable_identity_preserves_state_without_signaling(
    frontend_state, monkeypatch, unavailable
):
    saved = json.dumps(_saved_state())
    frontend_state.write_text(saved)
    process = mock.Mock(spec=psutil.Process)
    process.pid = 4321
    monkeypatch.setattr(gui_cmd.psutil, "Process", lambda pid: process)
    monkeypatch.setattr(
        gui_cmd,
        "_process_identity",
        mock.Mock(side_effect=PermissionError)
        if unavailable == "permission"
        else lambda p: None,
    )

    with pytest.raises(click.ClickException, match="saved state was kept"):
        gui_cmd.stop_frontend()
    process.terminate.assert_not_called()
    assert frontend_state.read_text() == saved


def test_refresh_preserves_identity_when_process_inspection_is_denied(
    frontend_state, monkeypatch
):
    process = mock.Mock(spec=subprocess.Popen)
    process.pid = 4321
    process.poll.return_value = 0
    owner = gui_cmd._FrontendOwner(process, 5173)
    owner.state = _saved_state()
    owner.registered = True
    saved = json.dumps(owner.state)
    frontend_state.write_text(saved)
    recorded = mock.Mock(spec=psutil.Process)
    recorded.pid = 4321
    monkeypatch.setattr(gui_cmd.psutil, "Process", lambda pid: recorded)
    monkeypatch.setattr(
        gui_cmd, "_process_identity", mock.Mock(side_effect=psutil.AccessDenied(4321))
    )

    owner.refresh()

    assert owner.state["processes"] == json.loads(saved)["processes"]
    assert frontend_state.read_text() == saved


@pytest.mark.parametrize("later", ["denied", "recycled"])
def test_refresh_does_not_lose_or_adopt_an_owner_when_identity_changes_mid_read(
    frontend_state, monkeypatch, later
):
    process = mock.Mock(spec=subprocess.Popen)
    process.pid = 4321
    process.poll.return_value = 0
    owner = gui_cmd._FrontendOwner(process, 5173)
    owner.state = _saved_state()
    owner.registered = True
    saved = json.dumps(owner.state)
    frontend_state.write_text(saved)
    recorded = mock.Mock(spec=psutil.Process)
    recorded.pid = 4321
    recorded.is_running.return_value = True
    recorded.status.return_value = psutil.STATUS_RUNNING
    recorded.children.return_value = []
    monkeypatch.setattr(gui_cmd.psutil, "Process", lambda pid: recorded)
    original = owner.state["processes"][0]["identity"]
    changed = (
        PermissionError() if later == "denied" else {**original, "created_at": 200.0}
    )
    monkeypatch.setattr(
        gui_cmd, "_process_identity", mock.Mock(side_effect=[original, changed])
    )

    owner.refresh()

    if later == "denied":
        assert owner.state["processes"] == json.loads(saved)["processes"]
        assert frontend_state.read_text() == saved
    else:
        assert owner.state["processes"] == []


def test_stop_preserves_record_if_identity_becomes_unknown_after_signaling(
    frontend_state, monkeypatch
):
    saved = json.dumps(_saved_state())
    frontend_state.write_text(saved)
    process = mock.Mock(spec=psutil.Process)
    process.pid = 4321
    process.is_running.return_value = True
    process.status.return_value = psutil.STATUS_RUNNING
    process.children.return_value = []
    monkeypatch.setattr(gui_cmd.psutil, "Process", lambda pid: process)
    monkeypatch.setattr(
        gui_cmd,
        "_process_identity",
        mock.Mock(
            side_effect=[_saved_state()["processes"][0]["identity"], PermissionError()]
        ),
    )
    monkeypatch.setattr(gui_cmd.psutil, "wait_procs", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(gui_cmd.os, "getpgid", lambda pid: 9999, raising=False)

    with pytest.raises(click.ClickException, match="saved state was kept"):
        gui_cmd.stop_frontend()

    assert frontend_state.read_text() == saved


@pytest.mark.parametrize("unreadable", [False, True])
def test_register_cannot_replace_another_live_or_unverifiable_owner(
    frontend_state, monkeypatch, unreadable
):
    saved = json.dumps(_saved_state())
    frontend_state.write_text(saved)
    processes = {}
    for pid in (4321, 9876):
        process = mock.Mock(spec=psutil.Process)
        process.pid = pid
        process.is_running.return_value = True
        process.status.return_value = psutil.STATUS_RUNNING
        process.children.return_value = []
        processes[pid] = process
    monkeypatch.setattr(gui_cmd.psutil, "Process", processes.__getitem__)

    def identity(process):
        if process.pid == 4321 and unreadable:
            raise psutil.AccessDenied(4321)
        return {"pid": process.pid, "created_at": 100.0}

    monkeypatch.setattr(gui_cmd, "_process_identity", identity)
    child = mock.Mock(spec=subprocess.Popen)
    child.pid = 9876
    child.poll.return_value = None
    owner = gui_cmd._FrontendOwner(child, 5180)

    with pytest.raises(click.ClickException, match="Another frontend"):
        owner.register()

    assert not owner.registered
    assert frontend_state.read_text() == saved


def test_reclaim_uses_its_snapshot_when_another_port_registers(
    frontend_state, monkeypatch
):
    initial = _saved_state()
    replacement = {**_saved_state(pid=9876, token="replacement"), "port": 5180}
    frontend_state.write_text(json.dumps(replacement))
    monkeypatch.setattr(
        gui_cmd, "_read_frontend_state", mock.Mock(side_effect=[initial, replacement])
    )
    terminate = mock.Mock(return_value=True)
    monkeypatch.setattr(gui_cmd, "_terminate_frontend", terminate)
    monkeypatch.setattr(gui_cmd, "_port_free", lambda port: True)

    assert gui_cmd._reclaim_port(5173)

    terminate.assert_called_once_with(initial)
    assert json.loads(frontend_state.read_text()) == replacement


def test_linux_identity_uses_boot_id_and_start_ticks(monkeypatch):
    process = mock.Mock(spec=psutil.Process)
    process.pid = 4321
    process.create_time.side_effect = AssertionError("wall-clock epoch is not identity")
    expected = {"pid": 4321, "boot_id": "boot-a", "start_ticks": 12345}
    monkeypatch.setattr(gui_cmd.sys, "platform", "linux")
    monkeypatch.setattr(daemon_cmd, "_linux_process_identity", lambda pid: expected)

    assert gui_cmd._process_identity(process) == expected
    process.create_time.assert_not_called()


def test_cleanup_is_idempotent_and_cannot_clear_a_later_launch(
    frontend_state, monkeypatch
):
    process = mock.Mock(spec=subprocess.Popen)
    process.pid = 4321
    owner = gui_cmd._FrontendOwner(process, 5173)
    frontend_state.write_text(json.dumps(_saved_state(token="new-launch")))
    terminate = mock.Mock(return_value=True)
    monkeypatch.setattr(gui_cmd, "_terminate_frontend", terminate)

    owner.shutdown()
    owner.shutdown()

    terminate.assert_called_once()
    assert json.loads(frontend_state.read_text())["launch_token"] == "new-launch"


def test_refresh_does_not_overwrite_another_launch(frontend_state, monkeypatch):
    process = mock.Mock(spec=subprocess.Popen)
    process.pid = 4321
    owner = gui_cmd._FrontendOwner(process, 5173)
    owner.registered = True
    frontend_state.write_text(json.dumps(_saved_state(token="new-launch")))
    observed = mock.Mock(spec=psutil.Process)
    observed.pid = 4321
    observed.is_running.return_value = True
    monkeypatch.setattr(
        gui_cmd, "_frontend_processes", lambda *args, **kwargs: [observed]
    )
    monkeypatch.setattr(
        gui_cmd, "_process_identity", lambda p: {"pid": p.pid, "created_at": 100.0}
    )

    owner.refresh()

    assert json.loads(frontend_state.read_text())["launch_token"] == "new-launch"


def _is_running(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


@pytest.mark.parametrize("launcher_exits", [False, True])
def test_stop_cleans_up_real_descendants_even_after_launcher_exit(
    tmp_path, frontend_state, launcher_exits
):
    child_pid_file = tmp_path / "child.pid"
    parent_code = (
        "import pathlib, subprocess, sys, time\n"
        "child = subprocess.Popen([sys.executable, '-c', "
        "'import time; time.sleep(60)'])\n"
        "pathlib.Path(sys.argv[1]).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    options = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if sys.platform == "win32"
        else {"start_new_session": True}
    )
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code, str(child_pid_file)], **options
    )
    child = None
    owner = gui_cmd._FrontendOwner(parent, 5173)
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                child = psutil.Process(int(child_pid_file.read_text()))
                break
            except (FileNotFoundError, ValueError):
                time.sleep(0.02)
        assert child is not None
        owner.register()
        assert child.pid in {record["pid"] for record in owner.state["processes"]}
        if launcher_exits:
            parent.terminate()
            parent.wait(timeout=5)
            assert _is_running(child)

        assert gui_cmd.stop_frontend() == parent.pid

        parent.wait(timeout=5)
        assert not _is_running(child)
        assert not frontend_state.exists()
    finally:
        if child is not None and _is_running(child):
            child.kill()
            child.wait(timeout=5)
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)


@pytest.fixture
def gui_invocation(tmp_path, monkeypatch):
    process = mock.Mock(spec=subprocess.Popen)
    process.pid = 4321
    process.poll.return_value = None
    process.wait.return_value = 0
    owner = mock.Mock()
    monkeypatch.setattr(gui_cmd, "_frontend_dir", lambda: tmp_path)
    monkeypatch.setattr(gui_cmd, "_check_frontend_port", lambda port: None)
    monkeypatch.setattr(gui_cmd, "_ensure_frontend_dependencies", lambda *args: None)
    monkeypatch.setattr(gui_cmd.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(gui_cmd.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(gui_cmd, "_FrontendOwner", lambda *args: owner)
    monkeypatch.setattr(gui_cmd, "_api_healthy", lambda *args: False)
    monkeypatch.setattr(gui_cmd, "_wait_for_port", lambda *args, **kwargs: True)
    monkeypatch.setattr(gui_cmd.webbrowser, "open", lambda url: True)
    return process, owner


@pytest.mark.parametrize("failure", [None, "register", "startup", "browser"])
def test_invocation_unregisters_exit_hook_and_restores_signals(
    gui_invocation, monkeypatch, failure
):
    process, owner = gui_invocation
    if failure == "register":
        owner.register.side_effect = RuntimeError("cannot record state")
    elif failure == "startup":
        monkeypatch.setattr(gui_cmd, "_wait_for_port", lambda *args, **kwargs: False)
    elif failure == "browser":
        monkeypatch.setattr(
            gui_cmd.webbrowser, "open", mock.Mock(side_effect=RuntimeError)
        )
    previous = signal.getsignal(signal.SIGTERM)
    register, unregister = mock.Mock(), mock.Mock()
    monkeypatch.setattr(gui_cmd.atexit, "register", register)
    monkeypatch.setattr(gui_cmd.atexit, "unregister", unregister)

    result = CliRunner().invoke(gui_cmd.gui, ["--no-server"])

    assert result.exit_code == (0 if failure is None else 1)
    owner.shutdown.assert_called_once()
    unregister.assert_called_once_with(register.call_args.args[0])
    assert signal.getsignal(signal.SIGTERM) is previous


def test_api_monitor_arms_when_slow_backend_first_becomes_healthy(
    gui_invocation, monkeypatch
):
    process, owner = gui_invocation
    process.wait.side_effect = [subprocess.TimeoutExpired("npm", 5)] * 4 + [0]
    monkeypatch.setattr(
        gui_cmd,
        "_api_healthy",
        mock.Mock(side_effect=[False, True, False, False, False]),
    )
    monkeypatch.setattr(gui_cmd, "_daemon_pid_alive", lambda port: False)

    result = CliRunner().invoke(gui_cmd.gui, ["--no-server", "--no-browser"])

    assert result.exit_code == 1
    assert "API server stopped" in result.output
    owner.shutdown.assert_called_once()


def test_api_failure_before_first_healthy_probe_does_not_leave_gui_running(
    gui_invocation, monkeypatch
):
    process, owner = gui_invocation
    process.wait.side_effect = [subprocess.TimeoutExpired("npm", 5)] * 3 + [0]
    monkeypatch.setattr(
        gui_cmd.subprocess, "run", mock.Mock(return_value=mock.Mock(returncode=0))
    )
    monkeypatch.setattr(gui_cmd, "_daemon_pid_alive", lambda port: False)

    result = CliRunner().invoke(gui_cmd.gui, ["--no-browser"])

    assert result.exit_code == 1
    assert "failed to start" in result.output
    owner.shutdown.assert_called_once()


@pytest.mark.parametrize("registered", [False, True])
def test_automatic_api_reuse_requires_verified_daemon_ownership(
    gui_invocation, monkeypatch, registered
):
    _, owner = gui_invocation
    monkeypatch.setattr(gui_cmd, "_api_healthy", lambda *args: True)
    ownership = mock.Mock(return_value=registered)
    monkeypatch.setattr(gui_cmd, "_daemon_pid_alive", ownership)
    run = mock.Mock(return_value=mock.Mock(returncode=0))
    monkeypatch.setattr(gui_cmd.subprocess, "run", run)

    result = CliRunner().invoke(gui_cmd.gui, ["--no-browser"])

    ownership.assert_called_once_with(8000, require_ready=True)
    run.assert_not_called()
    if registered:
        assert result.exit_code == 0
        assert "Reusing the API server" in result.output
        owner.register.assert_called_once()
    else:
        assert result.exit_code == 1
        assert "unregistered service" in result.output
        owner.register.assert_not_called()


def test_explicit_no_server_allows_an_externally_managed_backend(
    gui_invocation, monkeypatch
):
    _, owner = gui_invocation
    monkeypatch.setattr(gui_cmd, "_api_healthy", lambda *args: True)
    ownership = mock.Mock(return_value=False)
    monkeypatch.setattr(gui_cmd, "_daemon_pid_alive", ownership)

    result = CliRunner().invoke(gui_cmd.gui, ["--no-server", "--no-browser"])

    assert result.exit_code == 0
    ownership.assert_not_called()
    owner.register.assert_called_once()


def test_pending_daemon_is_monitored_but_not_automatically_reused(monkeypatch):
    monkeypatch.setattr(daemon_cmd, "_state_lock", lambda: nullcontext())
    monkeypatch.setattr(
        daemon_cmd, "_read_state", lambda: {"pid": 4321, "port": 8000, "ready": False}
    )
    monkeypatch.setattr(daemon_cmd, "_read_pid_unlocked", lambda: 4321)

    assert gui_cmd._daemon_pid_alive(8000)
    assert not gui_cmd._daemon_pid_alive(8000, require_ready=True)


def test_daemon_stop_can_stop_frontend_without_a_backend(monkeypatch):
    monkeypatch.setattr(gui_cmd, "stop_frontend", lambda: 4321)
    monkeypatch.setattr(daemon_cmd, "_read_pid", lambda: None)

    result = CliRunner().invoke(daemon_cmd.stop)

    assert result.exit_code == 0
    assert "Frontend stopped" in result.output
