from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from openjarvis.codex import (
    ApprovalDecision,
    ApprovalRequest,
    AppServerTransport,
    CodexPolicyError,
)
from openjarvis.codex.types import CodexTimeoutError

_FAKE_SERVER = r"""
import json
import sys


def send(message):
    print(json.dumps(message), flush=True)


initialize = json.loads(sys.stdin.readline())
send({"id": initialize["id"], "result": {"userAgent": "fake-app-server"}})
json.loads(sys.stdin.readline())
print("api_key=sk-abcdefghijklmnopqrstuvwxyz123456", file=sys.stderr, flush=True)

for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if method == "test/approval":
        approval = {
            "id": "approval-1",
            "method": "item/commandExecution/requestApproval",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "command": "echo safe",
            },
        }
        send(approval)
        send(approval)
        response = json.loads(sys.stdin.readline())
        send(
            {
                "id": message["id"],
                "result": {"decision": response["result"]["decision"]},
            }
        )
    elif method == "test/no-response":
        continue
    else:
        send({"id": message["id"], "result": {}})
"""


class BlockingApprovalBroker:
    def __init__(self) -> None:
        self.called = asyncio.Event()
        self.release = asyncio.Event()
        self.requests: list[ApprovalRequest] = []

    async def resolve(self, request: ApprovalRequest) -> ApprovalDecision:
        self.requests.append(request)
        self.called.set()
        await self.release.wait()
        return ApprovalDecision.ACCEPT


def _write_fake_server(tmp_path: Path) -> Path:
    server = tmp_path / "fake_app_server.py"
    server.write_text(_FAKE_SERVER, encoding="utf-8")
    return server


@pytest.mark.asyncio
async def test_transport_waits_for_broker_and_replies_once(tmp_path: Path) -> None:
    broker = BlockingApprovalBroker()
    transport = AppServerTransport(
        (sys.executable, str(_write_fake_server(tmp_path))),
        approval_broker=broker,
        request_timeout=2,
        queue_size=4,
    )
    await transport.start()

    request = asyncio.create_task(transport.request("test/approval", {}))
    requested = await transport.next_message(timeout=2)
    await broker.called.wait()

    assert requested["method"] == "approval/requested"
    assert request.done() is False
    assert broker.requests[0].thread_id == "thread-1"

    broker.release.set()
    result = await request
    resolved = await transport.next_message(timeout=2)

    assert result == {"decision": "accept"}
    assert resolved["method"] == "approval/resolved"
    assert resolved["params"]["decision"] == "accept"
    assert transport.approval_response_count == 1
    assert all(
        "sk-abcdefghijklmnopqrstuvwxyz" not in line
        for line in transport.stderr_tail
    )
    await transport.close()


@pytest.mark.asyncio
async def test_transport_defaults_to_decline(tmp_path: Path) -> None:
    transport = AppServerTransport(
        (sys.executable, str(_write_fake_server(tmp_path))),
        request_timeout=2,
    )
    await transport.start()

    result = await transport.request("test/approval", {})

    assert result == {"decision": "decline"}
    assert transport.approval_response_count == 1
    await transport.close()


@pytest.mark.asyncio
async def test_transport_bounds_requests_and_reconnect_policy(tmp_path: Path) -> None:
    transport = AppServerTransport(
        (sys.executable, str(_write_fake_server(tmp_path))),
        request_timeout=2,
    )
    await transport.start()

    with pytest.raises(CodexTimeoutError, match="test/no-response"):
        await transport.request("test/no-response", {}, timeout=0.05)
    with pytest.raises(CodexPolicyError, match="explicitly safe"):
        await transport.reconnect(safe=False)

    await transport.close()


@pytest.mark.asyncio
async def test_concurrent_start_creates_one_reader_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = asyncio.create_subprocess_exec
    launch_count = 0

    async def delayed_launch(*args, **kwargs):
        nonlocal launch_count
        launch_count += 1
        await asyncio.sleep(0.02)
        return await original(*args, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_launch)
    transport = AppServerTransport(
        (sys.executable, str(_write_fake_server(tmp_path))),
        request_timeout=2,
    )

    await asyncio.gather(*(transport.start() for _ in range(5)))

    assert launch_count == 1
    assert transport.running is True
    await transport.close()
