from __future__ import annotations

from dataclasses import replace

import pytest

from openjarvis.codex import CodexBackendRouter
from openjarvis.codex.types import (
    BackendCapabilities,
    CodexBackendError,
    CodexBackendKind,
    CodexHealth,
)


def _capabilities(*, approvals: bool, persistent: bool = True):
    return BackendCapabilities(
        persistent_threads=persistent,
        resume=persistent,
        fork=persistent,
        streaming=persistent,
        steer=persistent,
        interrupt=persistent,
        command_approvals=approvals,
        file_approvals=approvals,
        full_item_events=persistent,
        usage_events=True,
        read_only=True,
        workspace_write=persistent,
    )


class FakeBackend:
    def __init__(self, health: CodexHealth) -> None:
        self._health = health
        self.capabilities = health.capabilities
        self.closed = 0

    async def health(self):
        return self._health

    async def close(self):
        self.closed += 1


def _health(
    backend: CodexBackendKind,
    *,
    available: bool = True,
    authenticated: bool = True,
    approvals: bool = False,
    persistent: bool = True,
) -> CodexHealth:
    return CodexHealth(
        available=available,
        authenticated=authenticated,
        auth_mode="chatgpt" if authenticated else None,
        runtime_version="test",
        backend=backend,
        capabilities=_capabilities(
            approvals=approvals,
            persistent=persistent,
        ),
        degraded_backend=backend is CodexBackendKind.CLI_FALLBACK,
        detail=None if available else "unavailable",
    )


@pytest.mark.asyncio
async def test_router_prefers_sdk_and_app_server_for_approvals() -> None:
    sdk = FakeBackend(_health(CodexBackendKind.PYTHON_SDK))
    app = FakeBackend(
        _health(CodexBackendKind.APP_SERVER, approvals=True)
    )
    cli = FakeBackend(
        _health(CodexBackendKind.CLI_FALLBACK, persistent=False)
    )
    router = CodexBackendRouter(
        sdk_backend=sdk,
        app_server_backend=app,
        cli_fallback_backend=cli,
        allow_cli_fallback=True,
    )

    assert await router.select() is sdk
    assert await router.select(require_interactive_approvals=True) is app


@pytest.mark.asyncio
async def test_router_never_uses_cli_without_explicit_opt_in() -> None:
    sdk_health = replace(
        _health(CodexBackendKind.PYTHON_SDK),
        available=False,
    )
    app_health = replace(
        _health(CodexBackendKind.APP_SERVER, approvals=True),
        available=False,
    )
    cli = FakeBackend(
        _health(CodexBackendKind.CLI_FALLBACK, persistent=False)
    )
    router = CodexBackendRouter(
        sdk_backend=FakeBackend(sdk_health),
        app_server_backend=FakeBackend(app_health),
        cli_fallback_backend=cli,
        allow_cli_fallback=False,
    )

    with pytest.raises(CodexBackendError, match="No eligible"):
        await router.select()


@pytest.mark.asyncio
async def test_router_explicitly_allows_degraded_cli() -> None:
    unavailable_sdk = FakeBackend(
        _health(CodexBackendKind.PYTHON_SDK, available=False)
    )
    unavailable_app = FakeBackend(
        _health(
            CodexBackendKind.APP_SERVER,
            available=False,
            approvals=True,
        )
    )
    cli = FakeBackend(
        _health(CodexBackendKind.CLI_FALLBACK, persistent=False)
    )
    router = CodexBackendRouter(
        sdk_backend=unavailable_sdk,
        app_server_backend=unavailable_app,
        cli_fallback_backend=cli,
        allow_cli_fallback=True,
    )

    assert await router.select() is cli
    with pytest.raises(CodexBackendError, match="No eligible"):
        await router.select(require_interactive_approvals=True)
