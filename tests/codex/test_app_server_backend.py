from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from openjarvis.codex import (
    ApprovalMode,
    CodexAppServerBackend,
    CodexModelConfig,
    CodexPolicyError,
    CodexRunContext,
    CodexStateStore,
    SandboxMode,
    ThreadForkRequest,
    ThreadResumeRequest,
    ThreadStartRequest,
    TurnStartRequest,
)


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], float | None]] = []
        self.messages: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.started = 0
        self.closed = 0
        self.reconnected = 0
        self.next_thread = "thread-1"
        self.next_turn = "turn-1"
        self.account_type: str | None = "chatgpt"

    async def start(self) -> None:
        self.started += 1

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        self.calls.append((method, params, timeout))
        if method == "account/read":
            account = (
                {"type": self.account_type, "email": "private@example.test"}
                if self.account_type
                else None
            )
            return {"account": account}
        if method in {"thread/start", "thread/resume", "thread/fork"}:
            return {"thread": {"id": self.next_thread}}
        if method == "turn/start":
            return {"turn": {"id": self.next_turn}}
        if method == "thread/read":
            return {
                "thread": {
                    "id": params["threadId"],
                    "accessToken": "must-not-escape",
                }
            }
        return {}

    async def next_message(self, *, timeout: float) -> dict[str, Any]:
        return await asyncio.wait_for(self.messages.get(), timeout)

    async def reconnect(self, *, safe: bool) -> None:
        assert safe is True
        self.reconnected += 1

    async def close(self) -> None:
        self.closed += 1


def _context(
    workspace: Path,
    correlation_id: str,
    *,
    sandbox: SandboxMode = SandboxMode.READ_ONLY,
) -> CodexRunContext:
    return CodexRunContext(
        task_id="task-1",
        session_id="session-1",
        correlation_id=correlation_id,
        cwd=workspace,
        sandbox=sandbox,
        approval_mode=ApprovalMode.DENY_ALL,
        model=CodexModelConfig(
            model="test-model",
            effort="medium",
            service_tier=None,
        ),
        timeout_seconds=30,
        step_limit=20,
        token_limit=100,
        developer_instructions=(
            "Do not reveal token=eyJabcdefghijk.abcdefghijklmnop.abcdefghijklmnop"
        ),
        isolated_workspace=(
            workspace if sandbox is SandboxMode.WORKSPACE_WRITE else None
        ),
    )


def _backend(
    transport: FakeTransport,
    store: CodexStateStore,
) -> CodexAppServerBackend:
    return CodexAppServerBackend(transport=transport, store=store)


@pytest.mark.asyncio
async def test_app_server_health_requires_chatgpt_login(tmp_path: Path) -> None:
    transport = FakeTransport()
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(transport, store)

    healthy = await backend.health()
    transport.account_type = "apiKey"
    rejected = await backend.health()

    assert healthy.available is True
    assert healthy.authenticated is True
    assert healthy.auth_mode == "chatgpt"
    assert rejected.available is True
    assert rejected.authenticated is False
    assert rejected.auth_mode == "apiKey"
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_thread_lifecycle_uses_explicit_safe_wire_values(tmp_path: Path) -> None:
    transport = FakeTransport()
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(transport, store)
    context = _context(tmp_path, "thread-correlation")

    started = await backend.start_thread(ThreadStartRequest(context=context))
    duplicate = await backend.start_thread(ThreadStartRequest(context=context))

    assert duplicate == started
    start_calls = [call for call in transport.calls if call[0] == "thread/start"]
    assert len(start_calls) == 1
    params = start_calls[0][1]
    assert params["approvalPolicy"] == "never"
    assert params["approvalsReviewer"] == "user"
    assert params["sandbox"] == "read-only"
    assert params["ephemeral"] is False
    assert "eyJabcdefghijk" not in (params["developerInstructions"] or "")

    resumed = await backend.resume_thread(
        ThreadResumeRequest(
            context=_context(tmp_path, "resume-correlation"),
            thread_id=None,
        )
    )
    assert resumed.thread_id == "thread-1"
    resume_params = [
        call[1] for call in transport.calls if call[0] == "thread/resume"
    ][0]
    assert resume_params["threadId"] == "thread-1"
    assert resume_params["approvalPolicy"] == "never"
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_fork_and_turn_are_idempotent(tmp_path: Path) -> None:
    transport = FakeTransport()
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(transport, store)
    await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )
    transport.next_thread = "thread-forked"
    fork_context = replace(
        _context(tmp_path, "fork-correlation"),
        task_id="task-fork",
        session_id="session-fork",
    )
    fork_request = ThreadForkRequest(
        context=fork_context,
        source_thread_id="thread-1",
    )

    first_fork = await backend.fork_thread(fork_request)
    second_fork = await backend.fork_thread(fork_request)

    assert first_fork == second_fork
    assert len([call for call in transport.calls if call[0] == "thread/fork"]) == 1

    turn_context = _context(tmp_path, "turn-correlation")
    turn_request = TurnStartRequest(
        context=turn_context,
        thread_id="thread-1",
        prompt="Harmless read-only request",
    )
    first_turn = await backend.start_turn(turn_request)
    second_turn = await backend.start_turn(turn_request)

    assert first_turn == second_turn
    assert len([call for call in transport.calls if call[0] == "turn/start"]) == 1
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_workspace_write_turn_is_isolated_and_networkless(
    tmp_path: Path,
) -> None:
    transport = FakeTransport()
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(transport, store)
    context = _context(
        tmp_path,
        "thread-correlation",
        sandbox=SandboxMode.WORKSPACE_WRITE,
    )
    await backend.start_thread(ThreadStartRequest(context=context))
    turn = await backend.start_turn(
        TurnStartRequest(
            context=replace(context, correlation_id="turn-correlation"),
            thread_id="thread-1",
            prompt="Operate only in the isolated test workspace",
        )
    )
    params = [call[1] for call in transport.calls if call[0] == "turn/start"][0]

    assert params["approvalPolicy"] == "never"
    assert params["sandboxPolicy"] == {
        "type": "workspaceWrite",
        "writableRoots": [str(tmp_path)],
        "networkAccess": False,
        "excludeSlashTmp": False,
        "excludeTmpdirEnvVar": False,
    }
    await backend.interrupt(turn.turn_id)
    await backend.close()
    store.close()


def test_brokered_policy_uses_on_request_with_user_reviewer(tmp_path: Path) -> None:
    context = replace(
        _context(
            tmp_path,
            "brokered-correlation",
            sandbox=SandboxMode.WORKSPACE_WRITE,
        ),
        approval_mode=ApprovalMode.BROKERED,
    )

    params = CodexAppServerBackend._thread_params(context)

    assert params["approvalPolicy"] == "on-request"
    assert params["approvalsReviewer"] == "user"


@pytest.mark.asyncio
async def test_events_are_streamed_and_read_is_redacted(tmp_path: Path) -> None:
    transport = FakeTransport()
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(transport, store)
    await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )
    turn = await backend.start_turn(
        TurnStartRequest(
            context=_context(tmp_path, "turn-correlation"),
            thread_id="thread-1",
            prompt="Read only",
        )
    )
    await transport.messages.put(
        {
            "method": "turn/started",
            "eventId": "event-1",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "inProgress"},
            },
        }
    )
    await transport.messages.put(
        {
            "method": "turn/completed",
            "eventId": "event-2",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed"},
            },
        }
    )

    events = [event async for event in backend.stream_events(turn.turn_id)]
    read = await backend.read_thread("thread-1")

    assert [event.event_type.value for event in events] == [
        "turn.started",
        "turn.completed",
    ]
    assert read["thread"]["accessToken"] == "[REDACTED]"
    await backend.reconnect()
    assert transport.reconnected == 1
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_reconnect_is_blocked_while_turn_is_active(tmp_path: Path) -> None:
    transport = FakeTransport()
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(transport, store)
    await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )
    await backend.start_turn(
        TurnStartRequest(
            context=_context(tmp_path, "turn-correlation"),
            thread_id="thread-1",
            prompt="Read only",
        )
    )

    with pytest.raises(CodexPolicyError, match="turns are active"):
        await backend.reconnect()

    await backend.close()
    store.close()
