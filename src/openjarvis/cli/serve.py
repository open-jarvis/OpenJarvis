"""``jarvis serve`` — OpenAI-compatible API server."""

from __future__ import annotations

import logging
import sys

import click
from rich.console import Console

from openjarvis.cli._banner import print_banner
from openjarvis.core.config import load_config
from openjarvis.core.credentials import inject_credentials
from openjarvis.core.events import EventBus
from openjarvis.core.paths import get_config_dir
from openjarvis.engine import (
    discover_engines,
    discover_models,
    get_engine,
)
from openjarvis.intelligence import (
    merge_discovered_models,
    register_builtin_models,
)

logger = logging.getLogger(__name__)

_DEFAULT_TOOLS = frozenset({"think", "calculator", "web_search"})


def _resolve_allowed_tools(config: object) -> tuple[set[str], bool]:
    """Return configured tool names and whether the selection was explicit.

    ``tools.enabled`` is the canonical setting used by ``SystemBuilder`` and
    the interactive CLI.  ``agent.tools`` remains as a backward-compatible
    fallback, followed by the server's default tool set when neither is set.
    """
    configured = config.tools.enabled or config.agent.tools
    if not configured:
        return set(_DEFAULT_TOOLS), False

    if isinstance(configured, list):
        allowed = {
            tool.strip()
            for tool in configured
            if isinstance(tool, str) and tool.strip()
        }
    else:
        allowed = {tool.strip() for tool in configured.split(",") if tool.strip()}
    return allowed, True


def _unique_model_ids(model_ids: list[str]) -> list[str]:
    """Return model ids in first-seen order without duplicates."""
    unique: list[str] = []
    seen: set[str] = set()
    for model_id in model_ids:
        if model_id and model_id not in seen:
            seen.add(model_id)
            unique.append(model_id)
    return unique


def _safe_list_models(engine: object) -> list[str]:
    try:
        list_models = getattr(engine, "list_models")
        return list(list_models())
    except Exception as exc:
        logger.debug("Failed to list models for selected server engine: %s", exc)
        return []


def _resolve_server_model(
    requested_model: str | None,
    *,
    config: object,
    engine_name: str,
    engine: object,
    all_models: dict[str, list[str]],
) -> str:
    """Pick a startup model that is present on the active server engine.

    CLI ``--model`` remains authoritative. For config-driven startup, prefer the
    configured server/default model only when the active engine can actually
    serve it; otherwise use ``intelligence.fallback_model`` or the first
    reachable model. This prevents MLX-preferred configs from hiding a healthy
    Ollama fallback behind an empty/incorrect model map.
    """
    if requested_model:
        return requested_model

    candidates = [
        getattr(config.server, "model", ""),
        getattr(config.intelligence, "default_model", ""),
        getattr(config.intelligence, "fallback_model", ""),
    ]
    available = _unique_model_ids(
        _safe_list_models(engine) + list(all_models.get(engine_name, []))
    )

    for candidate in candidates:
        if candidate and (not available or candidate in available):
            return candidate

    return available[0] if available else ""


@click.command()
@click.option("--host", default=None, help="Bind address (default: config).")
@click.option(
    "--port",
    default=None,
    type=int,
    help="Port number (default: config).",
)
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Default model.")
@click.option(
    "-a",
    "--agent",
    "agent_name",
    default=None,
    help="Agent for chat requests (simple, orchestrator, react, openhands).",
)
@click.pass_context
def serve(
    ctx: click.Context,
    host: str | None,
    port: int | None,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
) -> None:
    """Start the OpenAI-compatible API server."""
    print_banner(quiet=(ctx.obj or {}).get("quiet", False))
    console = Console(stderr=True)

    # Check for server dependencies
    try:
        import uvicorn  # noqa: F401
        from fastapi import FastAPI  # noqa: F401
    except ImportError:
        console.print(
            "[red bold]Server dependencies not installed.[/red bold]\n\n"
            "Install the server extra:\n"
            "  [cyan]uv sync --extra server[/cyan]"
        )
        sys.exit(1)

    # Tool credentials saved through the browser UI live in the OpenJarvis
    # credential store. Restore them before engines and tools are constructed
    # so availability checks and tool instances see the same environment.
    inject_credentials()

    config = load_config()

    # Resolve host/port from CLI args or config
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    # Set up engine
    register_builtin_models()
    bus = EventBus(record_history=False)

    # Telemetry, security guardrails and engine instrumentation are applied by
    # the single SystemBuilder composition below. Doing them here as well would
    # wrap the engine twice and put two TelemetryStores on the same bus.

    # Select with the model we'll actually serve so an engine that can't
    # serve it (e.g. the cloud fallback without the matching provider key) is
    # skipped rather than chosen and failing per-request later (see #532).
    selection_model = (
        model_name or config.server.model or config.intelligence.default_model or None
    )
    resolved = get_engine(config, engine_key, model=selection_model)
    if resolved is None:
        console.print(
            "[red bold]No inference engine available.[/red bold]\n\n"
            "Make sure an engine is running."
        )
        sys.exit(1)

    engine_name, engine = resolved

    # If cloud API keys are set, prepare a cloud engine. We build the
    # MultiEngine after local discovery so healthy local fallbacks such as
    # Ollama stay visible even when the configured preferred engine is MLX.
    import os

    cloud_engine = None
    _has_cloud = (
        os.environ.get("OPENAI_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )
    if _has_cloud and engine_name != "cloud":
        try:
            from openjarvis.engine.cloud import CloudEngine

            cloud_engine = CloudEngine()
            if cloud_engine.health():
                console.print("  Cloud:  [cyan]enabled[/cyan] (API keys detected)")
            else:
                console.print(
                    "  Cloud:  [yellow]keys set but packages missing[/yellow] "
                    "(run: uv sync --extra inference-cloud --extra inference-google)"
                )
        except Exception as exc:
            logger.debug("Cloud engine init failed: %s", exc)

    # Discover models
    all_engines = discover_engines(config)
    all_models = discover_models(all_engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    multi_entries = [(engine_name, engine)]
    for discovered_name, discovered_engine in all_engines:
        if discovered_name != engine_name:
            multi_entries.append((discovered_name, discovered_engine))
    if cloud_engine is not None:
        multi_entries.append(("cloud", cloud_engine))

    if len(multi_entries) > 1:
        from openjarvis.engine.multi import MultiEngine

        engine = MultiEngine(multi_entries)
        engine_name = "multi"
        all_models[engine_name] = engine.list_models()
        merge_discovered_models(engine_name, all_models[engine_name])

    # Resolve model
    configured_model = (
        model_name or config.server.model or config.intelligence.default_model
    )
    model_name = _resolve_server_model(
        model_name,
        config=config,
        engine_name=engine_name,
        engine=engine,
        all_models=all_models,
    )
    if configured_model and model_name and model_name != configured_model:
        console.print(
            "[yellow]Configured model "
            f"{configured_model!r} is not reachable; using {model_name!r}.[/yellow]"
        )
    if not model_name:
        console.print(
            "[red]No model available on any reachable engine.[/red]\n\n"
            "Start an inference backend and make sure it lists at least one model.\n"
            "For Ollama: [cyan]ollama serve[/cyan] and "
            "[cyan]ollama pull qwen3.5:9b[/cyan].\n"
            "For MLX: start the MLX OpenAI-compatible server on the configured host."
        )
        sys.exit(1)

    # One composition root. Everything downstream -- the API path, scheduled
    # agents, operators and the realtime voice session -- draws its engine,
    # tools, MCP clients, memory, sessions and policy from this one system.
    #
    # serve.py used to assemble JarvisSystem by hand to avoid a second
    # build() call (#263). The fix for a double build is to build once, not
    # to hand-assemble: the manual path silently dropped scheduler,
    # workflow_engine, skill_manager, speech_backend, audit_logger,
    # container_runner, agent_scheduler, channel_backend, gpu_monitor and
    # scheduler_store.
    from openjarvis.system import SystemBuilder

    agent_key = agent_name or config.server.agent
    builder = (
        SystemBuilder(config)
        .engine_instance(engine, key=engine_name or "openai-compat")
        .event_bus(bus)
        .model(model_name)
        .scheduler(True)
        .workflow(True)
        .sessions(True)
        .operators(True)
        .telemetry(config.telemetry.enabled)
        .traces(config.traces.enabled)
    )
    if agent_key:
        builder = builder.agent(agent_key)
    # The builder resolves no tools at all when nothing is configured; the
    # server has always served a small default set instead.
    _allowed, _tools_configured = _resolve_allowed_tools(config)
    if not _tools_configured:
        builder = builder.tools(sorted(_allowed))

    system = builder.build()

    # From here on the system owns them.
    engine = system.engine
    engine_name = system.engine_key
    model_name = system.model
    agent_key = system.agent_name

    # The server is the authoritative tick runner: on boot it holds no locks,
    # so it (and only it) sweeps any zombie running->idle left by a crash.
    if system.agent_manager is not None:
        try:
            system.agent_manager._clear_stale_running_state()
        except Exception as exc:
            logger.debug("Stale agent-state sweep failed: %s", exc)

    # The realtime voice path holds one agent across turns: it streams token
    # deltas, keeps a binding, and cancels an in-flight tool call on barge-in.
    # ask() constructs a fresh agent per call, which is the right lifecycle
    # for request/response work but cannot serve a session. Build the
    # long-lived one here, from what the system already owns.
    import openjarvis.agents  # noqa: F401  -- trigger agent registration
    from openjarvis.system.agent_construction import (
        construct_registered_agent,
        resolve_agent_system_prompt,
    )

    agent = None
    if system.agent_name:
        try:
            agent = construct_registered_agent(
                agent_name=system.agent_name,
                engine=system.engine,
                model=system.model,
                tools=system.tools,
                bus=system.bus,
                max_turns=system.config.agent.max_turns,
                capability_policy=system.capability_policy,
                memory_backend=system.memory_backend,
                session_store=system.session_store,
                system_prompt=resolve_agent_system_prompt(system.config.agent),
                parallel_tools=system.config.agent.parallel_tools,
                extra_kwargs={
                    "skill_few_shot_examples": system._skill_few_shot_examples,
                },
            )
            system.agent = agent
        except Exception as exc:
            logger.warning("Failed to construct the serving agent: %s", exc)
            console.print(f"[yellow]Agent {agent_key!r} failed to load: {exc}[/yellow]")

    # Provenance: which implementation backs each tool name. Names only --
    # never arguments or results.
    def _provenance(tool) -> str:
        mcp_meta = tool.spec.metadata.get("mcp")
        origin = type(tool).__name__
        if isinstance(mcp_meta, dict):
            origin += f"@{mcp_meta.get('server', '')}"
        return f"{tool.spec.name}[{origin}]"

    logger.warning(
        "Agent tools: %s",
        ", ".join(_provenance(t) for t in system.tools) or "none",
    )

    # The channel backend is the system's; serve only connects it and routes
    # inbound messages back through the same system.
    channel_bridge = system.channel_backend
    if channel_bridge is not None:
        try:
            channel_bridge.connect()
            system.wire_channel(channel_bridge)
            console.print(f"  Channel: [cyan]{config.channel.default_channel}[/cyan]")
        except Exception as exc:
            console.print(f"[yellow]Channel failed to start: {exc}[/yellow]")
            channel_bridge = None

    if system.speech_backend is not None:
        console.print(f"  Speech: [cyan]{system.speech_backend.backend_id}[/cyan]")
    if system.memory_backend is not None:
        console.print("  Memory:    [cyan]active[/cyan]")

    # Automatic long-term memory service (background fact extraction). Not part
    # of the system dataclass -- the API layer owns its lifecycle.
    memory_service = None
    try:
        from openjarvis.memory import build_memory_service

        memory_service = build_memory_service(
            config,
            system.engine,
            system.model,
            event_bus=bus,
        )
        if memory_service is not None:
            memory_service.start()
            console.print("  Memory svc: [cyan]active[/cyan]")
    except Exception as exc:
        logger.debug("Memory service init failed: %s", exc)
        memory_service = None

    # build() creates the scheduler; starting it and registering the cron and
    # interval agents is the server's job.
    if system.agent_scheduler is not None and system.agent_manager is not None:
        try:
            for ag in system.agent_manager.list_agents():
                sched_type = ag.get("config", {}).get("schedule_type", "manual")
                if sched_type in ("cron", "interval") and ag["status"] not in (
                    "archived",
                    "error",
                ):
                    system.agent_scheduler.register_agent(ag["id"])
            system.agent_scheduler.start()
            console.print("  Scheduler: [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Agent scheduler start failed: %s", exc)

    # Create app
    # --- Channel Gateway: API key, sessions, ChannelBridge ---
    import os as _os

    from openjarvis.server.app import create_app

    api_key = _os.environ.get("OPENJARVIS_API_KEY", "")
    if not api_key:
        try:
            import tomllib

            _cfg_path = str(get_config_dir() / "config.toml")
            with open(_cfg_path, "rb") as _f:
                _raw = tomllib.load(_f)
            api_key = _raw.get("server", {}).get("auth", {}).get("api_key", "")
        except (FileNotFoundError, ImportError):
            pass

    from openjarvis.server.auth_middleware import check_bind_safety

    check_bind_safety(bind_host, api_key=api_key)

    # Log credential status at startup
    from openjarvis.core.credentials import TOOL_CREDENTIALS, get_credential_status

    _cred_parts = []
    for _tool_name in sorted(TOOL_CREDENTIALS):
        _status = get_credential_status(_tool_name)
        _set = sum(1 for v in _status.values() if v)
        _total = len(_status)
        if _set > 0:
            _cred_parts.append(f"{_tool_name}: {_set}/{_total} keys")
    if _cred_parts:
        logger.info("Credentials loaded — %s", ", ".join(_cred_parts))

    webhook_config = {
        "twilio_auth_token": _os.environ.get("TWILIO_AUTH_TOKEN", ""),
        "bluebubbles_password": _os.environ.get("BLUEBUBBLES_PASSWORD", ""),
        "whatsapp_verify_token": _os.environ.get("WHATSAPP_VERIFY_TOKEN", ""),
        "whatsapp_app_secret": _os.environ.get("WHATSAPP_APP_SECRET", ""),
    }

    # Wrap existing channel in ChannelBridge orchestrator
    if channel_bridge is not None:
        try:
            from openjarvis.server.channel_bridge import (
                ChannelBridge,
            )
            from openjarvis.server.session_store import (
                SessionStore,
            )

            session_store = SessionStore()
            channels = {channel_bridge.channel_id: channel_bridge}
            channel_bridge = ChannelBridge(
                channels=channels,
                session_store=session_store,
                bus=bus,
                system=None,
                agent_manager=system.agent_manager,
            )
        except Exception as exc:
            logger.debug("ChannelBridge init skipped: %s", exc)

    cors_origins = system.config.server.cors_origins

    app = create_app(
        engine=system.engine,
        model=system.model,
        agent=agent,
        bus=system.bus,
        engine_name=system.engine_key,
        agent_name=system.agent_name,
        channel_bridge=channel_bridge,
        config=system.config,
        memory_backend=system.memory_backend,
        memory_service=memory_service,
        speech_backend=system.speech_backend,
        agent_manager=system.agent_manager,
        agent_scheduler=system.agent_scheduler,
        mcp_tools=system.mcp_tools,
        mcp_clients=system._mcp_clients,
        api_key=api_key,
        webhook_config=webhook_config,
        cors_origins=cors_origins,
    )
    app.state.system = system

    console.print(
        f"[green]Starting OpenJarvis API server[/green]\n"
        f"  Engine: [cyan]{engine_name}[/cyan]\n"
        f"  Model:  [cyan]{model_name}[/cyan]\n"
        f"  Agent:  [cyan]{agent_key or 'none'}[/cyan]\n"
        f"  URL:    [cyan]http://{bind_host}:{bind_port}[/cyan]"
    )

    # Warn about wildcard CORS on non-loopback
    import ipaddress as _ipa

    try:
        _is_loop = _ipa.ip_address(bind_host).is_loopback
    except ValueError:
        _is_loop = bind_host in ("localhost", "")

    if not _is_loop and "*" in cors_origins:
        console.print(
            "[yellow bold]WARNING:[/yellow bold] Wildcard CORS with credentials "
            "enabled on non-loopback interface. This allows any website to make "
            "authenticated requests to your instance."
        )

    # serve owns the system it built. The app's own shutdown hook only closes
    # what it was told it owns; everything else the builder opened -- engine,
    # session/telemetry/trace stores, scheduler store, memory backend -- is
    # released here. close() is tolerant of a resource the app already closed.
    try:
        uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
    finally:
        system.close()
