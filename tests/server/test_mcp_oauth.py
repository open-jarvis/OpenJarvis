"""OAuth sign-in for MCP servers against a local fake authorization server."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.mcp.store import MCPServerStore  # noqa: E402
from openjarvis.server.mcp_routes import create_mcp_router  # noqa: E402

CLIENT_SECRET = "client-secret-for-tests-987"


class _FakeAuth:
    """Authorization server + protected MCP server on one port."""

    def __init__(self, *, dcr: bool) -> None:
        self.dcr = dcr
        self.codes: dict[str, dict] = {}
        self.access: set[str] = set()
        self.refresh: set[str] = set()
        self.token_requests: list[dict] = []
        self.counter = 0
        self.base = ""
        self.forbidden = False
        # Answer with a valid JSON-RPC result but HTTP 403, as Google does.
        self.result_with_403 = False


def _handler(fake: _FakeAuth):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, payload, headers=None):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/.well-known/oauth-protected-resource/mcp":
                return self._json(
                    200,
                    {
                        "resource": f"{fake.base}/mcp",
                        "authorization_servers": [fake.base],
                        "scopes_supported": ["read", "write"],
                    },
                )
            if url.path == "/.well-known/oauth-authorization-server":
                meta = {
                    "issuer": fake.base,
                    "authorization_endpoint": f"{fake.base}/authorize",
                    "token_endpoint": f"{fake.base}/token",
                    "code_challenge_methods_supported": ["S256"],
                }
                if fake.dcr:
                    meta["registration_endpoint"] = f"{fake.base}/register"
                return self._json(200, meta)
            if url.path == "/authorize":
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                fake.counter += 1
                code = f"code-{fake.counter}"
                fake.codes[code] = q
                self.send_response(302)
                self.send_header(
                    "Location", f"{q['redirect_uri']}?code={code}&state={q['state']}"
                )
                self.end_headers()
                return None
            return self._json(404, {})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode()
            path = urlparse(self.path).path
            if path == "/register":
                return self._json(201, {"client_id": "dyn-client"})
            if path == "/token":
                form = {k: v[0] for k, v in parse_qs(raw).items()}
                fake.token_requests.append(form)
                fake.counter += 1
                if form["grant_type"] == "authorization_code":
                    req = fake.codes.pop(form["code"], None)
                    digest = hashlib.sha256(form["code_verifier"].encode()).digest()
                    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
                    if (
                        req is None
                        or req["code_challenge"] != challenge
                        or req["redirect_uri"] != form["redirect_uri"]
                        or req["client_id"] != form["client_id"]
                    ):
                        return self._json(400, {"error": "invalid_grant"})
                elif form["grant_type"] == "refresh_token":
                    if form["refresh_token"] not in fake.refresh:
                        return self._json(400, {"error": "invalid_grant"})
                access = f"access-{fake.counter}"
                refresh = f"refresh-{fake.counter}"
                fake.access.add(access)
                fake.refresh.add(refresh)
                return self._json(
                    200,
                    {
                        "access_token": access,
                        "refresh_token": refresh,
                        "expires_in": 3600,
                        "token_type": "Bearer",
                    },
                )
            if path == "/mcp":
                auth = self.headers.get("Authorization", "")
                if auth.removeprefix("Bearer ") not in fake.access:
                    meta = f"{fake.base}/.well-known/oauth-protected-resource/mcp"
                    return self._json(
                        401,
                        {},
                        {"WWW-Authenticate": f'Bearer resource_metadata="{meta}"'},
                    )
                if fake.forbidden:
                    return self._json(
                        403,
                        {
                            "error": {
                                "code": 403,
                                "message": "Gmail MCP API has not been used in "
                                f"project 1 before or it is disabled. {auth}",
                                "status": "PERMISSION_DENIED",
                            }
                        },
                    )
                req = json.loads(raw)
                if "id" not in req:
                    self.send_response(202)
                    self.end_headers()
                    return None
                result = (
                    {"tools": [{"name": "inbox", "description": "", "inputSchema": {}}]}
                    if req["method"] == "tools/list"
                    else {"protocolVersion": "2025-06-18", "capabilities": {}}
                )
                status = 403 if fake.result_with_403 else 200
                return self._json(
                    status, {"jsonrpc": "2.0", "id": req["id"], "result": result}
                )
            return self._json(404, {})

    return H


def _serve(dcr: bool):
    fake = _FakeAuth(dcr=dcr)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    fake.base = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return fake, server


@pytest.fixture
def dcr_server():
    fake, server = _serve(dcr=True)
    yield fake
    server.shutdown()


@pytest.fixture
def manual_server():
    fake, server = _serve(dcr=False)
    yield fake
    server.shutdown()


@pytest.fixture
def env(tmp_path):
    config = SimpleNamespace(
        tools=SimpleNamespace(
            mcp=SimpleNamespace(enabled=True, servers="", oauth_redirect_uri="")
        ),
        _config_dir=tmp_path,
    )
    store = MCPServerStore(tmp_path / "mcp")
    app = FastAPI()
    app.include_router(create_mcp_router(config=config, store=store))
    return SimpleNamespace(client=TestClient(app), store=store, tmp=tmp_path)


def _create(env, fake, **extra):
    res = env.client.post(
        "/v1/mcp/servers",
        json={
            "name": "Mail",
            "transport": "http",
            "url": f"{fake.base}/mcp",
            "auth_type": "oauth",
            **extra,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["server"]


def _sign_in(env, sid):
    res = env.client.post(f"/v1/mcp/servers/{sid}/oauth/start")
    assert res.status_code == 200, res.text
    auth_url = res.json()["authorization_url"]
    # Play the user's browser: the fake server approves and redirects.
    redirect = httpx.get(auth_url, follow_redirects=False).headers["location"]
    target = urlparse(redirect)
    assert target.path == "/v1/mcp/oauth/callback"
    return auth_url, env.client.get(f"{target.path}?{target.query}")


def test_dynamic_registration_sign_in_refresh_and_sign_out(env, dcr_server):
    server = _create(env, dcr_server, oauth_auth_params={"prompt": "consent"})
    sid = server["id"]
    assert server["oauth_status"] == "signed_out"
    failed = env.client.post(f"/v1/mcp/servers/{sid}/test").json()
    assert failed == {
        "ok": False,
        "error": "Not signed in. Sign in to this server first.",
    }

    auth_url, page = _sign_in(env, sid)
    query = parse_qs(urlparse(auth_url).query)
    assert query["client_id"] == ["dyn-client"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["resource"] == [f"{dcr_server.base}/mcp"]
    assert query["scope"] == ["read write"]
    assert query["prompt"] == ["consent"]
    assert query["redirect_uri"] == ["http://testserver/v1/mcp/oauth/callback"]
    assert page.status_code == 200
    assert "Signed in" in page.text
    assert "access-" not in page.text and "refresh-" not in page.text

    listing = env.client.get("/v1/mcp/servers")
    assert listing.json()["servers"][0]["oauth_status"] == "connected"
    assert "access-" not in listing.text and "refresh-" not in listing.text
    assert listing.json()["restart_required"] is True

    tools = env.client.post(f"/v1/mcp/servers/{sid}/test").json()
    assert [t["name"] for t in tools["tools"]] == ["inbox"]

    # An expired access token is refreshed before the request.
    tokens = env.store.oauth_tokens(sid)
    env.store.set_oauth_tokens(sid, {**tokens, "expires_at": time.time() - 10})
    assert env.client.post(f"/v1/mcp/servers/{sid}/test").json()["ok"] is True
    assert dcr_server.token_requests[-1]["grant_type"] == "refresh_token"
    assert env.store.oauth_tokens(sid)["access_token"] != tokens["access_token"]

    # A revoked access token is refreshed after the 401.
    dcr_server.access.clear()
    assert env.client.post(f"/v1/mcp/servers/{sid}/test").json()["ok"] is True

    res = env.client.post(f"/v1/mcp/servers/{sid}/oauth/sign-out")
    assert res.json()["signed_out"] is True
    assert env.store.oauth_tokens(sid) is None
    assert (
        env.client.get("/v1/mcp/servers").json()["servers"][0]["oauth_status"]
        == "signed_out"
    )


def test_state_is_single_use_and_checked(env, dcr_server):
    sid = _create(env, dcr_server)["id"]
    res = env.client.post(f"/v1/mcp/servers/{sid}/oauth/start")
    redirect = httpx.get(
        res.json()["authorization_url"], follow_redirects=False
    ).headers["location"]
    target = urlparse(redirect)
    forged = env.client.get(f"{target.path}?code=x&state=forged")
    assert forged.status_code == 400
    assert "expired" in forged.text
    assert env.client.get(f"{target.path}?{target.query}").status_code == 200
    replay = env.client.get(f"{target.path}?{target.query}")
    assert replay.status_code == 400


def test_user_supplied_client_is_required_without_registration(env, manual_server):
    sid = _create(env, manual_server)["id"]
    res = env.client.post(f"/v1/mcp/servers/{sid}/oauth/start")
    assert res.status_code == 400
    assert "OAuth client you create yourself" in res.json()["detail"]

    server = _create(
        env,
        manual_server,
        oauth_client_id="my-client",
        oauth_client_secret=CLIENT_SECRET,
        oauth_scopes=["read"],
    )
    assert server["has_client_secret"] is True
    assert CLIENT_SECRET not in env.client.get("/v1/mcp/servers").text
    assert CLIENT_SECRET not in (env.tmp / "mcp" / "servers.json").read_text()
    auth_url, page = _sign_in(env, server["id"])
    assert parse_qs(urlparse(auth_url).query)["scope"] == ["read"]
    assert page.status_code == 200
    assert manual_server.token_requests[-1]["client_secret"] == CLIENT_SECRET
    assert manual_server.token_requests[-1]["client_id"] == "my-client"


def test_changing_the_url_drops_the_sign_in(env, dcr_server):
    server = _create(env, dcr_server)
    _sign_in(env, server["id"])
    update = {
        "name": "Mail",
        "transport": "http",
        "url": f"{dcr_server.base}/mcp?v=2",
        "auth_type": "oauth",
    }
    res = env.client.put(f"/v1/mcp/servers/{server['id']}", json=update)
    assert res.json()["server"]["oauth_status"] == "signed_out"


def test_non_oauth_servers_cannot_start_sign_in(env, dcr_server):
    res = env.client.post(
        "/v1/mcp/servers",
        json={"name": "x", "transport": "http", "url": f"{dcr_server.base}/mcp"},
    )
    sid = res.json()["server"]["id"]
    assert env.client.post(f"/v1/mcp/servers/{sid}/oauth/start").status_code == 400


def test_callback_is_exempt_from_api_key_auth():
    from openjarvis.server.auth_middleware import AuthMiddleware

    assert AuthMiddleware._requires_auth("/v1/mcp/oauth/callback") is False
    assert AuthMiddleware._requires_auth("/v1/mcp/servers") is True


def test_forbidden_shows_the_server_reason_without_the_token(env, dcr_server):
    sid = _create(env, dcr_server)["id"]
    _sign_in(env, sid)
    dcr_server.forbidden = True
    res = env.client.post(f"/v1/mcp/servers/{sid}/test").json()
    assert res["ok"] is False
    assert res["error"].startswith("The server refused access (HTTP 403): Gmail MCP")
    assert "access-" not in res["error"]


def test_valid_jsonrpc_body_with_error_status_is_used(env, dcr_server):
    sid = _create(env, dcr_server)["id"]
    _sign_in(env, sid)
    dcr_server.result_with_403 = True
    res = env.client.post(f"/v1/mcp/servers/{sid}/test").json()
    assert res["ok"] is True
    assert [t["name"] for t in res["tools"]] == ["inbox"]
