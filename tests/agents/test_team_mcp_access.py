"""Team MCP connections: custom auth header, per-agent access, paid gate, files.

Uses a real local Streamable-HTTP MCP server (no external services).
"""

from __future__ import annotations

import base64
import json
import struct
import threading
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

import openjarvis.agents.team_tools as team_tools
from openjarvis.agents.manager import AgentManager
from openjarvis.agents.team_tools import discover_team_connections


def _png() -> bytes:
    raw = b"\x00\x80\x80\x80"

    def chunk(kind, data):
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


class FakeBria(BaseHTTPRequestHandler):
    """Minimal MCP server that requires ``api_token`` like Bria's hosted MCP."""

    received: list = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("api_token") != "company-bria-key":
            self.send_response(401)
            self.end_headers()
            return
        if "id" not in body:
            self.send_response(202)
            self.end_headers()
            return
        method = body.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "bria", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "remove_background",
                        "description": "Remove image background",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"image": {"type": "string"}},
                        },
                    }
                ]
            }
        else:
            FakeBria.received.append(body["params"]["arguments"])
            text = json.dumps({"result": {"image_url": "https://cdn.bria.test/o.png"}})
            result = {"content": [{"type": "text", "text": text}]}
        out = json.dumps(
            {"jsonrpc": "2.0", "id": body["id"], "result": result}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


@pytest.fixture
def bria_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeBria)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    FakeBria.received = []
    yield f"http://127.0.0.1:{server.server_port}/mcp"
    server.shutdown()


@pytest.fixture
def env(tmp_path, monkeypatch, bria_url):
    monkeypatch.setattr(
        team_tools,
        "_download_transport",
        httpx.MockTransport(lambda r: httpx.Response(200, content=_png())),
    )
    manager = AgentManager(str(tmp_path / "agents.db"))
    team = manager.create_team("سوفت باك")
    lead = manager.create_agent("المنسّق", team_id=team["id"])
    designer = manager.create_agent("المصمم", team_id=team["id"])
    writer = manager.create_agent("الكاتب", team_id=team["id"])
    manager.campaigns.set_team_lead(team["id"], lead["id"])

    def add(token="company-bria-key", **settings):
        return manager.create_team_connection(
            team["id"],
            name="Bria",
            provider="Bria",
            url=bria_url,
            auth_type="header",
            token=token,
            settings={"header_name": "api_token", **settings},
        )

    yield manager, team, lead, designer, writer, add
    manager.close()


def _running_task(manager, team, lead, designer, **options):
    campaign = manager.campaigns.create_campaign(
        team["id"], title="c", brief="b", options=options
    )
    root = manager.campaigns.campaign_dir(team["id"], campaign["id"])
    (root / "originals" / "box.png").write_bytes(b"ORIGINAL-BYTES")
    request = manager.campaigns.add_request(campaign["id"], content="b", files=[])
    manager.campaigns.claim_batch(request)
    manager.campaigns.assign_tasks(
        lead["id"],
        [{"target_agent_id": designer["id"], "title": "صمّم", "instructions": "x"}],
    )
    task = manager.campaigns.list_handoffs(campaign["id"])[-1]
    manager.campaigns.update_handoff(request["id"], status="completed")
    manager.campaigns.claim_batch(task)
    return campaign, root


def _tool(manager, agent):
    tools, clients = discover_team_connections(manager, agent["id"])
    return tools, clients


def test_header_auth_and_access_limited_to_chosen_agents(env):
    manager, team, lead, designer, writer, add = env
    connection = add(agent_ids=[designer["id"]])
    tools, clients = _tool(manager, designer)
    assert [t._tool.spec.name for t in tools] == ["remove_background"]
    for client in clients:
        client.close()
    assert _tool(manager, writer) == ([], [])
    assert not manager.team_connection_allowed(writer["id"], connection["id"])
    manager.set_team_connection_access(
        team["id"], connection["id"], agent_ids=[], paid=False
    )
    assert manager.team_connection_allowed(writer["id"], connection["id"])
    with pytest.raises(ValueError):
        manager.set_team_connection_access(
            team["id"], connection["id"], agent_ids=["ffffffffffff"], paid=False
        )


def test_invalid_header_names_rejected(env):
    manager, team, *_ = env
    for bad in ("", "Host", "Content-Type", "bad header"):
        with pytest.raises(ValueError):
            manager.create_team_connection(
                team["id"],
                name=f"x{bad}",
                provider=f"x{bad}",
                url="https://mcp.example.test/mcp",
                auth_type="header",
                token="t",
                settings={"header_name": bad},
            )


def test_paid_service_needs_request_permission(env):
    manager, team, lead, designer, writer, add = env
    add(paid=True)
    _running_task(manager, team, lead, designer, allow_paid=False)
    tools, clients = _tool(manager, designer)
    result = tools[0].execute(image="campaign:originals/box.png")
    assert not result.success and "مدفوعة" in result.content
    assert FakeBria.received == []
    for client in clients:
        client.close()


def test_campaign_file_sent_by_runtime_and_result_saved_for_review(env):
    manager, team, lead, designer, writer, add = env
    add(paid=True)
    campaign, root = _running_task(manager, team, lead, designer, allow_paid=True)
    tools, clients = _tool(manager, designer)
    result = tools[0].execute(image="campaign:originals/box.png")
    for client in clients:
        client.close()
    assert result.success, result.content
    # The file's bytes reached the service; the model never saw them.
    assert FakeBria.received == [
        {"image": base64.b64encode(b"ORIGINAL-BYTES").decode()}
    ]
    saved = [p for p in (root / "drafts").glob("mcp-*.png")]
    assert len(saved) == 1 and saved[0].read_bytes() == _png()
    meta = json.loads(saved[0].with_name(saved[0].name + ".json").read_text())
    assert meta["reconstructed"] is True and meta["verified"] is False
    assert "drafts/mcp-" in result.content and "مراجعة" in result.content


def test_campaign_paths_cannot_escape_the_request(env):
    manager, team, lead, designer, writer, add = env
    add()
    _running_task(manager, team, lead, designer)
    tools, clients = _tool(manager, designer)
    result = tools[0].execute(image="campaign:../../../agents.db")
    for client in clients:
        client.close()
    assert not result.success and FakeBria.received == []


def test_verify_lists_tools_and_reports_bad_key(env):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from openjarvis.server.agent_manager_routes import create_agent_manager_router

    manager, team, lead, designer, writer, add = env
    app = FastAPI()
    routers = create_agent_manager_router(manager)
    for router in routers if isinstance(routers, (list, tuple)) else [routers]:
        app.include_router(router)
    client = TestClient(app)
    good = add()
    response = client.post(
        f"/v1/managed-agents/teams/{team['id']}/connections/{good['id']}/verify"
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "verified"
    assert response.json()["tools"][0]["name"] == "remove_background"
    manager.delete_team_connection(team["id"], good["id"])
    bad = add(token="wrong-key")
    response = client.post(
        f"/v1/managed-agents/teams/{team['id']}/connections/{bad['id']}/verify"
    )
    assert response.status_code == 409
    assert "wrong-key" not in response.text
    status = manager.get_team_connection(team["id"], bad["id"])["status"]
    assert status == "error"
