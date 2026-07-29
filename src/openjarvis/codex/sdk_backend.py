"""Primary Codex backend using the public asynchronous Python SDK."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from importlib import metadata
from typing import Any

from openjarvis.codex.redaction import (
    redact_data,
    safe_error_message,
    sanitized_codex_environment,
)
from openjarvis.codex.types import (
    BackendCapabilities,
    BackendThread,
    BackendTurn,
    CodexAuthenticationError,
    CodexBackendError,
    CodexBackendKind,
    CodexCapabilityError,
    CodexEvent,
    CodexHealth,
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
    ) -> None:
        self._sdk_factory = sdk_factory
        self._codex_bin = codex_bin
        self._environment = sanitized_codex_environment(environment)
        self._client: Any | None = None

    @property
    def capabilities(self) -> BackendCapabilities:
        return self._CAPABILITIES

    def _runtime_version(self) -> str | None:
        try:
            return metadata.version("openai-codex-cli-bin")
        except metadata.PackageNotFoundError:
            return None

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
        self._client = client
        return client

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
        del request
        raise CodexCapabilityError("SDK thread lifecycle is not initialized")

    async def resume_thread(self, request: ThreadResumeRequest) -> BackendThread:
        del request
        raise CodexCapabilityError("SDK thread lifecycle is not initialized")

    async def fork_thread(self, request: ThreadForkRequest) -> BackendThread:
        del request
        raise CodexCapabilityError("SDK thread lifecycle is not initialized")

    async def list_threads(self, *, limit: int = 100) -> list[BackendThread]:
        del limit
        raise CodexCapabilityError("SDK thread lifecycle is not initialized")

    async def start_turn(self, request: TurnStartRequest) -> BackendTurn:
        del request
        raise CodexCapabilityError("SDK turn lifecycle is not initialized")

    async def stream_events(self, turn_id: str) -> AsyncIterator[CodexEvent]:
        del turn_id
        raise CodexCapabilityError("SDK event streaming is not initialized")
        yield  # pragma: no cover

    async def steer(self, turn_id: str, prompt: str) -> None:
        del turn_id, prompt
        raise CodexCapabilityError("SDK steer is not initialized")

    async def interrupt(self, turn_id: str) -> None:
        del turn_id
        raise CodexCapabilityError("SDK interrupt is not initialized")

    async def read_thread(self, thread_id: str) -> Any:
        del thread_id
        raise CodexCapabilityError("SDK thread read is not initialized")

    async def close(self) -> None:
        if self._client is None:
            return
        try:
            result = self._client.close()
            if inspect.isawaitable(result):
                await result
        finally:
            self._client = None

    @staticmethod
    def redact(value: Any) -> Any:
        """Expose the shared redactor for normalized diagnostic payloads."""

        return redact_data(value)


__all__ = ["CodexPythonSdkBackend"]
