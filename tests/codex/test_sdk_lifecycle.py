from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from openjarvis.codex import (
    ApprovalMode,
    CodexModelConfig,
    CodexPolicyError,
    CodexPythonSdkBackend,
    CodexRunContext,
    CodexStateStore,
    SandboxMode,
    ThreadForkRequest,
    ThreadResumeRequest,
    ThreadStartRequest,
    TurnStartRequest,
)


class FakeAccount:
    def model_dump(self, **kwargs):
        del kwargs
        return {
            "account": {"type": "chatgpt", "email": "private@example.test"},
            "requiresOpenaiAuth": True,
        }


class FakeRead:
    def model_dump(self, **kwargs):
        del kwargs
        return {
            "thread": {
                "id": "thread-1",
                "accessToken": "must-not-escape",
            }
        }


class FakeTurnHandle:
    def __init__(self, turn_id: str, events: list[dict] | None = None) -> None:
        self.id = turn_id
        self.events = events or []
        self.steered: list[str] = []
        self.interrupt_count = 0

    async def stream(self):
        for event in self.events:
            yield event

    async def steer(self, prompt: str):
        self.steered.append(prompt)
        return {}

    async def interrupt(self):
        self.interrupt_count += 1
        return {}


class FakeThread:
    def __init__(
        self,
        thread_id: str,
        *,
        turn_handle: FakeTurnHandle | None = None,
    ) -> None:
        self.id = thread_id
        self.turn_handle = turn_handle or FakeTurnHandle("turn-1")
        self.turn_calls: list[tuple[str, dict]] = []

    async def turn(self, prompt: str, **kwargs):
        self.turn_calls.append((prompt, kwargs))
        return self.turn_handle

    async def read(self, *, include_turns: bool):
        assert include_turns is True
        return FakeRead()


class FakeSdk:
    def __init__(self) -> None:
        self.start_calls: list[dict] = []
        self.resume_calls: list[tuple[str, dict]] = []
        self.fork_calls: list[tuple[str, dict]] = []
        self.started_thread = FakeThread("thread-1")
        self.resumed_thread = FakeThread("thread-1")
        self.forked_thread = FakeThread("thread-forked")
        self.closed = False

    async def account(self, *, refresh_token: bool):
        assert refresh_token is False
        return FakeAccount()

    async def thread_start(self, **kwargs):
        self.start_calls.append(kwargs)
        return self.started_thread

    async def thread_resume(self, thread_id: str, **kwargs):
        self.resume_calls.append((thread_id, kwargs))
        self.resumed_thread.id = thread_id
        return self.resumed_thread

    async def thread_fork(self, thread_id: str, **kwargs):
        self.fork_calls.append((thread_id, kwargs))
        return self.forked_thread

    async def close(self):
        self.closed = True


def _context(
    workspace: Path,
    correlation_id: str,
    *,
    step_limit: int = 20,
    token_limit: int | None = None,
) -> CodexRunContext:
    return CodexRunContext(
        task_id="task-1",
        session_id="session-1",
        correlation_id=correlation_id,
        cwd=workspace,
        sandbox=SandboxMode.READ_ONLY,
        approval_mode=ApprovalMode.DENY_ALL,
        model=CodexModelConfig(
            model="test-model",
            effort="medium",
            service_tier=None,
        ),
        timeout_seconds=30,
        step_limit=step_limit,
        token_limit=token_limit,
        developer_instructions=(
            "Use token=eyJabcdefghijk.abcdefghijklmnop.abcdefghijklmnop safely"
        ),
        isolated_workspace=None,
    )


def _backend(
    fake: FakeSdk,
    store: CodexStateStore,
) -> CodexPythonSdkBackend:
    return CodexPythonSdkBackend(
        sdk_factory=lambda spec: fake,
        environment={"PATH": "safe"},
        store=store,
    )


@pytest.mark.asyncio
async def test_thread_start_is_explicit_safe_and_persisted(tmp_path: Path) -> None:
    store = CodexStateStore(tmp_path / "codex.db")
    fake = FakeSdk()
    backend = _backend(fake, store)
    context = _context(tmp_path, "thread-correlation")

    thread = await backend.start_thread(ThreadStartRequest(context=context))
    duplicate = await backend.start_thread(ThreadStartRequest(context=context))

    assert thread.thread_id == "thread-1"
    assert duplicate == thread
    assert len(fake.start_calls) == 1
    call = fake.start_calls[0]
    assert call["approval_mode"].value == "deny_all"
    assert call["sandbox"].value == "read-only"
    assert call["ephemeral"] is False
    assert call["cwd"] == str(tmp_path)
    assert "eyJabcdefghijk" not in (call["developer_instructions"] or "")
    record = store.get_thread("task-1", "session-1")
    assert record is not None
    assert record.thread_id == "thread-1"
    assert record.approval_mode is ApprovalMode.DENY_ALL
    assert record.sandbox is SandboxMode.READ_ONLY
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_thread_resume_after_backend_restart(tmp_path: Path) -> None:
    path = tmp_path / "codex.db"
    first_store = CodexStateStore(path)
    first_fake = FakeSdk()
    first = _backend(first_fake, first_store)
    await first.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )
    await first.close()
    first_store.close()

    reopened_store = CodexStateStore(path)
    second_fake = FakeSdk()
    second = _backend(second_fake, reopened_store)
    resumed = await second.resume_thread(
        ThreadResumeRequest(
            context=_context(tmp_path, "resume-correlation"),
            thread_id=None,
        )
    )

    assert resumed.thread_id == "thread-1"
    assert second_fake.resume_calls[0][0] == "thread-1"
    kwargs = second_fake.resume_calls[0][1]
    assert kwargs["approval_mode"].value == "deny_all"
    assert kwargs["sandbox"].value == "read-only"
    await second.close()
    reopened_store.close()


@pytest.mark.asyncio
async def test_thread_fork_is_supported_and_persisted(tmp_path: Path) -> None:
    store = CodexStateStore(tmp_path / "codex.db")
    fake = FakeSdk()
    backend = _backend(fake, store)
    await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )
    fork_context = replace(
        _context(tmp_path, "fork-correlation"),
        task_id="task-fork",
        session_id="session-fork",
    )

    forked = await backend.fork_thread(
        ThreadForkRequest(
            context=fork_context,
            source_thread_id="thread-1",
        )
    )

    assert forked.thread_id == "thread-forked"
    assert fake.fork_calls[0][0] == "thread-1"
    assert store.get_thread("task-fork", "session-fork") is not None
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_turn_streaming_steer_interrupt_and_checkpoint(tmp_path: Path) -> None:
    events = [
        {
            "method": "turn/started",
            "eventId": "event-1",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "inProgress"},
            },
        },
        {
            "method": "item/agentMessage/delta",
            "eventId": "event-2",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "delta": "hello",
            },
        },
        {
            "method": "turn/completed",
            "eventId": "event-3",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed"},
            },
        },
    ]
    handle = FakeTurnHandle("turn-1", events)
    fake = FakeSdk()
    fake.started_thread = FakeThread("thread-1", turn_handle=handle)
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(fake, store)
    await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )
    turn_context = _context(tmp_path, "turn-correlation")
    turn = await backend.start_turn(
        TurnStartRequest(
            context=turn_context,
            thread_id="thread-1",
            prompt="Harmless read-only request",
        )
    )
    await backend.steer(turn.turn_id, "Focus on the summary")
    streamed = [event async for event in backend.stream_events(turn.turn_id)]

    assert [event.event_type.value for event in streamed] == [
        "turn.started",
        "item.delta",
        "turn.completed",
    ]
    assert handle.steered == ["Focus on the summary"]
    persisted_turn = store.get_turn("turn-1")
    persisted_thread = store.get_thread_by_id("thread-1")
    assert persisted_turn is not None and persisted_turn.status == "completed"
    assert persisted_thread is not None
    assert persisted_thread.resume_checkpoint == "turn-1"
    turn_call = fake.started_thread.turn_calls[0][1]
    assert turn_call["approval_mode"].value == "deny_all"
    assert turn_call["sandbox"].value == "read-only"
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_step_limit_interrupts_turn(tmp_path: Path) -> None:
    events = [
        {
            "method": "item/agentMessage/delta",
            "eventId": f"event-{index}",
            "params": {"threadId": "thread-1", "turnId": "turn-1"},
        }
        for index in range(2)
    ]
    handle = FakeTurnHandle("turn-1", events)
    fake = FakeSdk()
    fake.started_thread = FakeThread("thread-1", turn_handle=handle)
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(fake, store)
    await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )
    turn = await backend.start_turn(
        TurnStartRequest(
            context=_context(tmp_path, "turn-correlation", step_limit=1),
            thread_id="thread-1",
            prompt="Read only",
        )
    )

    with pytest.raises(CodexPolicyError, match="step limit"):
        _ = [event async for event in backend.stream_events(turn.turn_id)]

    assert handle.interrupt_count == 1
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_token_limit_interrupts_turn(tmp_path: Path) -> None:
    events = [
        {
            "method": "thread/tokenUsage/updated",
            "eventId": "usage-event",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "tokenUsage": {"total": {"totalTokens": 11}},
            },
        }
    ]
    handle = FakeTurnHandle("turn-1", events)
    fake = FakeSdk()
    fake.started_thread = FakeThread("thread-1", turn_handle=handle)
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(fake, store)
    await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )
    turn = await backend.start_turn(
        TurnStartRequest(
            context=_context(
                tmp_path,
                "turn-correlation",
                token_limit=10,
            ),
            thread_id="thread-1",
            prompt="Read only",
        )
    )

    with pytest.raises(CodexPolicyError, match="token limit"):
        _ = [event async for event in backend.stream_events(turn.turn_id)]

    assert handle.interrupt_count == 1
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_explicit_interrupt_updates_persisted_turn(tmp_path: Path) -> None:
    handle = FakeTurnHandle("turn-1")
    fake = FakeSdk()
    fake.started_thread = FakeThread("thread-1", turn_handle=handle)
    store = CodexStateStore(tmp_path / "codex.db")
    backend = _backend(fake, store)
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

    await backend.interrupt(turn.turn_id)

    assert handle.interrupt_count == 1
    record = store.get_turn(turn.turn_id)
    assert record is not None and record.status == "interrupted"
    await backend.close()
    store.close()


@pytest.mark.asyncio
async def test_read_thread_redacts_credentials(tmp_path: Path) -> None:
    store = CodexStateStore(tmp_path / "codex.db")
    fake = FakeSdk()
    backend = _backend(fake, store)
    await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )

    result = await backend.read_thread("thread-1")

    assert result["thread"]["accessToken"] == "[REDACTED]"
    await backend.close()
    store.close()
