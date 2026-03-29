"""``jarvis serve`` — OpenAI-compatible API server."""

from __future__ import annotations

import logging
import sys

import click
from rich.console import Console

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
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
    help="Agent for non-streaming requests (simple, orchestrator, react, openhands).",
)
def serve(
    host: str | None,
    port: int | None,
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
) -> None:
    """Start the OpenAI-compatible API server."""
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

    config = load_config()

    # Resolve host/port from CLI args or config
    bind_host = host or config.server.host
    bind_port = port or config.server.port

    # Set up engine
    register_builtin_models()
    bus = EventBus(record_history=False)

    # Set up telemetry
    telem_store = None
    if config.telemetry.enabled:
        try:
            from pathlib import Path

            from openjarvis.telemetry.store import TelemetryStore

            db_path = Path(config.telemetry.db_path).expanduser()
            db_path.parent.mkdir(parents=True, exist_ok=True)
            telem_store = TelemetryStore(str(db_path))
            telem_store.subscribe_to_bus(bus)
        except Exception as exc:
            logger.debug("Telemetry store init failed: %s", exc)

    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print(
            "[red bold]No inference engine available.[/red bold]\n\n"
            "Make sure an engine is running."
        )
        sys.exit(1)

    engine_name, engine = resolved

    # Apply security guardrails
    from openjarvis.security import setup_security

    sec = setup_security(config, engine, bus)
    engine = sec.engine

    # If cloud API keys are set, wrap with MultiEngine so both local
    # and cloud models appear in the model list and can be used.
    import os

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
            from openjarvis.engine.multi import MultiEngine

            cloud = CloudEngine()
            if cloud.health():
                engine = MultiEngine([(engine_name, engine), ("cloud", cloud)])
                engine_name = "multi"
                console.print("  Cloud:  [cyan]enabled[/cyan] (API keys detected)")
        except Exception as exc:
            logger.debug("Cloud engine init failed: %s", exc)

    # Wrap engine with InstrumentedEngine for telemetry recording
    try:
        from openjarvis.telemetry.instrumented_engine import InstrumentedEngine

        energy_mon = None
        try:
            from openjarvis.telemetry.energy_monitor import create_energy_monitor

            energy_mon = create_energy_monitor()
            if energy_mon is not None:
                console.print(
                    f"  Energy: [cyan]{energy_mon.vendor().value}[/cyan] "
                    f"({energy_mon.energy_method()})"
                )
        except Exception as exc:
            logger.debug("Energy monitor creation failed: %s", exc)

        engine = InstrumentedEngine(engine, bus, energy_monitor=energy_mon)
    except Exception as exc:
        logger.debug("Engine instrumentation failed: %s", exc)

    # Discover models
    all_engines = discover_engines(config)
    all_models = discover_models(all_engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    # Resolve model
    if model_name is None:
        model_name = config.server.model or config.intelligence.default_model
    if not model_name:
        engine_models = all_models.get(engine_name, [])
        if engine_models:
            model_name = engine_models[0]
        else:
            console.print("[red]No model available on engine.[/red]")
            sys.exit(1)

    # Resolve agent
    agent = None
    agent_key = agent_name or config.server.agent
    if agent_key:
        try:
            import openjarvis.agents  # noqa: F401
            from openjarvis.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls = AgentRegistry.get(agent_key)
                agent_kwargs = {"bus": bus}
                if sec.capability_policy is not None:
                    agent_kwargs["capability_policy"] = sec.capability_policy

                # Load tools for agents that support them
                if getattr(agent_cls, "accepts_tools", False):
                    import openjarvis.tools  # noqa: F401  # trigger registration
                    from openjarvis.core.registry import ToolRegistry
                    from openjarvis.tools._stubs import BaseTool

                    _DEFAULT_TOOLS = {"think", "calculator", "web_search"}
                    configured = config.agent.tools
                    if configured:
                        if isinstance(configured, list):
                            allowed = {
                                t.strip()
                                for t in configured
                                if isinstance(t, str) and t.strip()
                            }
                        else:
                            allowed = {
                                t.strip() for t in configured.split(",") if t.strip()
                            }
                    else:
                        allowed = _DEFAULT_TOOLS

                    tools = []
                    for name in ToolRegistry.keys():
                        if name not in allowed:
                            continue
                        tool_cls = ToolRegistry.get(name)
                        if isinstance(tool_cls, type) and issubclass(
                            tool_cls, BaseTool
                        ):
                            tools.append(tool_cls())
                        elif isinstance(tool_cls, BaseTool):
                            tools.append(tool_cls)
                    if tools:
                        agent_kwargs["tools"] = tools

                if getattr(agent_cls, "accepts_tools", False):
                    agent_kwargs["max_turns"] = config.agent.max_turns

                agent = agent_cls(engine, model_name, **agent_kwargs)
        except Exception as exc:
            import traceback

            console.print(f"[yellow]Agent '{agent_key}' failed to load: {exc}[/yellow]")
            traceback.print_exc()

    # Set up channel backend if enabled
    channel_bridge = None
    if config.channel.enabled and config.channel.default_channel:
        try:
            from openjarvis.system import SystemBuilder

            # Reuse _resolve_channel logic from SystemBuilder
            sb = SystemBuilder(config)
            sb._bus = bus
            channel_bridge = sb._resolve_channel(config, bus)
            if channel_bridge is not None:
                channel_bridge.connect()
                console.print(
                    f"  Channel: [cyan]{config.channel.default_channel}[/cyan]"
                )
        except Exception as exc:
            console.print(f"[yellow]Channel failed to start: {exc}[/yellow]")
            channel_bridge = None

    # Wire channel messages → agent / engine (per-chat session isolation)
    if channel_bridge is not None:
        from openjarvis.system import JarvisSystem

        channel_agent = config.channel.default_agent or agent_key or "simple"

        _channel_tools: list = []
        if channel_agent:
            try:
                import openjarvis.agents
                from openjarvis.core.registry import AgentRegistry

                if AgentRegistry.contains(channel_agent):
                    _ch_cls = AgentRegistry.get(channel_agent)
                    if getattr(_ch_cls, "accepts_tools", False):
                        import openjarvis.tools
                        from openjarvis.core.registry import ToolRegistry
                        from openjarvis.tools._stubs import BaseTool

                        _DEFAULT_TOOLS = {"think", "calculator", "web_search"}
                        configured = config.agent.tools
                        if configured:
                            if isinstance(configured, list):
                                _allowed = {
                                    t.strip()
                                    for t in configured
                                    if isinstance(t, str) and t.strip()
                                }
                            else:
                                _allowed = {
                                    t.strip()
                                    for t in configured.split(",")
                                    if t.strip()
                                }
                        else:
                            _allowed = _DEFAULT_TOOLS

                        for _tname in ToolRegistry.keys():
                            if _tname not in _allowed:
                                continue
                            _tcls = ToolRegistry.get(_tname)
                            if isinstance(_tcls, type) and issubclass(_tcls, BaseTool):
                                _channel_tools.append(_tcls())
                            elif isinstance(_tcls, BaseTool):
                                _channel_tools.append(_tcls)
            except Exception as exc:
                logger.warning("Channel tools failed to load: %s", exc)

        _wire_system = JarvisSystem(
            config=config,
            bus=bus,
            engine=engine,
            engine_key=engine_name,
            model=model_name,
            agent_name=channel_agent,
            tools=_channel_tools,
        )
        _wire_system.wire_channel(channel_bridge)

    # Set up speech backend
    speech_backend = None
    try:
        from openjarvis.speech._discovery import get_speech_backend

        speech_backend = get_speech_backend(config)
        if speech_backend:
            console.print(f"  Speech: [cyan]{speech_backend.backend_id}[/cyan]")
    except Exception as exc:
        logger.debug("Speech backend discovery failed: %s", exc)

    # Create app
    from openjarvis.server.app import create_app

    # Set up agent manager
    agent_manager = None
    if config.agent_manager.enabled:
        try:
            from pathlib import Path

            from openjarvis.agents.manager import AgentManager

            am_db = config.agent_manager.db_path or str(
                Path("~/.openjarvis/agents.db").expanduser()
            )
            agent_manager = AgentManager(db_path=am_db)
        except Exception as exc:
            logger.debug("Agent manager init failed: %s", exc)

    # Set up agent scheduler for cron/interval agents
    agent_scheduler = None
    if agent_manager is not None:
        try:
            from openjarvis.agents.executor import AgentExecutor
            from openjarvis.agents.scheduler import AgentScheduler

            executor = AgentExecutor(manager=agent_manager, event_bus=bus)
            from openjarvis.system import SystemBuilder

            system = SystemBuilder(config).build()
            executor.set_system(system)

            agent_scheduler = AgentScheduler(
                manager=agent_manager,
                executor=executor,
                event_bus=bus,
            )
            for ag in agent_manager.list_agents():
                sched_type = ag.get("config", {}).get("schedule_type", "manual")
                if sched_type in ("cron", "interval") and ag["status"] not in (
                    "archived",
                    "error",
                ):
                    agent_scheduler.register_agent(ag["id"])
            agent_scheduler.start()
            console.print("  Scheduler: [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Agent scheduler init failed: %s", exc)

    # Set up memory backend for context injection
    memory_backend = None
    if config.agent.context_from_memory:
        try:
            import openjarvis.tools.storage  # noqa: F401
            from openjarvis.core.registry import MemoryRegistry

            mem_key = config.memory.default_backend
            if MemoryRegistry.contains(mem_key):
                memory_backend = MemoryRegistry.create(
                    mem_key,
                    db_path=config.memory.db_path,
                )
                console.print("  Memory:    [cyan]active[/cyan]")
        except Exception as exc:
            logger.debug("Memory backend init failed: %s", exc)

    # --- Channel Gateway: API key, sessions, ChannelBridge ---
    import os as _os

    api_key = _os.environ.get("OPENJARVIS_API_KEY", "")
    if not api_key:
        try:
            import tomllib

            _cfg_path = str(
                __import__("pathlib").Path.home() / ".openjarvis" / "config.toml"
            )
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
                agent_manager=agent_manager,
            )
        except Exception as exc:
            logger.debug("ChannelBridge init skipped: %s", exc)

    app = create_app(
        engine,
        model_name,
        agent=agent,
        bus=bus,
        engine_name=engine_name,
        agent_name=agent_key or "",
        channel_bridge=channel_bridge,
        config=config,
        memory_backend=memory_backend,
        speech_backend=speech_backend,
        agent_manager=agent_manager,
        agent_scheduler=agent_scheduler,
        api_key=api_key,
        webhook_config=webhook_config,
        cors_origins=config.server.cors_origins,
    )

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

    if not _is_loop and "*" in config.server.cors_origins:
        console.print(
            "[yellow bold]WARNING:[/yellow bold] Wildcard CORS with credentials "
            "enabled on non-loopback interface. This allows any website to make "
            "authenticated requests to your instance."
        )

    import uvicorn

    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info")
