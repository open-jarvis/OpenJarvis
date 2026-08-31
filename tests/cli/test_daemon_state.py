"""Daemon address bookkeeping.

`status` and `restart` used to read `config.server.{host,port}` rather than the
address the daemon actually bound to, so `jarvis start --port N` was reported
(and restarted) on the config default instead of N.
"""

from __future__ import annotations

import json

import pytest

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
