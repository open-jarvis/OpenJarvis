"""Exercise daemon state against real Uvicorn bind and shutdown behavior."""

from __future__ import annotations

import socket
from contextlib import asynccontextmanager

import httpx
import pytest
from fastapi import FastAPI

from openjarvis.cli import daemon_cmd
from openjarvis.server.daemon import DaemonServer, run_server


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(daemon_cmd, "_PID_FILE", tmp_path / "server.pid")
    monkeypatch.setattr(daemon_cmd, "_STATE_FILE", tmp_path / "server.json")
    monkeypatch.setattr(daemon_cmd, "DEFAULT_CONFIG_DIR", tmp_path)
    return tmp_path


def test_ephemeral_port_is_registered_after_startup_and_cleared(state_dir, monkeypatch):
    @asynccontextmanager
    async def lifespan(app):
        assert daemon_cmd._read_state() == {}
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    observed = []

    async def verify_running(self):
        state = daemon_cmd._read_state()
        assert state["host"] == "127.0.0.1"
        assert state["port"] > 0
        observed.append(state)
        async with httpx.AsyncClient(trust_env=False) as client:
            response = await client.get(f"http://127.0.0.1:{state['port']}/health")
        assert response.json() == {"status": "ok"}

    monkeypatch.setattr(DaemonServer, "main_loop", verify_running)
    run_server(app, host="127.0.0.1", port=0, log_level="error")

    assert len(observed) == 1
    assert daemon_cmd._read_state() == {}
    assert not (state_dir / "server.pid").exists()


def test_failed_bind_does_not_overwrite_an_existing_server(state_dir):
    daemon_cmd.record_server_state(999999, "127.0.0.1", 8899)
    before = (state_dir / "server.json").read_bytes()
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        with pytest.raises(SystemExit):
            run_server(
                FastAPI(),
                host="127.0.0.1",
                port=occupied.getsockname()[1],
                log_level="error",
            )

    assert (state_dir / "server.json").read_bytes() == before
    assert (state_dir / "server.pid").read_text() == "999999"


def test_second_live_server_cannot_replace_registered_owner(state_dir, monkeypatch):
    daemon_cmd.record_server_state(999999, "127.0.0.1", 8899)
    monkeypatch.setattr(daemon_cmd, "_pid_alive", lambda pid: True)

    with pytest.raises(RuntimeError, match="already registered"):
        run_server(FastAPI(), host="127.0.0.1", port=0, log_level="error")

    assert daemon_cmd._read_state()["pid"] == 999999
    assert (state_dir / "server.pid").read_text() == "999999"
