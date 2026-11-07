"""Tests for /v1/mcp/servers against a real local Streamable-HTTP MCP server."""

from __future__ import annotations

import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.mcp.loader import (  # noqa: E402
    load_mcp_tools_from_config,
    resolve_effective_mcp_servers,
)
from openjarvis.mcp.store import MCPServerStore  # noqa: E402
from openjarvis.server.mcp_routes import create_mcp_router  # noqa: E402

SECRET = "sk-test-very-secret-token-123"

_TOOLS = [
    {
        "name": "echo",
        "description": "Echo text back",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    {"name": "add", "description": "Add numbers", "inputSchema": {"type": "object"}},
]


class _FakeMCPHandler(BaseHTTPRequestHandler):
    """Minimal MCP Streamable HTTP server: initialize + tools/list + auth."""

    expected_header = "Authorization"
    expected_value: str | None = f"Bearer {SECRET}"
    seen_headers: list[dict[str, str]] = []

    def log_message(self, *args):  # silence test output
        pass

    def do_POST(self):  # noqa: N802
        self.seen_headers.append(dict(self.headers))
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if (
            self.expected_value is not None
            and self.headers.get(self.expected_header) != self.expected_value
        ):
            self.send_response(401)
            self.end_headers()
            return
        if "id" not in body:  # notification
            self.send_response(202)
            self.end_headers()
            return
        if body["method"] == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0"},
            }
        elif body["method"] == "tools/list":
            result = {"tools": _TOOLS}
        else:
            result = {}
        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Mcp-Session-Id", "s1")
        self.end_headers()
        self.wfile.write(payload.encode())


@pytest.fixture
def fake_mcp():
    handler = type("Handler", (_FakeMCPHandler,), {"seen_headers": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(
            url=f"http://127.0.0.1:{server.server_port}/mcp", handler=handler
        )
    finally:
        server.shutdown()
        server.server_close()


def _config(tmp_path, servers=""):
    return SimpleNamespace(
        tools=SimpleNamespace(mcp=SimpleNamespace(enabled=True, servers=servers)),
        _config_dir=tmp_path,
    )


@pytest.fixture
def env(tmp_path):
    config = _config(tmp_path)
    store = MCPServerStore(tmp_path / "mcp")
    app = FastAPI()
    app.include_router(create_mcp_router(config=config, store=store))
    return SimpleNamespace(
        client=TestClient(app), store=store, config=config, tmp=tmp_path
    )


def _http_payload(url, **extra):
    return {
        "name": "Fake",
        "transport": "http",
        "url": url,
        "auth_type": "bearer",
        "token": SECRET,
        **extra,
    }


def test_create_list_never_returns_token(env, fake_mcp):
    res = env.client.post("/v1/mcp/servers", json=_http_payload(fake_mcp.url))
    assert res.status_code == 201
    assert SECRET not in res.text
    server = res.json()["server"]
    assert server["has_token"] is True
    assert res.json()["restart_required"] is True

    listing = env.client.get("/v1/mcp/servers")
    assert SECRET not in listing.text
    assert [s["name"] for s in listing.json()["servers"]] == ["Fake"]

    # Secrets live in their own owner-only file, keyed by server id.
    secrets_path = env.tmp / "mcp" / "secrets.json"
    assert stat.S_IMODE(os.stat(secrets_path).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(env.tmp / "mcp").st_mode) == 0o700
    assert json.loads(secrets_path.read_text())["secrets"][server["id"]] == {
        "token": SECRET
    }
    assert SECRET not in (env.tmp / "mcp" / "servers.json").read_text()


def test_validation_error_does_not_echo_token(env):
    bad = {"name": "", "transport": "http", "url": "ftp://x", "token": SECRET}
    res = env.client.post("/v1/mcp/servers", json=bad)
    assert res.status_code == 422
    assert SECRET not in res.text

    wrong_type = {**bad, "name": "x", "url": "http://h", "token": [SECRET]}
    res = env.client.post("/v1/mcp/servers", json=wrong_type)
    assert res.status_code == 422
    assert SECRET not in res.text

    res = env.client.post(
        "/v1/mcp/servers",
        content=json.dumps(bad) + "{",
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 422
    assert SECRET not in res.text


def test_rejects_non_json_content_type(env):
    res = env.client.post(
        "/v1/mcp/servers",
        content=json.dumps({"name": "x", "transport": "stdio", "command": "x"}),
        headers={"Content-Type": "text/plain"},
    )
    assert res.status_code == 415
    assert env.store.list_servers() == []


def test_test_endpoint_lists_tools_with_filters(env, fake_mcp):
    created = env.client.post(
        "/v1/mcp/servers",
        json=_http_payload(fake_mcp.url, exclude_tools=["add"]),
    ).json()["server"]
    res = env.client.post(f"/v1/mcp/servers/{created['id']}/test")
    body = res.json()
    assert body["ok"] is True
    assert {t["name"]: t["active"] for t in body["tools"]} == {
        "echo": True,
        "add": False,
    }
    assert fake_mcp.handler.seen_headers[0]["Authorization"] == f"Bearer {SECRET}"


def test_test_error_never_contains_token(env, fake_mcp):
    payload = _http_payload(fake_mcp.url + f"?key={SECRET}", token="wrong-" + SECRET)
    res = env.client.post("/v1/mcp/servers/test", json=payload)
    body = res.json()
    assert body["ok"] is False
    assert body["error"].startswith("The server rejected the credentials (HTTP 401)")
    assert "Error" not in body["error"]
    assert SECRET not in res.text


def _unused_port():
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _NotMCPHandler(BaseHTTPRequestHandler):
    """Answers 404 under /missing and plain non-JSON-RPC text elsewhere."""

    def log_message(self, *args):
        pass

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path.startswith("/missing"):
            self.send_response(404)
            self.end_headers()
            return
        body = b"hello"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def not_mcp_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _NotMCPHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (
            lambda base: _http_payload(f"http://127.0.0.1:{_unused_port()}/mcp"),
            "Could not reach the server.",
        ),
        (lambda base: _http_payload(f"{base}/missing/mcp"), "No MCP endpoint"),
        (
            lambda base: _http_payload(f"{base}/mcp"),
            "Connected, but the server did not respond as an MCP server.",
        ),
        (
            lambda base: {
                "name": "Missing",
                "transport": "stdio",
                "command": "openjarvis-no-such-mcp-command",
            },
            "Could not start openjarvis-no-such-mcp-command: command not found.",
        ),
    ],
)
def test_test_errors_are_actionable(env, not_mcp_url, payload, expected):
    body = env.client.post("/v1/mcp/servers/test", json=payload(not_mcp_url)).json()
    assert body["ok"] is False
    assert body["error"].startswith(expected)
    assert "Error:" not in body["error"]
    assert SECRET not in body["error"]


def test_custom_auth_header(env, fake_mcp):
    fake_mcp.handler.expected_header = "X-Api-Key"
    fake_mcp.handler.expected_value = SECRET
    payload = _http_payload(fake_mcp.url, auth_type="header", auth_header="X-Api-Key")
    res = env.client.post("/v1/mcp/servers/test", json=payload)
    assert res.json()["ok"] is True
    assert "Authorization" not in fake_mcp.handler.seen_headers[-1]

    bad = {**payload, "auth_header": "Content-Type"}
    assert env.client.post("/v1/mcp/servers", json=bad).status_code == 422


def test_update_keeps_or_clears_token(env, fake_mcp):
    sid = env.client.post("/v1/mcp/servers", json=_http_payload(fake_mcp.url)).json()[
        "server"
    ]["id"]
    update = _http_payload(fake_mcp.url, name="Renamed", enabled=False)
    update.pop("token")
    res = env.client.put(f"/v1/mcp/servers/{sid}", json=update)
    assert res.json()["server"]["name"] == "Renamed"
    assert res.json()["server"]["has_token"] is True
    assert env.store.token(sid) == SECRET

    res = env.client.put(f"/v1/mcp/servers/{sid}", json={**update, "token": ""})
    assert res.json()["server"]["has_token"] is False

    assert env.client.put("/v1/mcp/servers/nope", json=update).status_code == 404


def test_delete_removes_secret(env, fake_mcp):
    sid = env.client.post("/v1/mcp/servers", json=_http_payload(fake_mcp.url)).json()[
        "server"
    ]["id"]
    assert env.client.delete(f"/v1/mcp/servers/{sid}").json()["deleted"] is True
    assert env.store.token(sid) is None
    assert env.client.get("/v1/mcp/servers").json()["restart_required"] is False
    assert env.client.delete(f"/v1/mcp/servers/{sid}").status_code == 404


def test_config_toml_servers_are_read_only(tmp_path, fake_mcp):
    servers = json.dumps(
        [
            {
                "name": "from-toml",
                "url": fake_mcp.url + "?k=secretq",
                "token": SECRET,
                "command": "",
            },
            {"name": "cli", "command": "my-mcp", "args": ["--api-key", SECRET]},
        ]
    )
    config = _config(tmp_path, servers)
    app = FastAPI()
    app.include_router(create_mcp_router(config=config))
    client = TestClient(app)

    listing = client.get("/v1/mcp/servers")
    assert SECRET not in listing.text
    assert "secretq" not in listing.text
    toml_servers = listing.json()["config_servers"]
    assert [s["read_only"] for s in toml_servers] == [True, True]
    assert toml_servers[1]["args"] == []

    tested = client.post("/v1/mcp/servers/config-0/test").json()
    assert tested["ok"] is True
    assert client.post("/v1/mcp/servers/config-9/test").status_code == 404


def test_runtime_loads_gui_and_toml_servers(env, fake_mcp):
    env.client.post(
        "/v1/mcp/servers", json=_http_payload(fake_mcp.url, include_tools=["echo"])
    )
    env.client.post(
        "/v1/mcp/servers",
        json=_http_payload(fake_mcp.url, name="Off", enabled=False),
    )
    env.config.tools.mcp.servers = json.dumps(
        [{"name": "toml", "url": fake_mcp.url, "token": SECRET}]
    )
    servers = resolve_effective_mcp_servers(env.config)
    assert [s["name"] for s in servers] == ["toml", "Fake"]

    tools, clients = load_mcp_tools_from_config(env.config.tools.mcp, servers=servers)
    try:
        assert sorted(t.spec.name for t in tools) == ["add", "echo", "echo"]
    finally:
        for client in clients:
            client.close()

    env.config.tools.mcp.enabled = False
    assert resolve_effective_mcp_servers(env.config) == []


def test_stdio_validation(env):
    res = env.client.post(
        "/v1/mcp/servers", json={"name": "s", "transport": "stdio", "command": ""}
    )
    assert res.status_code == 422
    res = env.client.post(
        "/v1/mcp/servers",
        json={
            "name": "s",
            "transport": "stdio",
            "command": "my-mcp",
            "args": ["--port", "1"],
        },
    )
    server = res.json()["server"]
    assert (server["command"], server["args"], server["url"]) == (
        "my-mcp",
        ["--port", "1"],
        None,
    )


_STDIO_SERVER = """
import json, os, sys
for line in sys.stdin:
    req = json.loads(line)
    if "id" not in req:
        continue
    if req["method"] == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "env", "version": "1"}}
    elif req["method"] == "tools/list":
        ok = os.environ.get("FAKE_KEY") == os.environ.get("EXPECTED")
        name = "env_ok" if ok else "env_missing"
        result = {"tools": [{"name": name, "description": "",
                             "inputSchema": {"type": "object"}}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}),
          flush=True)
"""


def test_stdio_env_secrets_are_write_only(env, tmp_path, monkeypatch):
    script = tmp_path / "env_server.py"
    script.write_text(_STDIO_SERVER)
    monkeypatch.setenv("EXPECTED", SECRET)
    payload = {
        "name": "env",
        "transport": "stdio",
        "command": sys.executable,
        "args": [str(script)],
        "env_names": ["FAKE_KEY", "OTHER"],
        "env": {"FAKE_KEY": SECRET},
    }
    res = env.client.post("/v1/mcp/servers", json=payload)
    assert res.status_code == 201
    assert SECRET not in res.text
    server = res.json()["server"]
    assert server["env_names"] == ["FAKE_KEY", "OTHER"]
    assert server["env_set"] == ["FAKE_KEY"]
    assert SECRET not in (env.tmp / "mcp" / "servers.json").read_text()
    assert SECRET not in env.client.get("/v1/mcp/servers").text

    sid = server["id"]
    tools = env.client.post(f"/v1/mcp/servers/{sid}/test").json()["tools"]
    assert [t["name"] for t in tools] == ["env_ok"]

    # A draft test reuses the stored value when the draft omits it.
    draft = {**payload, "id": sid}
    draft.pop("env")
    tools = env.client.post("/v1/mcp/servers/test", json=draft).json()["tools"]
    assert [t["name"] for t in tools] == ["env_ok"]

    # Omitted values are kept; "" clears; dropped names are removed.
    update = {**payload, "env": {"OTHER": "x"}}
    res = env.client.put(f"/v1/mcp/servers/{sid}", json=update)
    assert res.json()["server"]["env_set"] == ["FAKE_KEY", "OTHER"]
    update = {**payload, "env_names": ["OTHER"], "env": {"OTHER": ""}}
    res = env.client.put(f"/v1/mcp/servers/{sid}", json=update)
    assert res.json()["server"]["env_set"] == []
    assert env.store.env(sid) == {}

    runtime = env.store.runtime_configs()
    assert "env" not in runtime[0]


def test_env_validation_does_not_echo_values(env):
    base = {"name": "s", "transport": "stdio", "command": "x"}
    res = env.client.post(
        "/v1/mcp/servers",
        json={**base, "env_names": ["A"], "env": {"B": SECRET}},
    )
    assert res.status_code == 422
    assert SECRET not in res.text
    res = env.client.post("/v1/mcp/servers", json={**base, "env_names": ["1BAD"]})
    assert res.status_code == 422
