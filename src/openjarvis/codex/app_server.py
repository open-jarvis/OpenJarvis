"""Local stdio Codex app-server transport and backend."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import shutil
import subprocess
import time
from collections import deque
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from openjarvis.codex.approval import (
    ApprovalBroker,
    ApprovalDecision,
    ApprovalRequest,
    DenyApprovalBroker,
)
from openjarvis.codex.events import CodexEventAdapter
from openjarvis.codex.redaction import (
    redact_data,
    redact_text,
    safe_error_message,
    sanitized_codex_environment,
)
from openjarvis.codex.store import (
    CodexStateStore,
    CodexThreadRecord,
    CodexTurnRecord,
    resolve_turn_model_evidence,
    with_confirmed_model_evidence,
)
from openjarvis.codex.types import (
    ApprovalMode,
    BackendCapabilities,
    BackendThread,
    BackendTurn,
    CodexAuthenticationError,
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

_APPROVAL_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
}


class AppServerTransport:
    """Bounded JSONL transport for one local app-server child process."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        environment: Mapping[str, str] | None = None,
        approval_broker: ApprovalBroker | None = None,
        request_timeout: float = 30.0,
        queue_size: int = 256,
    ) -> None:
        if not command:
            raise ValueError("app-server command must not be empty")
        self._command = tuple(str(part) for part in command)
        self._cwd = str(cwd) if cwd is not None else None
        self._environment = sanitized_codex_environment(environment)
        self._approval_broker = approval_broker or DenyApprovalBroker()
        self._request_timeout = request_timeout
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=queue_size
        )
        self._stderr: deque[str] = deque(maxlen=100)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._next_request_id = 1
        self._write_lock = asyncio.Lock()
        self._server_request_lock = asyncio.Lock()
        self._responded_server_requests: set[str] = set()
        self._approval_response_count = 0
        self._process: asyncio.subprocess.Process | None = None
        self._stdout_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._closed = False

    @property
    def approval_response_count(self) -> int:
        return self._approval_response_count

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        return tuple(self._stderr)

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        if self.running:
            return
        if self._closed:
            raise CodexBackendError("app-server transport is closed")
        creationflags = 0
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._cwd,
                env=self._environment,
                creationflags=creationflags,
            )
        except Exception as exc:
            raise CodexBackendError(safe_error_message(exc)) from exc
        self._stdout_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        try:
            await self.request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "openjarvis",
                        "title": "OpenJarvis Codex App Server Backend",
                        "version": "0.1.0",
                    },
                    "capabilities": {"experimentalApi": False},
                },
            )
            await self.notify("initialized", {})
        except Exception:
            await self.close()
            raise

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        *,
        timeout: float | None = None,
    ) -> Any:
        if self._process is None or self._process.returncode is not None:
            raise CodexBackendError("app-server process is not running")
        request_id = self._next_request_id
        self._next_request_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        await self._send({"method": method, "id": request_id, "params": params})
        try:
            return await asyncio.wait_for(
                future,
                timeout=timeout or self._request_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise CodexTimeoutError(f"app-server request timed out: {method}") from exc
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"method": method, "params": params})

    async def next_message(self, *, timeout: float) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self._notifications.get(), timeout)
        except asyncio.TimeoutError as exc:
            raise CodexTimeoutError("app-server event stream timed out") from exc

    async def reconnect(self, *, safe: bool) -> None:
        if not safe:
            raise CodexPolicyError("reconnect requires an explicitly safe state")
        await self.close()
        self._closed = False
        self._responded_server_requests.clear()
        await self.start()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process is not None:
            if process.stdin is not None:
                process.stdin.close()
                wait_closed = getattr(process.stdin, "wait_closed", None)
                if wait_closed is not None:
                    try:
                        await wait_closed()
                    except (BrokenPipeError, ConnectionResetError):
                        pass
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
        for task in (self._stdout_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        error = CodexBackendError("app-server transport closed")
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        self._process = None
        self._stdout_task = None
        self._stderr_task = None

    async def _send(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise CodexBackendError("app-server stdin is unavailable")
        encoded = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        async with self._write_lock:
            process.stdin.write(encoded)
            try:
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise CodexBackendError("app-server stdin closed") from exc

    async def _read_stdout(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                await self._notifications.put(
                    {
                        "method": "error",
                        "params": {"message": "Invalid app-server JSON was ignored"},
                    }
                )
                continue
            if not isinstance(message, dict):
                continue
            if "id" in message and ("result" in message or "error" in message):
                request_id = message["id"]
                future = self._pending.get(request_id)
                if future is None or future.done():
                    continue
                if "error" in message:
                    future.set_exception(
                        CodexBackendError(
                            safe_error_message(
                                RuntimeError(json.dumps(message["error"]))
                            )
                        )
                    )
                else:
                    future.set_result(message.get("result"))
                continue
            if "id" in message and "method" in message:
                asyncio.create_task(self._handle_server_request(message))
                continue
            if "method" in message:
                await self._notifications.put(message)
        if not self._closed:
            error = CodexBackendError("app-server stdout closed unexpectedly")
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)

    async def _read_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None
        while True:
            line = await process.stderr.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip()
            self._stderr.append(redact_text(decoded))

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        request_id = str(message.get("id"))
        async with self._server_request_lock:
            if request_id in self._responded_server_requests:
                return
            self._responded_server_requests.add(request_id)

        method = str(message.get("method") or "")
        params = message.get("params")
        payload = redact_data(params if isinstance(params, dict) else {})
        if method in _APPROVAL_METHODS:
            request = ApprovalRequest(
                request_id=request_id,
                method=method,
                thread_id=self._string_value(payload, "threadId"),
                turn_id=self._string_value(payload, "turnId"),
                item_id=self._string_value(payload, "itemId"),
                payload=payload,
            )
            await self._notifications.put(
                {
                    "method": "approval/requested",
                    "eventId": f"approval:{request_id}:requested",
                    "params": payload,
                }
            )
            try:
                decision = await asyncio.wait_for(
                    self._approval_broker.resolve(request),
                    timeout=self._request_timeout,
                )
            except Exception:
                decision = ApprovalDecision.DECLINE
            if not isinstance(decision, ApprovalDecision):
                decision = ApprovalDecision.DECLINE
            await self._send(
                {"id": message.get("id"), "result": {"decision": decision.value}}
            )
            self._approval_response_count += 1
            await self._notifications.put(
                {
                    "method": "approval/resolved",
                    "eventId": f"approval:{request_id}:resolved",
                    "params": {**payload, "decision": decision.value},
                }
            )
            return
        await self._send(
            {
                "id": message.get("id"),
                "error": {
                    "code": -32601,
                    "message": "Unsupported server request",
                },
            }
        )

    @staticmethod
    def _string_value(payload: dict[str, Any], key: str) -> str | None:
        value = payload.get(key)
        return str(value) if value else None


@dataclass(slots=True)
class _AppServerTurn:
    context: CodexRunContext
    thread_id: str
    started_monotonic: float


class CodexAppServerBackend:
    """Codex backend with full event and approval fidelity over local stdio."""

    _CAPABILITIES = BackendCapabilities(
        persistent_threads=True,
        resume=True,
        fork=True,
        streaming=True,
        steer=True,
        interrupt=True,
        command_approvals=True,
        file_approvals=True,
        full_item_events=True,
        usage_events=True,
        read_only=True,
        workspace_write=True,
    )

    def __init__(
        self,
        *,
        transport: AppServerTransport | Any | None = None,
        codex_bin: str | Path | None = None,
        environment: Mapping[str, str] | None = None,
        approval_broker: ApprovalBroker | None = None,
        store: CodexStateStore | None = None,
        state_db_path: str | Path | None = None,
        request_timeout: float = 30.0,
    ) -> None:
        if request_timeout <= 0:
            raise ValueError("request_timeout must be positive")
        self._transport = transport
        self._codex_bin = Path(codex_bin) if codex_bin else None
        self._uses_pinned_runtime = transport is None and codex_bin is None
        self._environment = sanitized_codex_environment(environment)
        self._approval_broker = approval_broker
        self._store = store
        self._state_db_path = state_db_path
        self._request_timeout = request_timeout
        self._owns_store = store is None
        self._event_adapter = CodexEventAdapter(store) if store else None
        self._turns: dict[str, _AppServerTurn] = {}
        self._backlog: dict[str, deque[dict[str, Any]]] = {}

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._CAPABILITIES

    def _get_store(self) -> CodexStateStore:
        if self._store is None:
            if self._state_db_path is None:
                from openjarvis.core.paths import get_config_dir

                path: str | Path = get_config_dir() / "codex_state.db"
            else:
                path = self._state_db_path
            self._store = CodexStateStore(path)
            self._event_adapter = CodexEventAdapter(self._store)
        return self._store

    def _events(self) -> CodexEventAdapter:
        self._get_store()
        assert self._event_adapter is not None
        return self._event_adapter

    async def _get_transport(self) -> Any:
        if self._transport is None:
            binary = self._codex_bin
            if binary is None:
                try:
                    from codex_cli_bin import bundled_codex_path

                    binary = bundled_codex_path()
                except (ImportError, FileNotFoundError) as exc:
                    raise CodexBackendError(
                        "Pinned Codex app-server runtime is unavailable"
                    ) from exc
            self._transport = AppServerTransport(
                (str(binary), "app-server", "--listen", "stdio://"),
                environment=self._environment,
                approval_broker=self._approval_broker,
                request_timeout=self._request_timeout,
            )
        await self._transport.start()
        return self._transport

    def _runtime_version(self) -> str | None:
        try:
            return metadata.version("openai-codex-cli-bin")
        except metadata.PackageNotFoundError:
            return None

    def _pinned_runtime_version(self) -> str | None:
        return self._runtime_version() if self._uses_pinned_runtime else None

    async def health(self) -> CodexHealth:
        try:
            transport = await self._get_transport()
            result = await transport.request(
                "account/read",
                {"refreshToken": False},
            )
            account = result.get("account") if isinstance(result, dict) else None
            account_data = account if isinstance(account, dict) else {}
            auth_mode = account_data.get("type")
            authenticated = auth_mode == "chatgpt"
            return CodexHealth(
                available=True,
                authenticated=authenticated,
                auth_mode=str(auth_mode) if auth_mode else None,
                runtime_version=self._runtime_version(),
                backend=CodexBackendKind.APP_SERVER,
                capabilities=self.capabilities,
                detail=(
                    None
                    if authenticated
                    else "A ChatGPT Codex login is required"
                ),
            )
        except Exception as exc:
            return CodexHealth(
                available=False,
                authenticated=False,
                auth_mode=None,
                runtime_version=self._runtime_version(),
                backend=CodexBackendKind.APP_SERVER,
                capabilities=self.capabilities,
                detail=safe_error_message(exc),
            )

    async def _require_chatgpt(self) -> Any:
        health = await self.health()
        if not health.available:
            raise CodexBackendError(health.detail or "app-server unavailable")
        if not health.authenticated:
            raise CodexAuthenticationError("An existing ChatGPT login is required")
        return await self._get_transport()

    async def start_thread(self, request: ThreadStartRequest) -> BackendThread:
        context = request.context.validated()
        store = self._get_store()
        existing = store.get_thread_by_correlation(context.correlation_id)
        if existing:
            return self._backend_thread(existing)
        transport = await self._require_chatgpt()
        result = await transport.request(
            "thread/start",
            self._thread_params(context, ephemeral=False),
            timeout=context.timeout_seconds,
        )
        thread_id = self._response_id(result, "thread")
        actual_model, actual_effort = self._thread_response_evidence(result)
        now = self._now()
        record = store.save_thread(
            CodexThreadRecord(
                task_id=context.task_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                thread_id=thread_id,
                backend=CodexBackendKind.APP_SERVER,
                sandbox=context.sandbox,
                approval_mode=context.approval_mode,
                cwd=str(context.cwd.resolve(strict=False)),
                model_config=with_confirmed_model_evidence(
                    asdict(context.model),
                    actual_model=actual_model,
                    actual_effort=actual_effort,
                    source="app_server_thread_start",
                ),
                status="started",
                created_at=now,
                updated_at=now,
            )
        )
        self._events().emit(
            CodexEventType.THREAD_STARTED,
            context=context,
            backend=CodexBackendKind.APP_SERVER,
            thread_id=thread_id,
            payload={"status": "started"},
            event_id=f"app-server:{thread_id}:started",
        )
        return self._backend_thread(record)

    async def resume_thread(self, request: ThreadResumeRequest) -> BackendThread:
        context = request.context.validated()
        store = self._get_store()
        record = (
            store.get_thread_by_id(request.thread_id)
            if request.thread_id
            else store.get_thread(context.task_id, context.session_id)
        )
        thread_id = request.thread_id or (record.thread_id if record else None)
        if not thread_id:
            raise CodexCapabilityError("No persisted Codex thread mapping exists")
        transport = await self._require_chatgpt()
        params = self._thread_params(context)
        params["threadId"] = thread_id
        result = await transport.request(
            "thread/resume",
            params,
            timeout=context.timeout_seconds,
        )
        actual_id = self._response_id(result, "thread")
        actual_model, actual_effort = self._thread_response_evidence(result)
        now = self._now()
        persisted = store.save_thread(
            CodexThreadRecord(
                task_id=context.task_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                thread_id=actual_id,
                backend=CodexBackendKind.APP_SERVER,
                sandbox=context.sandbox,
                approval_mode=context.approval_mode,
                cwd=str(context.cwd.resolve(strict=False)),
                model_config=with_confirmed_model_evidence(
                    asdict(context.model),
                    actual_model=actual_model,
                    actual_effort=actual_effort,
                    source="app_server_thread_resume",
                ),
                status="resumed",
                created_at=record.created_at if record else now,
                updated_at=now,
                last_event_sequence=record.last_event_sequence if record else 0,
                resume_checkpoint=record.resume_checkpoint if record else None,
            )
        )
        store.update_thread(actual_id, status="resumed", updated_at=now)
        self._events().emit(
            CodexEventType.THREAD_RESUMED,
            context=context,
            backend=CodexBackendKind.APP_SERVER,
            thread_id=actual_id,
            payload={"status": "resumed"},
        )
        return self._backend_thread(persisted, status="resumed")

    async def fork_thread(self, request: ThreadForkRequest) -> BackendThread:
        context = request.context.validated()
        if not request.source_thread_id:
            raise CodexPolicyError("source_thread_id must be explicit")
        store = self._get_store()
        existing = store.get_thread_by_correlation(context.correlation_id)
        if existing:
            return self._backend_thread(existing)
        transport = await self._require_chatgpt()
        params = self._thread_params(context, ephemeral=False)
        params["threadId"] = request.source_thread_id
        result = await transport.request(
            "thread/fork",
            params,
            timeout=context.timeout_seconds,
        )
        thread_id = self._response_id(result, "thread")
        now = self._now()
        record = store.save_thread(
            CodexThreadRecord(
                task_id=context.task_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                thread_id=thread_id,
                backend=CodexBackendKind.APP_SERVER,
                sandbox=context.sandbox,
                approval_mode=context.approval_mode,
                cwd=str(context.cwd.resolve(strict=False)),
                model_config=asdict(context.model),
                status="forked",
                created_at=now,
                updated_at=now,
                resume_checkpoint=f"fork:{request.source_thread_id}",
            )
        )
        return self._backend_thread(record)

    async def list_threads(self, *, limit: int = 100) -> list[BackendThread]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return [
            self._backend_thread(record)
            for record in self._get_store().list_threads(limit=limit)
            if record.backend is CodexBackendKind.APP_SERVER
        ]

    async def start_turn(self, request: TurnStartRequest) -> BackendTurn:
        context = request.context.validated()
        if not request.prompt.strip():
            raise CodexPolicyError("turn prompt must be non-empty")
        store = self._get_store()
        existing = store.get_turn_by_correlation(context.correlation_id)
        if existing:
            if existing.thread_id != request.thread_id:
                raise CodexPolicyError(
                    "turn correlation already belongs to a different thread"
                )
            return self._backend_turn(existing)
        thread = store.get_thread_by_id(request.thread_id)
        if thread is None:
            raise CodexCapabilityError("thread is not managed by OpenJarvis")
        if (
            thread.task_id != context.task_id
            or thread.session_id != context.session_id
        ):
            raise CodexPolicyError("turn context does not own the requested thread")
        transport = await self._require_chatgpt()
        result = await transport.request(
            "turn/start",
            {
                "threadId": request.thread_id,
                "input": [{"type": "text", "text": request.prompt}],
                "approvalPolicy": self._approval_policy(context.approval_mode),
                "cwd": str(context.cwd.resolve(strict=False)),
                "effort": context.model.effort,
                "model": context.model.model,
                "sandboxPolicy": self._turn_sandbox(context),
                "serviceTier": context.model.service_tier,
            },
            timeout=context.timeout_seconds,
        )
        turn_id = self._response_id(result, "turn")
        now = self._now()
        (
            actual_model,
            actual_effort,
            evidence_source,
        ) = resolve_turn_model_evidence(
            thread,
            requested_model=context.model.model,
            requested_effort=context.model.effort,
        )
        record = store.save_turn(
            CodexTurnRecord(
                turn_id=turn_id,
                task_id=context.task_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                thread_id=request.thread_id,
                backend=CodexBackendKind.APP_SERVER,
                sandbox=context.sandbox,
                approval_mode=context.approval_mode,
                cwd=str(context.cwd.resolve(strict=False)),
                runtime_evidence={
                    "requested_model": context.model.model,
                    "requested_effort": context.model.effort,
                    "actual_model": actual_model,
                    "actual_effort": actual_effort,
                    "evidence_source": evidence_source,
                    "sdk_version": None,
                    "runtime_version": self._pinned_runtime_version(),
                },
                status="started",
                created_at=now,
                updated_at=now,
            )
        )
        self._turns[turn_id] = _AppServerTurn(
            context=context,
            thread_id=request.thread_id,
            started_monotonic=time.monotonic(),
        )
        return self._backend_turn(record)

    async def stream_events(self, turn_id: str) -> AsyncIterator[CodexEvent]:
        active = self._turns.get(turn_id)
        if active is None:
            raise CodexCapabilityError(f"unknown active turn: {turn_id}")
        transport = await self._get_transport()
        step_count = 0
        try:
            while True:
                remaining = active.context.timeout_seconds - (
                    time.monotonic() - active.started_monotonic
                )
                if remaining <= 0:
                    await self.interrupt(turn_id)
                    raise CodexTimeoutError("app-server turn timeout exceeded")
                message = await self._next_turn_message(
                    transport,
                    turn_id,
                    timeout=remaining,
                )
                event = self._events().normalize(
                    message,
                    context=active.context,
                    backend=CodexBackendKind.APP_SERVER,
                    thread_id=active.thread_id,
                    turn_id=turn_id,
                )
                if event is None:
                    continue
                step_count += 1
                if step_count > active.context.step_limit:
                    await self.interrupt(turn_id)
                    raise CodexPolicyError("turn step limit exceeded")
                if self._token_limit_exceeded(event, active.context.token_limit):
                    await self.interrupt(turn_id)
                    raise CodexPolicyError("turn token limit exceeded")
                yield event
                if event.event_type in {
                    CodexEventType.TURN_COMPLETED,
                    CodexEventType.TURN_FAILED,
                    CodexEventType.TURN_INTERRUPTED,
                }:
                    status = event.event_type.value.rsplit(".", 1)[-1]
                    now = self._now()
                    self._get_store().update_turn(
                        turn_id,
                        status=status,
                        updated_at=now,
                    )
                    self._get_store().update_thread(
                        active.thread_id,
                        status="idle",
                        updated_at=now,
                        resume_checkpoint=turn_id,
                    )
                    break
        finally:
            self._turns.pop(turn_id, None)

    async def steer(self, turn_id: str, prompt: str) -> None:
        if not prompt.strip():
            raise CodexPolicyError("steer prompt must be non-empty")
        active = self._turns.get(turn_id)
        if active is None:
            raise CodexCapabilityError(f"unknown active turn: {turn_id}")
        transport = await self._get_transport()
        await transport.request(
            "turn/steer",
            {
                "threadId": active.thread_id,
                "expectedTurnId": turn_id,
                "input": [{"type": "text", "text": prompt}],
            },
            timeout=active.context.timeout_seconds,
        )

    async def interrupt(self, turn_id: str) -> None:
        active = self._turns.get(turn_id)
        if active is None:
            raise CodexCapabilityError(f"unknown active turn: {turn_id}")
        transport = await self._get_transport()
        await transport.request(
            "turn/interrupt",
            {"threadId": active.thread_id, "turnId": turn_id},
            timeout=active.context.timeout_seconds,
        )
        self._get_store().update_turn(
            turn_id,
            status="interrupted",
            updated_at=self._now(),
        )

    async def read_thread(self, thread_id: str) -> Any:
        if self._get_store().get_thread_by_id(thread_id) is None:
            raise CodexCapabilityError("thread is not managed by OpenJarvis")
        transport = await self._require_chatgpt()
        result = await transport.request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
        )
        return redact_data(result)

    async def reconnect(self) -> None:
        if self._turns:
            raise CodexPolicyError("cannot reconnect while turns are active")
        transport = await self._get_transport()
        await transport.reconnect(safe=True)

    async def close(self) -> None:
        if self._transport is not None:
            result = self._transport.close()
            if inspect.isawaitable(result):
                await result
        self._turns.clear()
        self._backlog.clear()
        if self._owns_store and self._store is not None:
            self._store.close()
            self._store = None
            self._event_adapter = None

    async def _next_turn_message(
        self,
        transport: Any,
        turn_id: str,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        backlog = self._backlog.setdefault(turn_id, deque())
        if backlog:
            return backlog.popleft()
        while True:
            message = await transport.next_message(timeout=timeout)
            params = message.get("params")
            data = params if isinstance(params, dict) else {}
            message_turn = data.get("turnId")
            if not message_turn:
                turn = data.get("turn")
                if isinstance(turn, dict):
                    message_turn = turn.get("id")
            if not message_turn or str(message_turn) == turn_id:
                return message
            self._backlog.setdefault(str(message_turn), deque()).append(message)

    @staticmethod
    def _thread_params(
        context: CodexRunContext,
        *,
        ephemeral: bool | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "approvalPolicy": CodexAppServerBackend._approval_policy(
                context.approval_mode
            ),
            "approvalsReviewer": "user",
            "cwd": str(context.cwd.resolve(strict=False)),
            "developerInstructions": redact_text(
                context.developer_instructions or ""
            )
            or None,
            "model": context.model.model,
            "sandbox": CodexAppServerBackend._thread_sandbox(context.sandbox),
            "serviceTier": context.model.service_tier,
        }
        if ephemeral is not None:
            params["ephemeral"] = ephemeral
        return params

    @staticmethod
    def _thread_sandbox(mode: SandboxMode) -> str:
        if mode is SandboxMode.READ_ONLY:
            return "read-only"
        if mode is SandboxMode.WORKSPACE_WRITE:
            return "workspace-write"
        raise CodexPolicyError("full_access is prohibited")

    @staticmethod
    def _approval_policy(mode: ApprovalMode) -> str:
        if mode is ApprovalMode.DENY_ALL:
            return "never"
        if mode is ApprovalMode.BROKERED:
            return "on-request"
        raise CodexPolicyError("automatic approval review is prohibited")

    @staticmethod
    def _turn_sandbox(context: CodexRunContext) -> dict[str, Any]:
        if context.sandbox is SandboxMode.READ_ONLY:
            return {"type": "readOnly", "networkAccess": False}
        if context.sandbox is SandboxMode.WORKSPACE_WRITE:
            return {
                "type": "workspaceWrite",
                "writableRoots": [
                    str(context.isolated_workspace.resolve(strict=False))
                ],
                "networkAccess": False,
                "excludeSlashTmp": False,
                "excludeTmpdirEnvVar": False,
            }
        raise CodexPolicyError("full_access is prohibited")

    @staticmethod
    def _response_id(result: Any, kind: str) -> str:
        if not isinstance(result, dict):
            raise CodexBackendError(f"app-server {kind} response is invalid")
        value = result.get(kind)
        if isinstance(value, dict) and value.get("id"):
            return str(value["id"])
        raise CodexBackendError(f"app-server {kind} response did not contain an id")

    @staticmethod
    def _backend_thread(
        record: CodexThreadRecord,
        *,
        status: str | None = None,
    ) -> BackendThread:
        return BackendThread(
            thread_id=record.thread_id,
            backend=record.backend,
            task_id=record.task_id,
            session_id=record.session_id,
            status=status or record.status,
        )

    @staticmethod
    def _backend_turn(record: CodexTurnRecord) -> BackendTurn:
        return BackendTurn(
            turn_id=record.turn_id,
            thread_id=record.thread_id,
            backend=record.backend,
            status=record.status,
        )

    @staticmethod
    def _thread_response_evidence(
        result: Any,
    ) -> tuple[str | None, str | None]:
        """Read exact model fields from thread/start or thread/resume."""

        if not isinstance(result, dict):
            return None, None
        model = result.get("model")
        effort = result.get("reasoningEffort")
        return (
            model.strip() if isinstance(model, str) and model.strip() else None,
            effort.strip() if isinstance(effort, str) and effort.strip() else None,
        )

    @staticmethod
    def _token_limit_exceeded(
        event: CodexEvent,
        limit: int | None,
    ) -> bool:
        if limit is None or event.event_type is not CodexEventType.USAGE_UPDATED:
            return False
        usage = event.payload.get("tokenUsage")
        total = usage.get("total") if isinstance(usage, dict) else None
        value = total.get("totalTokens") if isinstance(total, dict) else None
        return isinstance(value, int) and value > limit

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


def find_global_codex() -> str | None:
    """Locate the global CLI only for explicit degraded fallback use."""

    return shutil.which("codex")


__all__ = [
    "AppServerTransport",
    "CodexAppServerBackend",
    "find_global_codex",
]
