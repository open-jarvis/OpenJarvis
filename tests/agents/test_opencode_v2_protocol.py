"""OpenCode protocol regressions using real HTTPX requests, without a model.

The V2 fixture follows the tagged v2.0.32 protocol and server handlers:
https://github.com/anomalyco/opencode/blob/v2.0.32/packages/protocol/openapi.json
https://github.com/anomalyco/opencode/blob/v2.0.32/packages/server/src/handlers/message.ts
https://github.com/anomalyco/opencode/blob/v2.0.32/packages/cli/src/server-process.ts
"""

from __future__ import annotations

import base64
import io
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest

import openjarvis.agents.opencode as opencode


def _assistant(number: int, text: str, **changes) -> dict:
    return {
        "id": f"msg_{number:04}",
        "time": {"created": number, "completed": number + 0.5},
        "type": "assistant",
        "agent": "build",
        "model": {"providerID": "openjarvis", "id": "local-model"},
        "content": [{"type": "text", "text": text}],
        "finish": "stop",
        **changes,
    }


def _idle(number: int, outcome: str = "succeeded", **changes) -> dict:
    return {
        "id": f"msg_{number:04}",
        "time": {"created": number},
        "type": "idle",
        "outcome": outcome,
        **changes,
    }


class _ProtocolServer:
    """An authenticated V1/V2 HTTP contract with V2's default ordering/cursors."""

    def __init__(self, version="v2", messages=None):
        self.version = version
        self.password = "fixture-password"
        self.messages = (
            messages
            if messages is not None
            else [
                _assistant(2, "Inspecting the code."),
                _assistant(3, "Final answer."),
                _idle(4),
            ]
        )
        self.calls: list[httpx.Request] = []
        self.wait_status = 204
        self.wait_timeout = False
        self.transcript_status = 200
        self.bad_transcript = None
        self.repeat_cursor = False
        self.session_count = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        expected = (
            "Basic " + base64.b64encode(f"opencode:{self.password}".encode()).decode()
        )
        if request.headers.get("authorization") != expected:
            return httpx.Response(401, json={"message": "Authentication required"})
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        if path == "/session" and request.method == "POST":
            if self.version != "v1":
                return httpx.Response(404, json={"message": "Not found"})
            return httpx.Response(200, json={"id": "ses_v1"})
        if path == "/session/ses_v1/message":
            message = {
                "info": {"role": "assistant", "finish": "stop"},
                "parts": [{"type": "text", "text": "V1 final answer."}],
            }
            return httpx.Response(
                200, json=message if request.method == "POST" else [message]
            )
        if path == "/api/session" and request.method == "POST":
            assert set(body) == {"title", "agent", "model"}
            assert body["model"] == {"providerID": "openjarvis", "id": "local-model"}
            self.session_count += 1
            return httpx.Response(
                200, json={"data": {"id": f"ses_{self.session_count}"}}
            )
        if path.endswith("/prompt"):
            assert set(body) == {"text"}
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "msg_0001",
                        "sessionID": path.split("/")[3],
                        "time": {"created": 1},
                        "type": "user",
                        "payload": {"text": body["text"]},
                        "delivery": "queue",
                    }
                },
            )
        if path.endswith("/wait"):
            if self.wait_timeout:
                raise httpx.ReadTimeout("Fixture wait timeout", request=request)
            return httpx.Response(self.wait_status)
        if path.endswith("/message"):
            if self.transcript_status != 200:
                return httpx.Response(
                    self.transcript_status, json={"message": "Failed"}
                )
            if self.bad_transcript is not None:
                return httpx.Response(200, json=self.bad_transcript)
            params = request.url.params
            if "cursor" in params:
                assert "order" not in params
                order, offset = params["cursor"].split(":")
                start = int(offset)
            else:
                order, start = params.get("order", "desc"), 0
            messages = sorted(
                self.messages,
                key=lambda m: m["time"]["created"],
                reverse=order == "desc",
            )
            page = messages[start : start + int(params.get("limit", "50"))]
            # Upstream includes next for every nonempty page, even the last.
            next_cursor = f"{order}:{start + len(page)}" if page else None
            if self.repeat_cursor and "cursor" in params:
                page = messages[:1]
                next_cursor = params["cursor"]
            return httpx.Response(
                200, json={"data": page, "cursor": {"next": next_cursor}}
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)


@pytest.fixture
def protocol_agent(monkeypatch, tmp_path):
    server = _ProtocolServer()
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(server)),
    )
    agent = opencode.OpenCodeAgent(
        SimpleNamespace(_host="http://engine.invalid"),
        "local-model",
        workspace=str(tmp_path),
        api_version="auto",
        server_password=server.password,
    )
    agent._base = "http://fixture.invalid"
    monkeypatch.setattr(agent, "_ensure_server", lambda: agent._base)
    return server, agent


def test_v2_final_answer_and_cached_detection(protocol_agent):
    server, agent = protocol_agent
    assert agent.run("First task").content == "Final answer."
    result = agent.run("Second task")
    assert result.content == "Final answer."
    assert result.metadata["api_version"] == "v2"
    assert sum(r.url.path == "/session" for r in server.calls) == 1


def test_v1_model_payload_and_reply_remain_compatible(protocol_agent):
    server, agent = protocol_agent
    server.version = "v1"
    result = agent.run("Task")
    assert result.content == "V1 final answer."
    assert result.metadata["api_version"] == "v1"
    prompt = next(
        r
        for r in server.calls
        if r.method == "POST" and r.url.path.endswith("/message")
    )
    assert json.loads(prompt.content)["model"] == {
        "providerID": "openjarvis",
        "modelID": "local-model",
    }
    assert not any("/wait" in r.url.path for r in server.calls)


def test_v2_reads_all_pages_and_preserves_tool_results(protocol_agent):
    server, agent = protocol_agent
    server.messages = []
    for number in range(1, 206):
        server.messages.append(
            _assistant(
                number,
                "",
                finish="tool-calls",
                content=[
                    {
                        "type": "tool",
                        "id": f"call_{number}",
                        "name": "read",
                        "time": {"created": number},
                        "state": {
                            "status": "completed",
                            "input": {},
                            "content": [{"type": "text", "text": f"Result {number}"}],
                        },
                    }
                ],
            )
        )
    server.messages.append(_assistant(206, "Final answer."))
    server.messages.append(_idle(207))
    result = agent.run("Long task")
    assert result.content == "Final answer."
    assert len(result.tool_results) == 205
    assert [r.content for r in result.tool_results] == [
        f"Result {number}" for number in range(1, 206)
    ]
    assert all(r.success for r in result.tool_results)
    pages = [r for r in server.calls if r.method == "GET"]
    assert len(pages) == 3  # 200, 7, then the empty cursor terminator


@pytest.mark.parametrize("status", [401, 404, 503])
def test_v2_wait_http_failure_is_an_error(protocol_agent, status):
    server, agent = protocol_agent
    server.wait_status = status
    result = agent.run("Task")
    assert result.metadata.get("error") is True
    assert not any(r.method == "GET" for r in server.calls)


def test_v2_wait_timeout_is_an_error(protocol_agent):
    server, agent = protocol_agent
    server.wait_timeout = True
    result = agent.run("Task")
    assert result.metadata.get("error") is True
    assert not any(r.method == "GET" for r in server.calls)


def test_v2_transcript_http_failure_is_an_error(protocol_agent):
    server, agent = protocol_agent
    server.transcript_status = 500
    result = agent.run("Task")
    assert result.metadata.get("error") is True


@pytest.mark.parametrize(
    "body", [{"data": None}, {"data": [None]}, {"data": [], "error": "failed"}]
)
def test_v2_invalid_or_empty_transcript_is_an_error(protocol_agent, body):
    server, agent = protocol_agent
    server.bad_transcript = body
    assert agent.run("Task").metadata.get("error") is True


def test_v2_repeated_cursor_fails_instead_of_looping(protocol_agent):
    server, agent = protocol_agent
    server.repeat_cursor = True
    result = agent.run("Task")
    assert result.metadata.get("error") is True
    assert "repeated" in result.content
    assert sum(r.method == "GET" for r in server.calls) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"finish": None},
        {"finish": "unknown"},
        {"finish": "content-filter"},
        {"finish": "error"},
        {
            "error": {
                "type": "provider",
                "message": "Provider rejected request",
                "status": 429,
            }
        },
    ],
)
def test_v2_failed_assistant_is_an_error(protocol_agent, changes):
    server, agent = protocol_agent
    server.messages = [_assistant(2, "Partial text", **changes), _idle(3)]
    result = agent.run("Task")
    assert result.metadata.get("error") is True


@pytest.mark.parametrize("finish", [None, "tool-calls", "stop", "length"])
def test_v2_missing_terminal_marker_is_an_error(protocol_agent, finish):
    server, agent = protocol_agent
    server.messages = [_assistant(2, "Partial text", finish=finish)]
    assert agent.run("Task").metadata.get("error") is True


@pytest.mark.parametrize("outcome", ["failed", "interrupted"])
@pytest.mark.parametrize("finish", ["stop", "length"])
def test_v2_idle_failure_is_not_successful_completion(protocol_agent, outcome, finish):
    server, agent = protocol_agent
    server.messages = [
        _assistant(2, "Partial text", finish=finish),
        _idle(
            3,
            outcome,
            error={"type": "output-limit", "message": "Output limit reached"},
        ),
    ]
    result = agent.run("Task")
    assert result.metadata.get("error") is True
    assert "Output limit reached" in result.content


def test_v2_old_idle_marker_cannot_complete_a_new_reply(protocol_agent):
    server, agent = protocol_agent
    server.messages = [
        _assistant(2, "Earlier reply"),
        _idle(3),
        _assistant(4, "Partial"),
    ]
    assert agent.run("Task").metadata.get("error") is True


@pytest.mark.parametrize("finish", ["stop", "length", "tool-calls"])
def test_v2_successful_idle_is_authoritative(protocol_agent, finish):
    server, agent = protocol_agent
    server.messages = [_assistant(2, "Completed", finish=finish), _idle(3)]
    result = agent.run("Task")
    assert not result.metadata.get("error")
    assert result.content == "Completed"
    assert result.metadata["finish"] == finish


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_startup_generated_password_authenticates_over_http(
    monkeypatch, tmp_path, version
):
    """Exercise _ensure_server, its process environment and the real HTTP client."""
    monkeypatch.delenv("OPENCODE_PASSWORD", raising=False)
    monkeypatch.delenv("OPENCODE_SERVER_PASSWORD", raising=False)
    protocol = _ProtocolServer(version=version)

    class Handler(BaseHTTPRequestHandler):
        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            response = protocol(
                httpx.Request(
                    self.command,
                    f"http://localhost{self.path}",
                    headers=dict(self.headers),
                    content=body,
                )
            )
            self.send_response(response.status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

        do_POST = do_GET = do_DELETE = handle_request

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{httpd.server_port}"
    spawned = {}

    def spawn(*args, **kwargs):
        env = kwargs["env"]
        assert env["OPENCODE_PASSWORD"] == env["OPENCODE_SERVER_PASSWORD"]
        assert len(env["OPENCODE_PASSWORD"]) >= 32
        protocol.password = env["OPENCODE_PASSWORD"]
        spawned.update(kwargs)
        return SimpleNamespace(
            stdout=io.StringIO(f"server listening on {url}\n"),
            poll=lambda: None,
            terminate=lambda: None,
            wait=lambda **kw: None,
        )

    monkeypatch.setattr(opencode, "is_opencode_available", lambda: True)
    monkeypatch.setattr(opencode.subprocess, "Popen", spawn)
    agent = opencode.OpenCodeAgent(
        SimpleNamespace(_host="http://engine.invalid"),
        "local-model",
        workspace=str(tmp_path),
    )
    try:
        result = agent.run("Task")
        assert not result.metadata.get("error"), result.content
        assert result.content == (
            "V1 final answer." if version == "v1" else "Final answer."
        )
        assert protocol.password not in result.content
        assert spawned
    finally:
        agent.close()
        httpd.shutdown()
        httpd.server_close()
        worker.join()


@pytest.mark.parametrize(
    "explicit,modern,legacy,expected",
    [
        ("explicit", "modern", "legacy", "explicit"),
        ("", "modern", "legacy", "modern"),
        ("", "", "legacy", "legacy"),
    ],
)
def test_server_password_precedence(monkeypatch, explicit, modern, legacy, expected):
    monkeypatch.setenv("OPENCODE_PASSWORD", modern)
    monkeypatch.setenv("OPENCODE_SERVER_PASSWORD", legacy)
    agent = opencode.OpenCodeAgent(
        SimpleNamespace(), "provider/model", server_password=explicit
    )
    with agent._client() as client:
        assert (
            client.headers["authorization"]
            == "Basic " + base64.b64encode(f"opencode:{expected}".encode()).decode()
        )
