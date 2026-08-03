"""Primary Codex backend using the public asynchronous Python SDK."""

from __future__ import annotations

import asyncio
import inspect
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

from openjarvis.codex.events import CodexEventAdapter, is_counted_step
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
    CodexModelConfig,
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
class _SdkLaunchSpec:
    """SDK launch values kept independent of the optional dependency."""

    codex_bin: str | None
    cwd: str | None
    env: dict[str, str]
    client_name: str
    client_title: str
    client_version: str
    experimental_api: bool


@dataclass(slots=True)
class _ActiveTurn:
    handle: Any
    context: CodexRunContext
    started_monotonic: float


class _ThreadEvidenceClientProxy:
    """Capture typed app-server thread responses the high-level SDK discards."""

    def __init__(self, target: Any, capture: Callable[[Any, str], None]) -> None:
        self._target = target
        self._capture = capture

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    async def thread_start(self, params: Any) -> Any:
        response = await self._target.thread_start(params)
        self._capture(response, "python_sdk_app_server_thread_start")
        return response

    async def thread_resume(self, thread_id: str, params: Any) -> Any:
        response = await self._target.thread_resume(thread_id, params)
        self._capture(response, "python_sdk_app_server_thread_resume")
        return response


class CodexPythonSdkBackend:
    """Credential-safe adapter for the public ``AsyncCodex`` API."""

    _CAPABILITIES = BackendCapabilities(
        persistent_threads=True,
        resume=True,
        fork=True,
        streaming=True,
        steer=True,
        interrupt=True,
        command_approvals=False,
        file_approvals=False,
        full_item_events=True,
        usage_events=True,
        read_only=True,
        workspace_write=True,
    )

    def __init__(
        self,
        *,
        sdk_factory: Callable[[_SdkLaunchSpec], Any] | None = None,
        codex_bin: str | None = None,
        environment: dict[str, str] | None = None,
        store: CodexStateStore | None = None,
        state_db_path: str | Path | None = None,
        require_model_confirmation: bool = False,
    ) -> None:
        self._sdk_factory = sdk_factory
        self._codex_bin = codex_bin
        self._uses_installed_sdk = sdk_factory is None
        self._uses_pinned_runtime = sdk_factory is None and codex_bin is None
        self._environment = sanitized_codex_environment(environment)
        self._require_model_confirmation = require_model_confirmation
        self._client: Any | None = None
        self._client_lock = asyncio.Lock()
        self._store = store
        self._state_db_path = state_db_path
        self._owns_store = store is None
        self._event_adapter: CodexEventAdapter | None = (
            CodexEventAdapter(store) if store is not None else None
        )
        self._threads: dict[str, Any] = {}
        self._thread_contexts: dict[str, CodexRunContext] = {}
        self._thread_evidence: dict[str, tuple[str | None, str | None, str]] = {}
        self._turns: dict[str, _ActiveTurn] = {}

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._CAPABILITIES

    def _runtime_version(self) -> str | None:
        try:
            return metadata.version("openai-codex-cli-bin")
        except metadata.PackageNotFoundError:
            return None

    def _sdk_version(self) -> str | None:
        if not self._uses_installed_sdk:
            return None
        try:
            return metadata.version("openai-codex")
        except metadata.PackageNotFoundError:
            return None

    def _pinned_runtime_version(self) -> str | None:
        return self._runtime_version() if self._uses_pinned_runtime else None

    def _launch_spec(self) -> _SdkLaunchSpec:
        return _SdkLaunchSpec(
            codex_bin=self._codex_bin,
            cwd=None,
            env=dict(self._environment),
            client_name="openjarvis",
            client_title="OpenJarvis Codex Backend",
            client_version="0.1.0",
            experimental_api=False,
        )

    async def _get_client(self) -> Any:
        async with self._client_lock:
            return await self._get_client_unlocked()

    async def _get_client_unlocked(self) -> Any:
        if self._client is not None:
            return self._client

        spec = self._launch_spec()
        if self._sdk_factory is not None:
            client = self._sdk_factory(spec)
        else:
            try:
                from openai_codex import AsyncCodex, CodexConfig
            except ImportError as exc:
                raise CodexBackendError(
                    "Codex Python SDK is not installed; install OpenJarvis[codex]"
                ) from exc
            config = CodexConfig(
                codex_bin=spec.codex_bin,
                cwd=spec.cwd,
                env=spec.env,
                client_name=spec.client_name,
                client_title=spec.client_title,
                client_version=spec.client_version,
                experimental_api=spec.experimental_api,
            )
            client = AsyncCodex(config)

        if inspect.isawaitable(client):
            client = await client
        if self._uses_installed_sdk:
            low_level = getattr(client, "_client", None)
            if low_level is not None:
                try:
                    client._client = _ThreadEvidenceClientProxy(  # noqa: SLF001
                        low_level,
                        self._capture_thread_evidence,
                    )
                except (AttributeError, TypeError):
                    pass
        self._client = client
        return client

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

    def _capture_thread_evidence(self, response: Any, source: str) -> None:
        """Store only typed fields from a successful pinned lifecycle response."""

        thread = getattr(response, "thread", None)
        thread_id = getattr(thread, "id", None)
        model = getattr(response, "model", None)
        effort = getattr(response, "reasoning_effort", None)
        effort = getattr(effort, "value", effort)
        if thread_id:
            self._thread_evidence[str(thread_id)] = (
                model.strip() if isinstance(model, str) and model.strip() else None,
                effort.strip() if isinstance(effort, str) and effort.strip() else None,
                source,
            )

    @staticmethod
    def _model_dump(value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            dumped = value.model_dump(mode="json", by_alias=True)
            return dumped if isinstance(dumped, dict) else {}
        if isinstance(value, dict):
            return dict(value)
        return {}

    async def health(self) -> CodexHealth:
        """Check runtime and account mode without exposing credential material."""

        runtime_version = self._runtime_version()
        try:
            client = await self._get_client()
            response = await client.account(refresh_token=False)
            data = self._model_dump(response)
            account = data.get("account")
            account_data = account if isinstance(account, dict) else {}
            auth_mode = account_data.get("type")
            authenticated = auth_mode == "chatgpt"
            detail = None if authenticated else "A ChatGPT Codex login is required"
            return CodexHealth(
                available=True,
                authenticated=authenticated,
                auth_mode=str(auth_mode) if auth_mode else None,
                runtime_version=runtime_version,
                backend=CodexBackendKind.PYTHON_SDK,
                capabilities=self.capabilities,
                detail=detail,
            )
        except Exception as exc:
            return CodexHealth(
                available=False,
                authenticated=False,
                auth_mode=None,
                runtime_version=runtime_version,
                backend=CodexBackendKind.PYTHON_SDK,
                capabilities=self.capabilities,
                detail=safe_error_message(exc),
            )

    async def _require_chatgpt(self) -> None:
        report = await self.health()
        if not report.available:
            raise CodexBackendError(report.detail or "Codex SDK unavailable")
        if not report.authenticated or report.auth_mode != "chatgpt":
            raise CodexAuthenticationError("An existing ChatGPT login is required")

    async def start_thread(self, request: ThreadStartRequest) -> BackendThread:
        context = request.context.validated()
        store = self._get_store()
        existing = store.get_thread_by_correlation(context.correlation_id)
        if existing is not None:
            return self._backend_thread(existing)

        await self._require_chatgpt()
        client = await self._get_client()
        try:
            thread = await client.thread_start(
                approval_mode=self._sdk_approval_mode(context.approval_mode),
                config=self._sdk_model_config(context.model),
                cwd=str(context.cwd.resolve(strict=False)),
                developer_instructions=redact_text(context.developer_instructions or "")
                or None,
                ephemeral=False,
                model=context.model.model,
                sandbox=self._sdk_sandbox(context.sandbox),
                service_tier=context.model.service_tier,
            )
        except Exception as exc:
            raise CodexBackendError(safe_error_message(exc)) from exc

        thread_id = self._required_id(thread, "thread")
        actual_model, actual_effort, evidence_source = self._thread_evidence.pop(
            thread_id, (None, None, "unknown")
        )
        self._verify_model_evidence(context.model, actual_model, actual_effort)
        now = self._now()
        record = store.save_thread(
            CodexThreadRecord(
                task_id=context.task_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                thread_id=thread_id,
                backend=CodexBackendKind.PYTHON_SDK,
                sandbox=context.sandbox,
                approval_mode=context.approval_mode,
                cwd=str(context.cwd.resolve(strict=False)),
                model_config=with_confirmed_model_evidence(
                    asdict(context.model),
                    actual_model=actual_model,
                    actual_effort=actual_effort,
                    source=evidence_source,
                ),
                status="started",
                created_at=now,
                updated_at=now,
            )
        )
        self._threads[thread_id] = thread
        self._thread_contexts[thread_id] = context
        self._events().emit(
            CodexEventType.THREAD_STARTED,
            context=context,
            backend=CodexBackendKind.PYTHON_SDK,
            thread_id=thread_id,
            payload={"status": "started"},
            event_id=f"sdk:{thread_id}:started",
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

        await self._require_chatgpt()
        client = await self._get_client()
        try:
            thread = await client.thread_resume(
                thread_id,
                approval_mode=self._sdk_approval_mode(context.approval_mode),
                config=self._sdk_model_config(context.model),
                cwd=str(context.cwd.resolve(strict=False)),
                developer_instructions=redact_text(context.developer_instructions or "")
                or None,
                model=context.model.model,
                sandbox=self._sdk_sandbox(context.sandbox),
                service_tier=context.model.service_tier,
            )
        except Exception as exc:
            raise CodexBackendError(safe_error_message(exc)) from exc

        actual_id = self._required_id(thread, "thread")
        actual_model, actual_effort, evidence_source = self._thread_evidence.pop(
            actual_id, (None, None, "unknown")
        )
        self._verify_model_evidence(context.model, actual_model, actual_effort)
        now = self._now()
        persisted = store.save_thread(
            CodexThreadRecord(
                task_id=context.task_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                thread_id=actual_id,
                backend=CodexBackendKind.PYTHON_SDK,
                sandbox=context.sandbox,
                approval_mode=context.approval_mode,
                cwd=str(context.cwd.resolve(strict=False)),
                model_config=with_confirmed_model_evidence(
                    asdict(context.model),
                    actual_model=actual_model,
                    actual_effort=actual_effort,
                    source=evidence_source,
                ),
                status="resumed",
                created_at=record.created_at if record else now,
                updated_at=now,
                last_event_sequence=record.last_event_sequence if record else 0,
                resume_checkpoint=record.resume_checkpoint if record else None,
            )
        )
        store.update_thread(actual_id, status="resumed", updated_at=now)
        self._threads[actual_id] = thread
        self._thread_contexts[actual_id] = context
        self._events().emit(
            CodexEventType.THREAD_RESUMED,
            context=context,
            backend=CodexBackendKind.PYTHON_SDK,
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
        if existing is not None:
            return self._backend_thread(existing)

        await self._require_chatgpt()
        client = await self._get_client()
        try:
            thread = await client.thread_fork(
                request.source_thread_id,
                approval_mode=self._sdk_approval_mode(context.approval_mode),
                config=self._sdk_model_config(context.model),
                cwd=str(context.cwd.resolve(strict=False)),
                developer_instructions=redact_text(context.developer_instructions or "")
                or None,
                ephemeral=False,
                model=context.model.model,
                sandbox=self._sdk_sandbox(context.sandbox),
                service_tier=context.model.service_tier,
            )
        except Exception as exc:
            raise CodexBackendError(safe_error_message(exc)) from exc

        thread_id = self._required_id(thread, "thread")
        now = self._now()
        record = store.save_thread(
            CodexThreadRecord(
                task_id=context.task_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                thread_id=thread_id,
                backend=CodexBackendKind.PYTHON_SDK,
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
        self._threads[thread_id] = thread
        self._thread_contexts[thread_id] = context
        self._events().emit(
            CodexEventType.THREAD_STARTED,
            context=context,
            backend=CodexBackendKind.PYTHON_SDK,
            thread_id=thread_id,
            payload={"forked_from": request.source_thread_id},
        )
        return self._backend_thread(record)

    async def list_threads(self, *, limit: int = 100) -> list[BackendThread]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return [
            self._backend_thread(record)
            for record in self._get_store().list_threads(limit=limit)
        ]

    async def start_turn(self, request: TurnStartRequest) -> BackendTurn:
        context = request.context.validated()
        if not request.thread_id:
            raise CodexPolicyError("thread_id must be explicit")
        if not request.prompt.strip():
            raise CodexPolicyError("turn prompt must be non-empty")
        store = self._get_store()
        existing = store.get_turn_by_correlation(context.correlation_id)
        if existing is not None:
            return self._backend_turn(existing)
        thread_record = store.get_thread_by_id(request.thread_id)
        if thread_record is None:
            raise CodexCapabilityError("thread is not managed by OpenJarvis")
        if (
            thread_record.task_id != context.task_id
            or thread_record.session_id != context.session_id
        ):
            raise CodexPolicyError("turn context does not own the requested thread")

        await self._require_chatgpt()
        thread = self._threads.get(request.thread_id)
        if thread is None:
            thread = await self._resume_handle(request.thread_id, context)
            thread_record = store.get_thread_by_id(request.thread_id) or thread_record
        try:
            handle = await thread.turn(
                request.prompt,
                approval_mode=self._sdk_approval_mode(context.approval_mode),
                cwd=str(context.cwd.resolve(strict=False)),
                effort=context.model.effort,
                model=context.model.model,
                sandbox=self._sdk_sandbox(context.sandbox),
                service_tier=context.model.service_tier,
            )
        except Exception as exc:
            raise CodexBackendError(safe_error_message(exc)) from exc

        turn_id = self._required_id(handle, "turn")
        now = self._now()
        (
            actual_model,
            actual_effort,
            evidence_source,
        ) = resolve_turn_model_evidence(
            thread_record,
            requested_model=context.model.model,
            requested_effort=context.model.effort,
        )
        self._verify_model_evidence(context.model, actual_model, actual_effort)
        record = store.save_turn(
            CodexTurnRecord(
                turn_id=turn_id,
                task_id=context.task_id,
                session_id=context.session_id,
                correlation_id=context.correlation_id,
                thread_id=request.thread_id,
                backend=CodexBackendKind.PYTHON_SDK,
                sandbox=context.sandbox,
                approval_mode=context.approval_mode,
                cwd=str(context.cwd.resolve(strict=False)),
                runtime_evidence={
                    "requested_model": context.model.model,
                    "requested_effort": context.model.effort,
                    "actual_model": actual_model,
                    "actual_effort": actual_effort,
                    "evidence_source": evidence_source,
                    "sdk_version": self._sdk_version(),
                    "runtime_version": self._pinned_runtime_version(),
                },
                status="started",
                created_at=now,
                updated_at=now,
            )
        )
        self._turns[turn_id] = _ActiveTurn(
            handle=handle,
            context=context,
            started_monotonic=time.monotonic(),
        )
        return self._backend_turn(record)

    async def stream_events(self, turn_id: str) -> AsyncIterator[CodexEvent]:
        active = self._turns.get(turn_id)
        if active is None:
            raise CodexCapabilityError(f"unknown active turn: {turn_id}")
        turn_record = self._get_store().get_turn(turn_id)
        if turn_record is None:
            raise CodexCapabilityError(f"turn is not persisted: {turn_id}")

        iterator = active.handle.stream().__aiter__()
        counted_steps: set[str] = set()
        try:
            while True:
                elapsed = time.monotonic() - active.started_monotonic
                remaining = active.context.timeout_seconds - elapsed
                if remaining <= 0:
                    async for event in self._limit_failure(
                        active,
                        turn_record,
                        "turn timeout exceeded",
                        timeout=True,
                    ):
                        yield event
                    raise CodexTimeoutError("turn timeout exceeded")
                try:
                    raw = await asyncio.wait_for(iterator.__anext__(), remaining)
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError as exc:
                    async for event in self._limit_failure(
                        active,
                        turn_record,
                        "turn timeout exceeded",
                        timeout=True,
                    ):
                        yield event
                    raise CodexTimeoutError("turn timeout exceeded") from exc

                event = self._events().normalize(
                    raw,
                    context=active.context,
                    backend=CodexBackendKind.PYTHON_SDK,
                    thread_id=turn_record.thread_id,
                    turn_id=turn_id,
                )
                if event is None:
                    continue
                if is_counted_step(event):
                    counted_steps.add(event.item_id or event.event_id)
                if len(counted_steps) > active.context.step_limit:
                    async for failure in self._limit_failure(
                        active,
                        turn_record,
                        "turn step limit exceeded",
                    ):
                        yield failure
                    raise CodexPolicyError("turn step limit exceeded")
                if self._token_limit_exceeded(event, active.context.token_limit):
                    async for failure in self._limit_failure(
                        active,
                        turn_record,
                        "turn token limit exceeded",
                    ):
                        yield failure
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
                        turn_record.thread_id,
                        status="idle",
                        updated_at=now,
                        resume_checkpoint=turn_id,
                    )
        finally:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                result = close()
                if inspect.isawaitable(result):
                    await result
            self._turns.pop(turn_id, None)

    async def steer(self, turn_id: str, prompt: str) -> None:
        if not prompt.strip():
            raise CodexPolicyError("steer prompt must be non-empty")
        active = self._turns.get(turn_id)
        if active is None:
            raise CodexCapabilityError(f"unknown active turn: {turn_id}")
        try:
            await active.handle.steer(prompt)
        except Exception as exc:
            raise CodexBackendError(safe_error_message(exc)) from exc

    async def interrupt(self, turn_id: str) -> None:
        active = self._turns.get(turn_id)
        if active is None:
            raise CodexCapabilityError(f"unknown active turn: {turn_id}")
        try:
            await active.handle.interrupt()
        except Exception as exc:
            raise CodexBackendError(safe_error_message(exc)) from exc
        self._get_store().update_turn(
            turn_id,
            status="interrupted",
            updated_at=self._now(),
        )

    async def read_thread(self, thread_id: str) -> Any:
        record = self._get_store().get_thread_by_id(thread_id)
        if record is None:
            raise CodexCapabilityError("thread is not managed by OpenJarvis")
        context = self._thread_contexts.get(thread_id) or self._context_from_record(
            record
        )
        await self._require_chatgpt()
        thread = self._threads.get(thread_id)
        if thread is None:
            thread = await self._resume_handle(thread_id, context)
        try:
            response = await thread.read(include_turns=True)
        except Exception as exc:
            raise CodexBackendError(safe_error_message(exc)) from exc
        return redact_data(self._model_dump(response))

    async def close(self) -> None:
        try:
            if self._client is not None:
                result = self._client.close()
                if inspect.isawaitable(result):
                    await result
        finally:
            self._client = None
            self._threads.clear()
            self._thread_contexts.clear()
            self._turns.clear()
            if self._owns_store and self._store is not None:
                self._store.close()
                self._store = None
                self._event_adapter = None

    @staticmethod
    def redact(value: Any) -> Any:
        """Expose the shared redactor for normalized diagnostic payloads."""

        return redact_data(value)

    async def _resume_handle(self, thread_id: str, context: CodexRunContext) -> Any:
        client = await self._get_client()
        try:
            thread = await client.thread_resume(
                thread_id,
                approval_mode=self._sdk_approval_mode(context.approval_mode),
                config=self._sdk_model_config(context.model),
                cwd=str(context.cwd.resolve(strict=False)),
                developer_instructions=redact_text(context.developer_instructions or "")
                or None,
                model=context.model.model,
                sandbox=self._sdk_sandbox(context.sandbox),
                service_tier=context.model.service_tier,
            )
        except Exception as exc:
            raise CodexBackendError(safe_error_message(exc)) from exc
        actual_model, actual_effort, evidence_source = self._thread_evidence.pop(
            thread_id, (None, None, "unknown")
        )
        self._verify_model_evidence(context.model, actual_model, actual_effort)
        self._get_store().update_thread_model_evidence(
            thread_id,
            actual_model=actual_model,
            actual_effort=actual_effort,
            evidence_source=evidence_source,
        )
        self._threads[thread_id] = thread
        self._thread_contexts[thread_id] = context
        return thread

    def _verify_model_evidence(
        self,
        requested: CodexModelConfig,
        actual_model: str | None,
        actual_effort: str | None,
    ) -> None:
        if not self._require_model_confirmation:
            return
        if not requested.model:
            raise CodexPolicyError("A product Codex turn requires an explicit model")
        if actual_model != requested.model:
            resolved = actual_model or "unconfirmed"
            raise CodexCapabilityError(
                "Codex runtime did not confirm the requested model "
                f"{requested.model!r}; resolved {resolved!r}"
            )
        if requested.effort and actual_effort != requested.effort:
            resolved = actual_effort or "unconfirmed"
            raise CodexCapabilityError(
                "Codex runtime did not confirm the requested reasoning effort "
                f"{requested.effort!r}; resolved {resolved!r}"
            )

    @staticmethod
    def _sdk_model_config(model: CodexModelConfig) -> dict[str, str] | None:
        """Return per-thread model settings that the flat SDK omits.

        The SDK exposes ``model`` and ``service_tier`` as first-class thread
        arguments, while reasoning effort remains a Codex config override.
        Supplying it per thread prevents a user's global Codex default from
        silently replacing OpenJarvis' requested effort.
        """

        if not model.effort:
            return None
        return {"model_reasoning_effort": model.effort}

    async def _limit_failure(
        self,
        active: _ActiveTurn,
        turn_record: CodexTurnRecord,
        message: str,
        *,
        timeout: bool = False,
    ) -> AsyncIterator[CodexEvent]:
        try:
            await active.handle.interrupt()
        except Exception:
            pass
        now = self._now()
        self._get_store().update_turn(
            turn_record.turn_id,
            status="failed",
            updated_at=now,
        )
        event = self._events().emit(
            CodexEventType.ERROR,
            context=active.context,
            backend=CodexBackendKind.PYTHON_SDK,
            thread_id=turn_record.thread_id,
            turn_id=turn_record.turn_id,
            payload={"message": message, "timeout": timeout},
        )
        if event is not None:
            yield event

    @staticmethod
    def _token_limit_exceeded(
        event: CodexEvent,
        limit: int | None,
    ) -> bool:
        if limit is None or event.event_type is not CodexEventType.USAGE_UPDATED:
            return False
        payload = event.payload
        token_usage = payload.get("tokenUsage")
        if not isinstance(token_usage, dict):
            return False
        total = token_usage.get("total")
        if not isinstance(total, dict):
            return False
        value = total.get("totalTokens")
        return isinstance(value, int) and value > limit

    @staticmethod
    def _sdk_approval_mode(mode: ApprovalMode) -> Any:
        if mode is not ApprovalMode.DENY_ALL:
            raise CodexPolicyError("Phase 2 requires ApprovalMode.deny_all")
        from openai_codex import ApprovalMode as SdkApprovalMode

        return SdkApprovalMode.deny_all

    @staticmethod
    def _sdk_sandbox(mode: SandboxMode) -> Any:
        from openai_codex import Sandbox as SdkSandbox

        if mode is SandboxMode.READ_ONLY:
            return SdkSandbox.read_only
        if mode is SandboxMode.WORKSPACE_WRITE:
            return SdkSandbox.workspace_write
        if mode is SandboxMode.FULL_ACCESS:
            return SdkSandbox.danger_full_access
        raise CodexPolicyError("unsupported sandbox mode")

    @staticmethod
    def _required_id(value: Any, kind: str) -> str:
        identifier = getattr(value, "id", None)
        if not identifier:
            raise CodexBackendError(f"Codex {kind} response did not contain an id")
        return str(identifier)

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
    def _context_from_record(record: CodexThreadRecord) -> CodexRunContext:
        model = record.model_config
        return CodexRunContext(
            task_id=record.task_id,
            session_id=record.session_id,
            correlation_id=record.correlation_id,
            cwd=Path(record.cwd),
            sandbox=record.sandbox,
            approval_mode=record.approval_mode,
            model=CodexModelConfig(
                model=model.get("model"),
                effort=model.get("effort"),
                service_tier=model.get("service_tier"),
            ),
            timeout_seconds=300,
            step_limit=100,
            token_limit=None,
            developer_instructions=None,
            isolated_workspace=(
                Path(record.cwd)
                if record.sandbox is SandboxMode.WORKSPACE_WRITE
                else None
            ),
        ).validated()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()


__all__ = ["CodexPythonSdkBackend"]
