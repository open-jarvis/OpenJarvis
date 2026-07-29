from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from openjarvis.codex import (
    ApprovalMode,
    CliProcessResult,
    CodexCapabilityError,
    CodexCliFallbackBackend,
    CodexModelConfig,
    CodexRunContext,
    SandboxMode,
    ThreadResumeRequest,
    ThreadStartRequest,
    TurnStartRequest,
)
from openjarvis.codex.types import CodexBackendError


class FakeRunner:
    def __init__(
        self,
        *,
        login: str = "Logged in using ChatGPT",
        exec_events: list[dict[str, Any]] | None = None,
    ) -> None:
        self.login = login
        self.exec_events = exec_events or [
            {"type": "thread.started", "thread_id": "must-not-be-resumable"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "id": "item-1",
                    "type": "agent_message",
                    "text": json.dumps({"summary": "Safe result"}),
                },
            },
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 2, "output_tokens": 3},
            },
        ]
        self.calls: list[
            tuple[tuple[str, ...], Path, dict[str, str], float, str | None]
        ] = []

    async def __call__(
        self,
        command,
        cwd,
        environment,
        timeout,
        stdin_text,
    ) -> CliProcessResult:
        command = tuple(command)
        self.calls.append(
            (command, cwd, dict(environment), timeout, stdin_text)
        )
        if command[-1] == "--version":
            return CliProcessResult(0, "codex-cli 0.145.0\n", "")
        if command[-2:] == ("login", "status"):
            return CliProcessResult(0, self.login, "")
        return CliProcessResult(
            0,
            "\n".join(json.dumps(event) for event in self.exec_events),
            "",
        )


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
        token_limit=20,
        developer_instructions=(
            "Never expose token=eyJabcdefghijk.abcdefghijklmnop.abcdefghijklmnop"
        ),
        isolated_workspace=(
            workspace if sandbox is SandboxMode.WORKSPACE_WRITE else None
        ),
    )


@pytest.mark.asyncio
async def test_cli_health_reports_explicit_degradation(tmp_path: Path) -> None:
    runner = FakeRunner()
    backend = CodexCliFallbackBackend(
        codex_bin="codex",
        runner=runner,
        environment={
            "PATH": "safe",
            "OPENAI_API_KEY": "must-not-be-inherited",
        },
    )

    health = await backend.health()

    assert health.available is True
    assert health.authenticated is True
    assert health.auth_mode == "chatgpt"
    assert health.degraded_backend is True
    assert health.capabilities.resume is False
    assert health.capabilities.command_approvals is False
    assert health.capabilities.full_item_events is False
    assert health.capabilities.streaming is False
    assert all("OPENAI_API_KEY" not in call[2] for call in runner.calls)


@pytest.mark.asyncio
async def test_cli_health_does_not_accept_api_key_mode(tmp_path: Path) -> None:
    del tmp_path
    runner = FakeRunner(login="Logged in using API key")
    backend = CodexCliFallbackBackend(codex_bin="codex", runner=runner)

    health = await backend.health()

    assert health.available is True
    assert health.authenticated is False
    assert health.auth_mode == "apiKey"


@pytest.mark.asyncio
async def test_cli_exec_is_ephemeral_read_only_and_schema_checked(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    backend = CodexCliFallbackBackend(
        codex_bin="codex",
        runner=runner,
        environment={"PATH": "safe"},
    )
    thread = await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )
    assert thread.thread_id.startswith("cli-ephemeral:")
    assert "must-not-be-resumable" not in thread.thread_id

    turn = await backend.start_turn(
        TurnStartRequest(
            context=_context(tmp_path, "turn-correlation"),
            thread_id=thread.thread_id,
            prompt="Return a harmless summary",
        )
    )
    command, cwd, _environment, timeout, stdin_text = runner.calls[-1]
    events = [event async for event in backend.stream_events(turn.turn_id)]

    assert command[:2] == ("codex", "exec")
    assert "--json" in command
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert 'approval_policy="never"' in command
    assert "--output-schema" in command
    assert command[-1] == "-"
    assert cwd == tmp_path
    assert timeout == 30
    assert "Return a harmless summary" in (stdin_text or "")
    assert "eyJabcdefghijk" not in (stdin_text or "")
    assert [event.event_type.value for event in events] == [
        "thread.started",
        "turn.started",
        "item.completed",
        "usage.updated",
        "turn.completed",
    ]
    assert events[2].payload == {"final": {"summary": "Safe result"}}


@pytest.mark.asyncio
async def test_cli_does_not_simulate_resume_or_second_turn(tmp_path: Path) -> None:
    runner = FakeRunner()
    backend = CodexCliFallbackBackend(codex_bin="codex", runner=runner)
    context = _context(tmp_path, "thread-correlation")
    thread = await backend.start_thread(ThreadStartRequest(context=context))
    await backend.start_turn(
        TurnStartRequest(
            context=_context(tmp_path, "turn-correlation"),
            thread_id=thread.thread_id,
            prompt="Read only",
        )
    )

    with pytest.raises(CodexCapabilityError, match="cannot resume"):
        await backend.resume_thread(
            ThreadResumeRequest(context=context, thread_id=thread.thread_id)
        )
    with pytest.raises(CodexCapabilityError, match="one turn"):
        await backend.start_turn(
            TurnStartRequest(
                context=_context(tmp_path, "second-turn"),
                thread_id=thread.thread_id,
                prompt="No simulated continuation",
            )
        )


@pytest.mark.asyncio
async def test_cli_rejects_workspace_write(tmp_path: Path) -> None:
    backend = CodexCliFallbackBackend(
        codex_bin="codex",
        runner=FakeRunner(),
    )

    with pytest.raises(CodexBackendError, match="read-only"):
        await backend.start_thread(
            ThreadStartRequest(
                context=_context(
                    tmp_path,
                    "thread-correlation",
                    sandbox=SandboxMode.WORKSPACE_WRITE,
                )
            )
        )


@pytest.mark.asyncio
async def test_cli_rejects_invalid_final_schema(tmp_path: Path) -> None:
    runner = FakeRunner(
        exec_events=[
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps({"unexpected": "value"}),
                },
            }
        ]
    )
    backend = CodexCliFallbackBackend(codex_bin="codex", runner=runner)
    thread = await backend.start_thread(
        ThreadStartRequest(context=_context(tmp_path, "thread-correlation"))
    )

    with pytest.raises(CodexBackendError, match="required schema"):
        await backend.start_turn(
            TurnStartRequest(
                context=_context(tmp_path, "turn-correlation"),
                thread_id=thread.thread_id,
                prompt="Read only",
            )
        )
