"""Explicitly degraded, read-only Codex CLI fallback."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openjarvis.codex.app_server import find_global_codex
from openjarvis.codex.redaction import (
    redact_data,
    redact_text,
    safe_error_message,
    sanitized_codex_environment,
)
from openjarvis.codex.types import (
    BackendCapabilities,
    BackendThread,
    BackendTurn,
    CodexBackendError,
    CodexBackendKind,
    CodexCapabilityError,
    CodexEvent,
    CodexEventType,
    CodexHealth,
    CodexPolicyError,
    CodexRunContext,
    CodexTimeoutError,
    SandboxMode,
    ThreadForkRequest,
    ThreadResumeRequest,
    ThreadStartRequest,
    TurnStartRequest,
)


@dataclass(frozen=True, slots=True)
class CliProcessResult:
    """Captured result from one bounded CLI invocation."""

    returncode: int
    stdout: str
    stderr: str


CliRunner = Callable[
    [Sequence[str], Path, Mapping[str, str], float, str | None],
    Awaitable[CliProcessResult],
]


@dataclass(slots=True)
class _CliThread:
    context: CodexRunContext
    used: bool = False


class CodexCliFallbackBackend:
    """One-shot emergency backend with no persistent or interactive claims."""

    _CAPABILITIES = BackendCapabilities(
        persistent_threads=False,
        resume=False,
        fork=False,
        streaming=False,
        steer=False,
        interrupt=False,
        command_approvals=False,
        file_approvals=False,
        full_item_events=False,
        usage_events=True,
        read_only=True,
        workspace_write=False,
    )

    def __init__(
        self,
        *,
        codex_bin: str | Path | None = None,
        environment: Mapping[str, str] | None = None,
        runner: CliRunner | None = None,
        output_schema_path: str | Path | None = None,
    ) -> None:
        self._codex_bin = str(codex_bin) if codex_bin else None
        self._environment = sanitized_codex_environment(environment)
        self._runner = runner or _run_cli
        self._schema_path = (
            Path(output_schema_path)
            if output_schema_path
            else Path(__file__).with_name("cli-final-response.schema.json")
        )
        self._threads: dict[str, _CliThread] = {}
        self._turn_events: dict[str, list[CodexEvent]] = {}
        self._runtime_version: str | None = None

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._CAPABILITIES

    def _binary(self) -> str:
        binary = self._codex_bin or find_global_codex()
        if not binary:
            raise CodexBackendError("Global Codex CLI is unavailable")
        return binary

    async def health(self) -> CodexHealth:
        """Check only the explicit global CLI and its safe login status."""

        try:
            binary = self._binary()
            cwd = Path.cwd()
            version = await self._runner(
                (binary, "--version"),
                cwd,
                self._environment,
                10,
                None,
            )
            if version.returncode != 0:
                raise CodexBackendError(safe_error_message(version.stderr))
            self._runtime_version = redact_text(version.stdout.strip()) or None
            login = await self._runner(
                (binary, "login", "status"),
                cwd,
                self._environment,
                10,
                None,
            )
            status = f"{login.stdout}\n{login.stderr}".lower()
            auth_mode = (
                "chatgpt"
                if "chatgpt" in status
                else "apiKey"
                if "api key" in status or "apikey" in status
                else None
            )
            authenticated = login.returncode == 0 and auth_mode == "chatgpt"
            return CodexHealth(
                available=True,
                authenticated=authenticated,
                auth_mode=auth_mode,
                runtime_version=self._runtime_version,
                backend=CodexBackendKind.CLI_FALLBACK,
                capabilities=self.capabilities,
                degraded_backend=True,
                detail=(
                    None
                    if authenticated
                    else "Degraded CLI fallback requires an existing ChatGPT login"
                ),
            )
        except Exception as exc:
            return CodexHealth(
                available=False,
                authenticated=False,
                auth_mode=None,
                runtime_version=self._runtime_version,
                backend=CodexBackendKind.CLI_FALLBACK,
                capabilities=self.capabilities,
                degraded_backend=True,
                detail=safe_error_message(exc),
            )

    async def _require_chatgpt(self) -> None:
        health = await self.health()
        if not health.available:
            raise CodexBackendError(health.detail or "Codex CLI unavailable")
        if not health.authenticated:
            raise CodexBackendError("An existing ChatGPT login is required")

    async def start_thread(self, request: ThreadStartRequest) -> BackendThread:
        context = request.context.validated()
        if context.sandbox is not SandboxMode.READ_ONLY:
            raise CodexPolicyError("CLI fallback is read-only")
        await self._require_chatgpt()
        thread_id = f"cli-ephemeral:{uuid.uuid4().hex}"
        self._threads[thread_id] = _CliThread(context=context)
        return BackendThread(
            thread_id=thread_id,
            backend=CodexBackendKind.CLI_FALLBACK,
            task_id=context.task_id,
            session_id=context.session_id,
            status="degraded_ephemeral",
        )

    async def resume_thread(self, request: ThreadResumeRequest) -> BackendThread:
        del request
        raise CodexCapabilityError(
            "CLI fallback cannot resume threads; no continuation is simulated"
        )

    async def fork_thread(self, request: ThreadForkRequest) -> BackendThread:
        del request
        raise CodexCapabilityError("CLI fallback cannot fork threads")

    async def list_threads(self, *, limit: int = 100) -> list[BackendThread]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return [
            BackendThread(
                thread_id=thread_id,
                backend=CodexBackendKind.CLI_FALLBACK,
                task_id=thread.context.task_id,
                session_id=thread.context.session_id,
                status="degraded_ephemeral",
            )
            for thread_id, thread in list(self._threads.items())[:limit]
        ]

    async def start_turn(self, request: TurnStartRequest) -> BackendTurn:
        context = request.context.validated()
        if context.sandbox is not SandboxMode.READ_ONLY:
            raise CodexPolicyError("CLI fallback is read-only")
        if not request.prompt.strip():
            raise CodexPolicyError("turn prompt must be non-empty")
        thread = self._threads.get(request.thread_id)
        if thread is None:
            raise CodexCapabilityError("unknown ephemeral CLI thread")
        if thread.used:
            raise CodexCapabilityError(
                "CLI fallback allows one turn and cannot continue it"
            )
        if (
            thread.context.task_id != context.task_id
            or thread.context.session_id != context.session_id
        ):
            raise CodexPolicyError("turn context does not own the CLI thread")
        if not self._schema_path.is_file():
            raise CodexBackendError("CLI fallback output schema is unavailable")

        thread.used = True
        turn_id = f"cli-turn:{uuid.uuid4().hex}"
        command = self._command(context)
        prompt = self._prompt(context, request.prompt)
        started = time.monotonic()
        try:
            result = await self._runner(
                command,
                context.cwd.resolve(strict=False),
                self._environment,
                context.timeout_seconds,
                prompt,
            )
        except asyncio.TimeoutError as exc:
            raise CodexTimeoutError("Codex CLI fallback timed out") from exc
        if result.returncode != 0:
            raise CodexBackendError(
                safe_error_message(
                    RuntimeError(
                        result.stderr.strip()
                        or f"Codex CLI exited with {result.returncode}"
                    )
                )
            )

        raw_events = self._parse_jsonl(result.stdout)
        if len(raw_events) > context.step_limit:
            raise CodexPolicyError("CLI fallback step limit exceeded")
        final = self._validated_final(raw_events)
        total_tokens = self._total_tokens(raw_events)
        if context.token_limit is not None and total_tokens > context.token_limit:
            raise CodexPolicyError("CLI fallback token limit exceeded")
        self._turn_events[turn_id] = self._events_for_result(
            context=context,
            thread_id=request.thread_id,
            turn_id=turn_id,
            final=final,
            total_tokens=total_tokens,
            duration_seconds=time.monotonic() - started,
        )
        return BackendTurn(
            turn_id=turn_id,
            thread_id=request.thread_id,
            backend=CodexBackendKind.CLI_FALLBACK,
            status="completed",
        )

    async def stream_events(self, turn_id: str) -> AsyncIterator[CodexEvent]:
        events = self._turn_events.pop(turn_id, None)
        if events is None:
            raise CodexCapabilityError(f"unknown completed CLI turn: {turn_id}")
        for event in events:
            yield event

    async def steer(self, turn_id: str, prompt: str) -> None:
        del turn_id, prompt
        raise CodexCapabilityError("CLI fallback cannot steer turns")

    async def interrupt(self, turn_id: str) -> None:
        del turn_id
        raise CodexCapabilityError("CLI fallback has no interactive turn handle")

    async def read_thread(self, thread_id: str) -> object:
        del thread_id
        raise CodexCapabilityError(
            "CLI fallback has no persistent thread state to read"
        )

    async def close(self) -> None:
        self._threads.clear()
        self._turn_events.clear()

    def _command(self, context: CodexRunContext) -> tuple[str, ...]:
        command = [
            self._binary(),
            "exec",
            "--json",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox",
            "read-only",
            "-c",
            'approval_policy="never"',
            "--cd",
            str(context.cwd.resolve(strict=False)),
            "--skip-git-repo-check",
            "--output-schema",
            str(self._schema_path.resolve(strict=True)),
            "--color",
            "never",
        ]
        if context.model.model:
            command.extend(("--model", context.model.model))
        if context.model.effort:
            command.extend(
                (
                    "-c",
                    f"model_reasoning_effort={json.dumps(context.model.effort)}",
                )
            )
        if context.model.service_tier:
            command.extend(
                (
                    "-c",
                    f"service_tier={json.dumps(context.model.service_tier)}",
                )
            )
        command.append("-")
        return tuple(command)

    @staticmethod
    def _prompt(context: CodexRunContext, prompt: str) -> str:
        instructions = redact_text(context.developer_instructions or "")
        prefix = (
            "This is an isolated, read-only OpenJarvis emergency run. "
            "Do not modify files, use external services, or request approvals. "
            "Return only the object required by the supplied JSON schema."
        )
        if instructions:
            prefix = f"{prefix}\nRedacted developer instructions:\n{instructions}"
        return f"{prefix}\nTask:\n{prompt}"

    @staticmethod
    def _parse_jsonl(stdout: str) -> list[dict[str, object]]:
        events: list[dict[str, object]] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise CodexBackendError(
                    "Codex CLI emitted invalid JSONL"
                ) from exc
            if not isinstance(value, dict):
                raise CodexBackendError("Codex CLI emitted a non-object event")
            events.append(value)
        if not events:
            raise CodexBackendError("Codex CLI emitted no JSON events")
        return events

    @staticmethod
    def _validated_final(events: list[dict[str, object]]) -> dict[str, str]:
        text: str | None = None
        for event in events:
            item = event.get("item")
            if event.get("type") != "item.completed" or not isinstance(item, dict):
                continue
            if item.get("type") not in {"agent_message", "agentMessage"}:
                continue
            candidate = item.get("text")
            if isinstance(candidate, str):
                text = candidate
        if text is None:
            raise CodexBackendError("Codex CLI returned no final agent message")
        try:
            final = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CodexBackendError(
                "Codex CLI final response did not match the required schema"
            ) from exc
        if (
            not isinstance(final, dict)
            or set(final) != {"summary"}
            or not isinstance(final["summary"], str)
            or not final["summary"].strip()
        ):
            raise CodexBackendError(
                "Codex CLI final response did not match the required schema"
            )
        return {"summary": redact_text(final["summary"])}

    @staticmethod
    def _total_tokens(events: list[dict[str, object]]) -> int:
        total = 0
        for event in events:
            usage = event.get("usage")
            if not isinstance(usage, dict):
                continue
            explicit = usage.get("total_tokens")
            if isinstance(explicit, int):
                total = max(total, explicit)
                continue
            input_tokens = usage.get("input_tokens")
            output_tokens = usage.get("output_tokens")
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                total = max(total, input_tokens + output_tokens)
        return total

    @staticmethod
    def _events_for_result(
        *,
        context: CodexRunContext,
        thread_id: str,
        turn_id: str,
        final: dict[str, str],
        total_tokens: int,
        duration_seconds: float,
    ) -> list[CodexEvent]:
        specifications = [
            (CodexEventType.THREAD_STARTED, {"ephemeral": True}),
            (CodexEventType.TURN_STARTED, {"degraded": True}),
            (CodexEventType.ITEM_COMPLETED, {"final": final}),
            (
                CodexEventType.USAGE_UPDATED,
                {"tokenUsage": {"total": {"totalTokens": total_tokens}}},
            ),
            (
                CodexEventType.TURN_COMPLETED,
                {"durationSeconds": duration_seconds, "degraded": True},
            ),
        ]
        occurred_at = datetime.now(timezone.utc).isoformat()
        return [
            CodexEvent(
                event_id=uuid.uuid4().hex,
                sequence=sequence,
                occurred_at=occurred_at,
                task_id=context.task_id,
                session_id=context.session_id,
                thread_id=thread_id,
                turn_id=turn_id,
                item_id=None,
                backend=CodexBackendKind.CLI_FALLBACK,
                event_type=event_type,
                payload=redact_data(payload),
            )
            for sequence, (event_type, payload) in enumerate(
                specifications,
                start=1,
            )
        ]


async def _run_cli(
    command: Sequence[str],
    cwd: Path,
    environment: Mapping[str, str],
    timeout: float,
    stdin_text: str | None,
) -> CliProcessResult:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=(
                asyncio.subprocess.PIPE
                if stdin_text is not None
                else asyncio.subprocess.DEVNULL
            ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
            env=dict(environment),
            creationflags=creationflags,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(
                    stdin_text.encode("utf-8") if stdin_text is not None else None
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            raise
    except asyncio.TimeoutError:
        raise
    except Exception as exc:
        raise CodexBackendError(safe_error_message(exc)) from exc
    return CliProcessResult(
        returncode=process.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=redact_text(stderr.decode("utf-8", errors="replace")),
    )


__all__ = [
    "CliProcessResult",
    "CliRunner",
    "CodexCliFallbackBackend",
]
