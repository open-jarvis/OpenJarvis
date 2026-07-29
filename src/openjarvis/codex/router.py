"""Capability-aware routing across Codex backends."""

from __future__ import annotations

from collections.abc import Sequence

from openjarvis.codex.protocol import CodexBackend
from openjarvis.codex.types import (
    CodexBackendError,
    CodexBackendKind,
    CodexHealth,
)


class CodexBackendRouter:
    """Prefer the SDK, use app-server for approvals, and gate CLI fallback."""

    def __init__(
        self,
        *,
        sdk_backend: CodexBackend,
        app_server_backend: CodexBackend,
        cli_fallback_backend: CodexBackend | None = None,
        allow_cli_fallback: bool = False,
    ) -> None:
        self._sdk = sdk_backend
        self._app_server = app_server_backend
        self._cli = cli_fallback_backend
        self._allow_cli_fallback = allow_cli_fallback

    async def health(self) -> tuple[CodexHealth, ...]:
        """Return every configured backend report without selecting one."""

        backends = [self._sdk, self._app_server]
        if self._cli is not None:
            backends.append(self._cli)
        return tuple([await backend.health() for backend in backends])

    async def select(
        self,
        *,
        require_interactive_approvals: bool = False,
    ) -> CodexBackend:
        """Select an authenticated backend with no silent degraded fallback."""

        primary: Sequence[CodexBackend]
        if require_interactive_approvals:
            primary = (self._app_server,)
        else:
            primary = (self._sdk, self._app_server)
        failures: list[str] = []
        for backend in primary:
            health = await backend.health()
            if health.available and health.authenticated:
                if (
                    not require_interactive_approvals
                    or (
                        backend.capabilities.command_approvals
                        and backend.capabilities.file_approvals
                    )
                ):
                    return backend
            failures.append(
                f"{health.backend.value}: {health.detail or 'not authenticated'}"
            )

        if (
            not require_interactive_approvals
            and self._allow_cli_fallback
            and self._cli is not None
        ):
            health = await self._cli.health()
            if health.available and health.authenticated:
                return self._cli
            failures.append(
                f"{CodexBackendKind.CLI_FALLBACK.value}: "
                f"{health.detail or 'not authenticated'}"
            )
        raise CodexBackendError(
            "No eligible Codex backend is available: " + "; ".join(failures)
        )

    async def close(self) -> None:
        """Close each configured backend once."""

        seen: set[int] = set()
        for backend in (self._sdk, self._app_server, self._cli):
            if backend is None or id(backend) in seen:
                continue
            seen.add(id(backend))
            await backend.close()


__all__ = ["CodexBackendRouter"]
