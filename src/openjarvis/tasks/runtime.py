"""Shared construction of the OpenJarvis-owned Codex task runtime."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from openjarvis.codex.app_server import CodexAppServerBackend
from openjarvis.codex.cli_backend import CodexCliFallbackBackend
from openjarvis.codex.router import CodexBackendRouter
from openjarvis.codex.sdk_backend import CodexPythonSdkBackend
from openjarvis.codex.types import CodexModelConfig
from openjarvis.tasks.budget import BudgetLimits
from openjarvis.tasks.orchestrator import CodexTaskOrchestrator
from openjarvis.tasks.projection import CodexTaskEventProjector
from openjarvis.tasks.recovery import RecoveryCoordinator
from openjarvis.tasks.service import TaskService
from openjarvis.tasks.store import TaskStore

if TYPE_CHECKING:
    from openjarvis.core.config import CodexBackendConfig
    from openjarvis.core.events import EventBus
    from openjarvis.traces.store import TraceStore


@dataclass(frozen=True, slots=True)
class CodexTaskRuntime:
    """All Phase 3 services sharing one canonical task store."""

    store: TaskStore
    service: TaskService
    approval_broker: None
    orchestrator: CodexTaskOrchestrator
    recovery: RecoveryCoordinator


def build_codex_task_runtime(
    config: CodexBackendConfig,
    *,
    bus: EventBus,
    trace_store: TraceStore | None,
    flow_authority=None,
) -> CodexTaskRuntime:
    """Build one credential-safe runtime for both CLI and library entrypoints."""

    store = TaskStore(config.state_db_path)
    try:
        service = TaskService(store, bus=bus)
        if flow_authority is None:
            from openjarvis.flow import FlowSessionAuthority

            flow_authority = FlowSessionAuthority.from_environment()
        sdk_backend = CodexPythonSdkBackend(
            store=store,
            require_model_confirmation=config.require_model_confirmation,
        )
        app_backend = CodexAppServerBackend(
            codex_bin=config.app_server_binary or None,
            approval_broker=None,
            store=store,
            request_timeout=config.default_timeout_seconds,
        )
        cli_backend = None
        if config.allow_cli_fallback:
            cli_backend = CodexCliFallbackBackend(
                codex_bin=config.cli_binary or None,
            )
        router = CodexBackendRouter(
            sdk_backend=sdk_backend,
            app_server_backend=app_backend,
            cli_fallback_backend=cli_backend,
            allow_cli_fallback=config.allow_cli_fallback,
        )
        projector = CodexTaskEventProjector(
            store,
            bus=bus,
            trace_store=trace_store,
        )
        orchestrator = CodexTaskOrchestrator(
            router,
            service,
            projector,
            flow_authority=flow_authority,
            default_timeout_seconds=config.default_timeout_seconds,
            default_step_limit=config.default_step_limit,
            default_token_limit=(config.default_token_limit or None),
            budget_limits=BudgetLimits(
                max_turn_duration=config.max_turn_duration,
                max_steps=config.max_steps,
                max_input_tokens=config.max_input_tokens,
                max_output_tokens=config.max_output_tokens,
                max_total_tokens_per_task=config.max_total_tokens_per_task,
                warning_threshold=config.warning_threshold,
                hard_limit_action=config.hard_limit_action,
            ),
            default_model=CodexModelConfig(
                model=config.model or None,
                effort=config.reasoning_effort or None,
                service_tier=config.service_tier or None,
            ),
        )
        recovery = RecoveryCoordinator(store, service)
        recovery.recover_all_sync()
        return CodexTaskRuntime(
            store=store,
            service=service,
            approval_broker=None,
            orchestrator=orchestrator,
            recovery=recovery,
        )
    except Exception:
        store.close()
        raise


__all__ = ["CodexTaskRuntime", "build_codex_task_runtime"]
