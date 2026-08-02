"""Fail-closed Phase-8 product runtime and local launcher entry point.

This module deliberately does not construct an Ollama, cloud, browser, MCP, or
channel backend.  Conversational work is owned by the configured Codex task
runtime; the ``InferenceEngine`` below exists only so the legacy health surface
can report a local, offline-ready product process.
"""

from __future__ import annotations

import argparse
import hmac
import json
import os
import stat
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from fastapi import HTTPException, Request

from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.core.events import EventBus
from openjarvis.engine import InferenceEngine
from openjarvis.learning.runtime import Phase7LearningRuntime
from openjarvis.memory.vault_service import (
    VaultMemoryService,
    build_vault_memory_service,
)
from openjarvis.server.app import create_app
from openjarvis.tasks import ExecutionLane
from openjarvis.tasks.policy import RiskLevel, ToolPolicyContext
from openjarvis.tasks.runtime import CodexTaskRuntime, build_codex_task_runtime
from openjarvis.tools.action_service import ToolActionService
from openjarvis.tools.action_store import ActionStore
from openjarvis.tools.manifest import ToolManifestCatalog
from openjarvis.traces.store import TraceStore
from openjarvis.website import WebsiteStagingService, WebsiteWorkspaceStore

FINAL_HEALTH_MARKER = "OPENJARVIS-FINAL-RUNTIME"
FINAL_RUNTIME_NAME = "phase8-final"
FINAL_MODEL = "codex-python-sdk"
FINAL_CODEX_MODEL = "gpt-5.6-terra"
FINAL_CODEX_EFFORT = "xhigh"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_PILOT_WORKSPACE_ID = "phase8-final-website-pilot"


class FinalCodexHealthEngine(InferenceEngine):
    """Offline health adapter; generation must use the canonical Codex routes."""

    engine_id = "codex-final"
    is_cloud = False

    @staticmethod
    def _blocked() -> RuntimeError:
        return RuntimeError(
            "legacy inference is disabled; use the canonical Codex task API"
        )

    def generate(
        self,
        messages: Sequence[Any],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> dict[str, Any]:
        del messages, model, temperature, max_tokens, kwargs
        raise self._blocked()

    async def stream(
        self,
        messages: Sequence[Any],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ):
        del messages, model, temperature, max_tokens, kwargs
        raise self._blocked()
        yield ""  # pragma: no cover - keeps this an async generator

    def list_models(self) -> list[str]:
        return [FINAL_MODEL]

    def health(self) -> bool:
        return True

    def can_serve(self, model: str) -> bool:
        return model == FINAL_MODEL


@dataclass(slots=True)
class FinalRuntime:
    """References owned by one final FastAPI process."""

    app: Any
    config: JarvisConfig
    tasks: CodexTaskRuntime
    vault: VaultMemoryService
    trace_store: TraceStore
    action_store: ActionStore
    phase7: Phase7LearningRuntime
    staging_root: Path
    assistant_workspace: Path


def _is_reparse(path: Path) -> bool:
    metadata = path.lstat()
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(getattr(metadata, "st_file_attributes", 0) & flag)


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _normal_root(path: Path, *, label: str, create: bool = False) -> Path:
    candidate = path.expanduser()
    if create:
        for ancestor in (candidate, *candidate.parents):
            if ancestor.exists() and _is_reparse(ancestor):
                raise ValueError(f"{label} ancestry contains a reparse point")
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir() or _is_reparse(resolved):
        raise ValueError(f"{label} must be an existing normal directory")
    return resolved


def _toml_string(value: Path | str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def render_final_config(*, home: Path, vault: Path, host: str, port: int) -> str:
    """Return a secret-free final config whose mutable state stays under home."""

    if host not in _LOOPBACK_HOSTS or host == "localhost":
        raise ValueError("final runtime must bind to a numeric loopback host")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    state = home / "state"
    return f'''# Generated locally by openjarvis.final_runtime; contains no credentials.
[engine]
default = "codex-final"

[server]
host = {_toml_string(host)}
port = {port}
agent = ""
model = "{FINAL_MODEL}"
workers = 1

[analytics]
enabled = false

[telemetry]
enabled = false
db_path = {_toml_string(state / "telemetry.sqlite3")}

[traces]
enabled = true
db_path = {_toml_string(state / "traces.sqlite3")}

[codex]
enabled = true
primary_backend = "python_sdk"
approval_mode = "deny_all"
analysis_sandbox = "read_only"
model = "{FINAL_CODEX_MODEL}"
reasoning_effort = "{FINAL_CODEX_EFFORT}"
require_model_confirmation = true
state_db_path = {_toml_string(state / "codex.sqlite3")}
allow_cli_fallback = false
allow_global_cli_override = false

[sandbox]
enabled = false
workspace = {_toml_string(home / "assistant-workspace")}

[memory]
enabled = false
vault_path = {_toml_string(vault)}
vault_index_path = {_toml_string(state / "vault-index.sqlite3")}
vault_restore_path = {_toml_string(home / "restore" / "vault")}
vault_mode = "read-only"
vault_embeddings_enabled = false
vault_watch_enabled = false

[tools]
enabled = ""

[tools.mcp]
enabled = false
servers = ""

[agent]
default_agent = "simple"
tools = ""
context_from_memory = false

[channel]
enabled = false

[skills]
enabled = false
active = ""
auto_discover = false
auto_sync = false

[learning]
enabled = false
auto_update = false
training_enabled = false

[scheduler]
enabled = false

[workflow]
enabled = false

[sessions]
enabled = false

[agent_manager]
enabled = false

[compression]
enabled = false
'''


def write_final_config(
    *,
    home: Path,
    vault: Path,
    config_path: Path,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> Path:
    """Atomically create the uncommitted local config after root validation."""

    vault_root = _normal_root(vault, label="vault")
    repo_root = Path(__file__).resolve().parents[2]
    proposed_home = home.expanduser().resolve(strict=False)
    if _overlaps(proposed_home, repo_root) or _overlaps(proposed_home, vault_root):
        raise ValueError("OPENJARVIS_HOME must be outside both repository and vault")
    runtime_home = _normal_root(home, label="OPENJARVIS_HOME", create=True)
    destination = config_path.expanduser().resolve(strict=False)
    if not destination.is_relative_to(runtime_home):
        raise ValueError("final config must live under OPENJARVIS_HOME")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    temporary.write_text(
        render_final_config(home=runtime_home, vault=vault_root, host=host, port=port),
        encoding="utf-8",
        newline="\n",
    )
    try:
        os.chmod(temporary, 0o600)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _validate_loaded_config(config: JarvisConfig, *, home: Path, vault: Path) -> None:
    if config.server.host not in {"127.0.0.1", "::1"}:
        raise ValueError("server host is not loopback-bound")
    if not config.codex.enabled or config.codex.primary_backend != "python_sdk":
        raise ValueError("final runtime requires the Python Codex SDK backend")
    if (
        config.codex.approval_mode != "deny_all"
        or config.codex.analysis_sandbox != "read_only"
    ):
        raise ValueError("final Codex policy must be deny_all/read_only")
    if (
        config.codex.model != FINAL_CODEX_MODEL
        or config.codex.reasoning_effort != FINAL_CODEX_EFFORT
        or not config.codex.require_model_confirmation
    ):
        raise ValueError("final Codex model must be explicitly confirmed")
    if config.codex.allow_cli_fallback or config.codex.allow_global_cli_override:
        raise ValueError("CLI fallback is forbidden in the final runtime")
    if config.analytics.enabled or config.telemetry.enabled or config.tools.mcp.enabled:
        raise ValueError("analytics, telemetry, and MCP must be disabled")
    if config.channel.enabled or config.skills.enabled:
        raise ValueError("channels and automatic skills must be disabled")
    if config.scheduler.enabled or config.workflow.enabled or config.sessions.enabled:
        raise ValueError("background schedulers and workflows must be disabled")
    if (
        config.agent_manager.enabled
        or config.learning.enabled
        or config.learning.training_enabled
    ):
        raise ValueError("agent manager and autonomous learning must be disabled")
    configured_vault = Path(config.tools.storage.vault_path).resolve(strict=True)
    if configured_vault != vault:
        raise ValueError("config vault does not match the approved vault root")
    for raw in (
        config.codex.state_db_path,
        config.traces.db_path,
        config.tools.storage.vault_index_path,
        config.tools.storage.vault_restore_path,
        config.sandbox.workspace,
    ):
        if not Path(raw).resolve(strict=False).is_relative_to(home):
            raise ValueError("mutable runtime path escaped OPENJARVIS_HOME")


def build_final_runtime(
    *,
    home: Path,
    vault: Path,
    config_path: Path,
    shutdown_token: str,
    shutdown_callback: Callable[[], None] | None = None,
    initial_index: bool = True,
) -> FinalRuntime:
    """Build the bounded product app without starting a listener or SDK turn."""

    runtime_home = _normal_root(home, label="OPENJARVIS_HOME")
    vault_root = _normal_root(vault, label="vault")
    repo_root = Path(__file__).resolve().parents[2]
    if _overlaps(runtime_home, repo_root) or _overlaps(runtime_home, vault_root):
        raise ValueError("OPENJARVIS_HOME must be outside both repository and vault")
    configured_home = os.environ.get("OPENJARVIS_HOME", "")
    if (
        not configured_home
        or Path(configured_home).resolve(strict=True) != runtime_home
    ):
        raise ValueError("OPENJARVIS_HOME must identify the supplied runtime root")
    resolved_config = config_path.resolve(strict=True)
    if (
        not resolved_config.is_relative_to(runtime_home)
        or not resolved_config.is_file()
        or _is_reparse(resolved_config)
    ):
        raise ValueError("config must be a normal file under OPENJARVIS_HOME")
    if not shutdown_token:
        raise ValueError("an ephemeral shutdown token is required")

    load_config.cache_clear()
    config = load_config(resolved_config)
    _validate_loaded_config(config, home=runtime_home, vault=vault_root)
    for path in (
        runtime_home / "state",
        runtime_home / "restore" / "vault",
        runtime_home / "website-staging",
        runtime_home / "tool-artifacts",
        runtime_home / "assistant-workspace",
    ):
        path.mkdir(parents=True, exist_ok=True)

    bus = EventBus()
    trace_store: TraceStore | None = None
    tasks: CodexTaskRuntime | None = None
    vault_service: VaultMemoryService | None = None
    action_store: ActionStore | None = None
    try:
        trace_store = TraceStore(config.traces.db_path)
        tasks = build_codex_task_runtime(config.codex, bus=bus, trace_store=trace_store)
        vault_service = build_vault_memory_service(
            config,
            task_store=tasks.store,
            trace_store=trace_store,
            initial_index=initial_index,
        )
        if vault_service is None:
            raise RuntimeError("vault memory was not constructed")
        staging_root = (runtime_home / "website-staging").resolve(strict=True)
        assistant_workspace = (runtime_home / "assistant-workspace").resolve(
            strict=True
        )
        action_store = ActionStore(runtime_home / "state" / "tool-actions.sqlite3")
        policy_context = ToolPolicyContext(
            granted_capabilities=frozenset({"website:stage"}),
            execution_lane=ExecutionLane.MODEL,
            requested_risk=RiskLevel.REVERSIBLE_WORKSPACE,
            proposal_capability="website:stage",
            allowed_roots=(staging_root,),
        )
        catalog = ToolManifestCatalog(())
        action_service = ToolActionService(
            catalog=catalog,
            store=action_store,
            context_factory=lambda _proposal: policy_context,
            runtimes={},
            artifact_root=runtime_home / "tool-artifacts",
            task_service=tasks.service,
        )
        website_service = WebsiteStagingService(
            workspace_store=WebsiteWorkspaceStore(
                staging_root,
                protected_roots=(repo_root, vault_root),
            ),
            action_service=action_service,
            task_service=tasks.service,
        )
        phase7 = Phase7LearningRuntime.create(
            runtime_home / "state" / "phase7.sqlite3",
            tool_catalog=catalog,
        )
        app = create_app(
            FinalCodexHealthEngine(),
            FINAL_MODEL,
            bus=bus,
            engine_name="codex-final",
            config=config,
            trace_store=trace_store,
            task_store=tasks.store,
            task_service=tasks.service,
            approval_broker=tasks.approval_broker,
            codex_orchestrator=tasks.orchestrator,
            recovery_coordinator=tasks.recovery,
            vault_memory_service=vault_service,
            tool_action_service=action_service,
            website_staging_service=website_service,
            browser_session_service=None,
            phase7_learning_runtime=phase7,
            owns_task_runtime=True,
            api_key="",
            cors_origins=[
                "tauri://localhost",
                "http://tauri.localhost",
                "https://tauri.localhost",
            ],
        )

        @app.get("/v1/final/health")
        async def final_health() -> dict[str, Any]:
            return {
                "marker": FINAL_HEALTH_MARKER,
                "runtime": FINAL_RUNTIME_NAME,
                "status": "ready",
                "backend": "python_sdk",
                "model": FINAL_CODEX_MODEL,
                "reasoning_effort": FINAL_CODEX_EFFORT,
                "model_confirmation_required": True,
                "policy": {"approval": "deny_all", "sandbox": "read_only"},
                "components": {
                    "codex_tasks": True,
                    "vault_memory": True,
                    "phase7": True,
                    "tools": True,
                    "website_staging": True,
                    "analytics": False,
                    "browser": False,
                    "channels": False,
                    "mcp": False,
                },
                "pid": os.getpid(),
            }

        app.router.routes.insert(0, app.router.routes.pop())

        @app.post("/v1/final/shutdown", status_code=202)
        async def final_shutdown(request: Request) -> dict[str, str]:
            peer = request.client.host if request.client else ""
            supplied = request.headers.get("x-openjarvis-shutdown-token", "")
            if peer not in _LOOPBACK_HOSTS or not hmac.compare_digest(
                supplied, shutdown_token
            ):
                raise HTTPException(status_code=403, detail="shutdown denied")
            if shutdown_callback is None:
                raise HTTPException(
                    status_code=503, detail="shutdown callback unavailable"
                )
            shutdown_callback()
            return {"status": "stopping", "marker": FINAL_HEALTH_MARKER}

        app.router.routes.insert(0, app.router.routes.pop())

        @app.post("/v1/final/pilot-cleanup/{workspace_id}")
        async def final_pilot_cleanup(
            workspace_id: str, request: Request
        ) -> dict[str, str]:
            peer = request.client.host if request.client else ""
            supplied = request.headers.get("x-openjarvis-shutdown-token", "")
            if peer not in _LOOPBACK_HOSTS or not hmac.compare_digest(
                supplied, shutdown_token
            ):
                raise HTTPException(status_code=403, detail="cleanup denied")
            if workspace_id != _PILOT_WORKSPACE_ID:
                raise HTTPException(
                    status_code=422, detail="invalid workspace identifier"
                )
            website_service.cleanup(workspace_id)
            return {"status": "cleaned", "marker": FINAL_HEALTH_MARKER}

        app.router.routes.insert(0, app.router.routes.pop())
        original_lifespan = app.router.lifespan_context

        @asynccontextmanager
        async def final_lifespan(runtime_app):
            try:
                async with original_lifespan(runtime_app):
                    yield
            finally:
                try:
                    action_store.close()
                except Exception:
                    pass

        app.router.lifespan_context = final_lifespan
        app.state.final_runtime_name = FINAL_RUNTIME_NAME
        app.state.final_runtime_home = runtime_home
        app.state.final_staging_root = staging_root
        app.state.assistant_workspace = assistant_workspace
        return FinalRuntime(
            app=app,
            config=config,
            tasks=tasks,
            vault=vault_service,
            trace_store=trace_store,
            action_store=action_store,
            phase7=phase7,
            staging_root=staging_root,
            assistant_workspace=assistant_workspace,
        )
    except Exception:
        if action_store is not None:
            action_store.close()
        if vault_service is not None:
            vault_service.close()
        if tasks is not None:
            tasks.orchestrator.close_sync()
            tasks.store.close()
        if trace_store is not None:
            trace_store.close()
        raise


def _prepend_active_python_to_path() -> None:
    """Make child commands resolve to this runtime's Python environment."""

    # Codex App Server commands inherit this process environment.  Prepend the
    # active interpreter's bin directory so `python -m openjarvis...` resolves
    # to this exact environment without committing a machine-specific path.
    python_bin = str(Path(sys.executable).parent)
    inherited_path = os.environ.get("PATH", "")
    inherited_parts = [part for part in inherited_path.split(os.pathsep) if part]
    normalized_python_bin = os.path.normcase(python_bin)
    inherited_parts = [
        part
        for part in inherited_parts
        if os.path.normcase(part) != normalized_python_bin
    ]
    os.environ["PATH"] = os.pathsep.join([python_bin, *inherited_parts])


def _serve(args: argparse.Namespace) -> int:
    import uvicorn

    token = os.environ.get("OPENJARVIS_SHUTDOWN_TOKEN", "")
    runtime_home = Path(args.home).resolve(strict=True)
    _prepend_active_python_to_path()
    os.environ["OPENJARVIS_ASSISTANT_WORKSPACE"] = str(
        (runtime_home / "assistant-workspace").resolve(strict=True)
    )
    os.environ["OPENJARVIS_TOOL_ARTIFACT_ROOT"] = str(
        (runtime_home / "tool-artifacts" / "assistant").resolve(strict=False)
    )
    Path(os.environ["OPENJARVIS_TOOL_ARTIFACT_ROOT"]).mkdir(
        parents=True, exist_ok=True
    )
    server: uvicorn.Server | None = None

    def request_shutdown() -> None:
        if server is not None:
            server.should_exit = True

    runtime = build_final_runtime(
        home=Path(args.home),
        vault=Path(args.vault),
        config_path=Path(args.config),
        shutdown_token=token,
        shutdown_callback=request_shutdown,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            runtime.app,
            host=runtime.config.server.host,
            port=runtime.config.server.port,
            workers=1,
            access_log=False,
        )
    )
    server.run()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenJarvis Phase-8 final runtime")
    commands = parser.add_subparsers(dest="command", required=True)
    config_cmd = commands.add_parser("config", help="write a secret-free local config")
    serve_cmd = commands.add_parser("serve", help="serve the bounded final runtime")
    for command in (config_cmd, serve_cmd):
        command.add_argument("--home", required=True)
        command.add_argument("--vault", required=True)
        command.add_argument("--config", required=True)
    config_cmd.add_argument("--host", default="127.0.0.1")
    config_cmd.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.command == "config":
        write_final_config(
            home=Path(args.home),
            vault=Path(args.vault),
            config_path=Path(args.config),
            host=args.host,
            port=args.port,
        )
        return 0
    return _serve(args)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FINAL_HEALTH_MARKER",
    "FINAL_CODEX_EFFORT",
    "FINAL_CODEX_MODEL",
    "FINAL_MODEL",
    "FINAL_RUNTIME_NAME",
    "FinalCodexHealthEngine",
    "FinalRuntime",
    "build_final_runtime",
    "render_final_config",
    "write_final_config",
]
