"""Temporary profile and owned-process browser manager tests."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

from openjarvis.browser import (
    BrowserOpenError,
    BrowserProcessManager,
    BrowserProfilePolicy,
)


def test_profile_is_temporary_owned_and_removable(tmp_path: Path) -> None:
    policy = BrowserProfilePolicy(tmp_path / "profiles")
    manager = BrowserProcessManager(
        executable=sys.executable,
        profile_policy=policy,
        command_builder=lambda profile, port, visible: [
            sys.executable,
            "-c",
            "import time;time.sleep(5)",
        ],
    )
    session = manager.create_session()
    marker = session.profile_path / ".openjarvis-browser-profile.json"
    assert marker.exists()
    assert json.loads(marker.read_text())["session_id"] == session.session_id
    policy.remove(session.profile_path, session.session_id)
    assert not session.profile_path.exists()


def test_foreign_profile_is_rejected(tmp_path: Path) -> None:
    policy = BrowserProfilePolicy(tmp_path / "profiles")
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    with pytest.raises(BrowserOpenError, match="escaped"):
        policy.validate_owned(foreign, "browser-test")


def test_repeated_start_does_not_duplicate_owned_process(tmp_path: Path) -> None:
    policy = BrowserProfilePolicy(tmp_path / "profiles")
    script = tmp_path / "control.py"
    script.write_text(
        """
import http.server, json, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body=json.dumps({'Browser':'synthetic','webSocketDebuggerUrl':'ws://x'}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def log_message(self, *args): pass
http.server.ThreadingHTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
""".strip(),
        encoding="utf-8",
    )
    manager = BrowserProcessManager(
        executable=sys.executable,
        profile_policy=policy,
        command_builder=lambda profile, port, visible: [
            sys.executable,
            str(script),
            str(port),
        ],
    )
    session = manager.create_session()
    manager.start(session)
    first_pid = session.browser_pid
    manager.start(session)
    assert session.browser_pid == first_pid
    assert manager.list_owned_pids() == (first_pid,)
    manager.close(session)
    assert manager.list_owned_pids() == ()
    assert not session.profile_path.exists()


def test_port_conflict_with_foreign_process_never_kills_foreign(tmp_path: Path) -> None:
    policy = BrowserProfilePolicy(tmp_path / "profiles")
    manager = BrowserProcessManager(
        executable=sys.executable,
        profile_policy=policy,
        command_builder=lambda profile, port, visible: [
            sys.executable,
            "-c",
            "import time;time.sleep(30)",
        ],
    )
    session = manager.create_session()
    foreign = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    foreign.bind(("127.0.0.1", session.control_port))
    foreign.listen()
    try:
        with pytest.raises(BrowserOpenError, match="did not become healthy"):
            manager.start(session, timeout=0.3)
        assert foreign.fileno() >= 0
    finally:
        manager.close(session)
        foreign.close()
