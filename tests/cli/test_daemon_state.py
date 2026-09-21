"""Daemon address bookkeeping.

`status` and `restart` used to read `config.server.{host,port}` rather than the
address the daemon actually bound to, so `jarvis start --port N` was reported
(and restarted) on the config default instead of N.
"""

from __future__ import annotations

import json
import threading

import pytest
from click.testing import CliRunner

from openjarvis.cli import daemon_cmd


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_cmd, "_PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(daemon_cmd, "_STATE_FILE", tmp_path / "server.json")
    monkeypatch.setattr(daemon_cmd, "DEFAULT_CONFIG_DIR", tmp_path)
    return tmp_path


def test_write_pid_records_bound_address(state_dir):
    daemon_cmd._write_pid(4321, "127.0.0.1", 8899)
    assert daemon_cmd._read_state() == {
        "pid": 4321,
        "host": "127.0.0.1",
        "port": 8899,
    }


def test_bound_address_prefers_recorded_over_config(state_dir):
    daemon_cmd._write_pid(4321, "127.0.0.1", 8899)
    host, port = daemon_cmd._bound_address()
    assert (host, port) == ("127.0.0.1", 8899)


def test_bound_address_falls_back_to_config(state_dir):
    from openjarvis.core.config import load_config

    config = load_config()
    host, port = daemon_cmd._bound_address()
    assert (host, port) == (config.server.host, int(config.server.port))


def test_read_state_tolerates_corrupt_file(state_dir):
    (state_dir / "server.json").write_text("{not json")
    assert daemon_cmd._read_state() == {}


def test_read_state_rejects_non_mapping(state_dir):
    (state_dir / "server.json").write_text(json.dumps([1, 2, 3]))
    assert daemon_cmd._read_state() == {}


def test_record_server_state_makes_status_findable(state_dir):
    """A launchd-supervised `serve` never calls `start`; it must still register."""
    daemon_cmd.record_server_state(999, "127.0.0.1", 8899)
    assert daemon_cmd._read_state()["port"] == 8899


def test_clear_server_state_only_removes_own_entry(state_dir):
    daemon_cmd.record_server_state(999, "127.0.0.1", 8899)
    daemon_cmd.clear_server_state(1234)  # a different process
    assert daemon_cmd._read_state()["pid"] == 999
    daemon_cmd.clear_server_state(999)
    assert daemon_cmd._read_state() == {}


def test_old_cleanup_preserves_new_pid_when_legacy_files_disagree(state_dir):
    daemon_cmd.record_server_state(999, "127.0.0.1", 8899)
    (state_dir / "server.pid").write_text("1234")

    daemon_cmd.clear_server_state(999)

    assert (state_dir / "server.pid").read_text() == "1234"
    assert not (state_dir / "server.json").exists()


def test_old_cleanup_preserves_new_address_when_legacy_files_disagree(state_dir):
    daemon_cmd.record_server_state(1234, "127.0.0.1", 8899)
    (state_dir / "server.pid").write_text("999")

    daemon_cmd.clear_server_state(999)

    assert daemon_cmd._read_state()["pid"] == 1234
    assert not (state_dir / "server.pid").exists()


def test_stale_address_is_not_used_for_another_pid(state_dir, monkeypatch):
    daemon_cmd.record_server_state(999, "127.0.0.1", 8899)
    (state_dir / "server.pid").write_text("1234")
    config = daemon_cmd.load_config()
    monkeypatch.setattr(daemon_cmd, "load_config", lambda: config)

    assert daemon_cmd._bound_address(1234) == (
        config.server.host,
        int(config.server.port),
    )


@pytest.mark.parametrize("port", ["broken", True, -1, 65536, None])
def test_invalid_address_fields_are_ignored(state_dir, port):
    (state_dir / "server.json").write_text(
        json.dumps({"pid": 999, "host": "127.0.0.1", "port": port})
    )
    assert daemon_cmd._read_state() == {}


def test_parent_cannot_replace_child_bound_port_with_requested_zero(state_dir):
    daemon_cmd.record_server_state(999, "127.0.0.1", 8899)

    daemon_cmd._write_pid(999, "127.0.0.1", 0, ready=False)

    assert daemon_cmd._read_state()["port"] == 8899
    assert daemon_cmd._read_state().get("ready", True)


def test_pending_start_does_not_claim_an_address_is_listening(state_dir, monkeypatch):
    daemon_cmd._write_pid(999, "127.0.0.1", 0, ready=False)
    monkeypatch.setattr(daemon_cmd, "_pid_alive", lambda pid: True)

    result = CliRunner().invoke(daemon_cmd.status)

    assert result.exit_code == 0
    assert "Server is starting" in result.output
    assert "URL:" not in result.output


def test_restart_passes_the_recorded_address_to_start(state_dir, monkeypatch):
    daemon_cmd.record_server_state(999, "127.0.0.1", 8899)
    monkeypatch.setattr(daemon_cmd, "_pid_alive", lambda pid: True)
    started = []
    monkeypatch.setattr(daemon_cmd.stop, "callback", lambda: None)
    monkeypatch.setattr(
        daemon_cmd.start, "callback", lambda **params: started.append(params)
    )

    result = CliRunner().invoke(daemon_cmd.restart)

    assert result.exit_code == 0
    assert started[0]["host"] == "127.0.0.1"
    assert started[0]["port"] == 8899


def test_cleanup_waits_for_in_progress_registration(state_dir, monkeypatch):
    daemon_cmd.record_server_state(999, "127.0.0.1", 8899)
    monkeypatch.setattr(daemon_cmd, "_pid_alive", lambda pid: False)
    write_started, release_write, cleared = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    write_json = daemon_cmd.secure_write_json

    def blocked_write(path, value):
        write_started.set()
        assert release_write.wait(5)
        write_json(path, value)

    def clear_old():
        daemon_cmd.clear_server_state(999)
        cleared.set()

    monkeypatch.setattr(daemon_cmd, "secure_write_json", blocked_write)
    writer = threading.Thread(
        target=daemon_cmd.record_server_state, args=(1234, "127.0.0.1", 8900)
    )
    cleanup = threading.Thread(target=clear_old)
    writer.start()
    try:
        assert write_started.wait(5)
        cleanup.start()
        assert not cleared.wait(0.05)
    finally:
        release_write.set()
        writer.join(5)
        if cleanup.ident is not None:
            cleanup.join(5)

    assert not writer.is_alive()
    assert not cleanup.is_alive()
    assert daemon_cmd._read_state()["pid"] == 1234
    assert (state_dir / "server.pid").read_text() == "1234"
