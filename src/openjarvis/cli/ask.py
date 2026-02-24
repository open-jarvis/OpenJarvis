"""``jarvis ask`` — send a query to the assistant."""

from __future__ import annotations

import json as json_mod
import sys

import click
from rich.console import Console

from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.core.types import Message, Role
from openjarvis.engine import (
    EngineConnectionError,
    discover_engines,
    discover_models,
    get_engine,
)
from openjarvis.intelligence import (
    merge_discovered_models,
    register_builtin_models,
)
from openjarvis.telemetry.store import TelemetryStore
from openjarvis.telemetry.wrapper import instrumented_generate


def _get_memory_backend(config):
    """Try to instantiate the memory backend, return None on failure."""
    try:
        import openjarvis.memory  # noqa: F401
        from openjarvis.core.registry import MemoryRegistry

        key = config.memory.default_backend
        if not MemoryRegistry.contains(key):
            return None

        if key == "sqlite":
            backend = MemoryRegistry.create(
                key, db_path=config.memory.db_path,
            )
        else:
            backend = MemoryRegistry.create(key)

        # Check if there's actually anything indexed
        if hasattr(backend, "count") and backend.count() == 0:
            if hasattr(backend, "close"):
                backend.close()
            return None

        return backend
    except Exception:
        return None


def _build_tools(tool_names: list[str], config, engine, model_name: str):
    """Instantiate tool objects from names."""
    from openjarvis.core.registry import ToolRegistry

    tools = []
    for name in tool_names:
        name = name.strip()
        if not name:
            continue
        if not ToolRegistry.contains(name):
            continue
        tool_cls = ToolRegistry.get(name)
        # Instantiate with appropriate arguments
        if name == "retrieval":
            backend = _get_memory_backend(config)
            tools.append(tool_cls(backend=backend))
        elif name == "llm":
            tools.append(tool_cls(engine=engine, model=model_name))
        elif name == "file_read":
            tools.append(tool_cls())
        else:
            tools.append(tool_cls())
    return tools


def _run_agent(
    agent_name: str,
    query_text: str,
    engine,
    model_name: str,
    tool_names: list[str],
    config,
    bus: EventBus,
    temperature: float,
    max_tokens: int,
):
    """Instantiate and run an agent, returning the AgentResult."""
    # Import agents to trigger registration
    import openjarvis.agents  # noqa: F401
    from openjarvis.agents._stubs import AgentContext
    from openjarvis.core.registry import AgentRegistry

    if not AgentRegistry.contains(agent_name):
        raise click.ClickException(
            f"Unknown agent: {agent_name}. "
            f"Available: {', '.join(AgentRegistry.keys())}"
        )

    agent_cls = AgentRegistry.get(agent_name)

    # Build tools
    tools = []
    if tool_names:
        # Trigger tool registration
        import openjarvis.tools  # noqa: F401
        tools = _build_tools(tool_names, config, engine, model_name)

    # Build agent with appropriate kwargs
    agent_kwargs = {
        "bus": bus,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if getattr(agent_cls, "accepts_tools", False):
        agent_kwargs["tools"] = tools
        agent_kwargs["max_turns"] = config.agent.max_turns

    agent = agent_cls(engine, model_name, **agent_kwargs)
    ctx = AgentContext()

    # Inject memory context into conversation if available
    if config.agent.context_from_memory:
        try:
            from openjarvis.memory.context import ContextConfig, inject_context

            backend = _get_memory_backend(config)
            if backend is not None:
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=config.memory.context_max_tokens,
                )
                context_messages = inject_context(
                    query_text, [], backend, config=ctx_cfg,
                )
                for msg in context_messages:
                    ctx.conversation.add(msg)
        except Exception:
            pass

    return agent.run(query_text, context=ctx)


@click.command()
@click.argument("query", nargs=-1, required=True)
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option(
    "-t", "--temperature", default=None, type=float,
    help="Sampling temperature (default: from config).",
)
@click.option(
    "--max-tokens", default=None, type=int,
    help="Max tokens to generate (default: from config).",
)
@click.option("--json", "output_json", is_flag=True, help="Output raw JSON result.")
@click.option("--no-stream", is_flag=True, help="Disable streaming (sync mode).")
@click.option(
    "--no-context", is_flag=True,
    help="Disable memory context injection.",
)
@click.option(
    "-a", "--agent", "agent_name", default=None,
    help="Agent to use (simple, orchestrator).",
)
@click.option(
    "--tools", "tool_names", default=None,
    help="Comma-separated tool names to enable (e.g. calculator,think).",
)
def ask(
    query: tuple[str, ...],
    model_name: str | None,
    engine_key: str | None,
    temperature: float,
    max_tokens: int,
    output_json: bool,
    no_stream: bool,
    no_context: bool,
    agent_name: str | None,
    tool_names: str | None,
) -> None:
    """Ask Jarvis a question."""
    console = Console(stderr=True)
    query_text = " ".join(query)

    # Load config
    config = load_config()

    # Fall back to config values for generation params
    if temperature is None:
        temperature = config.intelligence.temperature
    if max_tokens is None:
        max_tokens = config.intelligence.max_tokens

    # Set up telemetry
    bus = EventBus(record_history=True)
    telem_store: TelemetryStore | None = None
    if config.telemetry.enabled:
        try:
            telem_store = TelemetryStore(config.telemetry.db_path)
            telem_store.subscribe_to_bus(bus)
        except Exception:
            pass  # telemetry is best-effort

    # Discover engines
    register_builtin_models()

    effective_engine_key = engine_key or config.intelligence.preferred_engine or None
    resolved = get_engine(config, effective_engine_key)
    if resolved is None:
        console.print(
            "[red bold]No inference engine available.[/red bold]\n\n"
            "Make sure an engine is running:\n"
            "  [cyan]ollama serve[/cyan]          — start Ollama\n"
            "  [cyan]vllm serve <model>[/cyan]    — start vLLM\n"
            "  [cyan]llama-server -m <gguf>[/cyan] — start llama.cpp\n\n"
            "Or set OPENAI_API_KEY / ANTHROPIC_API_KEY for cloud inference."
        )
        sys.exit(1)

    engine_name, engine = resolved

    # Discover models and merge into registry
    all_engines = discover_engines(config)
    all_models = discover_models(all_engines)
    for ek, model_ids in all_models.items():
        merge_discovered_models(ek, model_ids)

    # Resolve model via config fallback chain
    if model_name is None:
        model_name = config.intelligence.default_model
    if not model_name:
        # Try first available from engine
        engine_models = all_models.get(engine_name, [])
        if engine_models:
            model_name = engine_models[0]
    if not model_name:
        model_name = config.intelligence.fallback_model
    if not model_name:
        console.print("[red]No model available on engine.[/red]")
        sys.exit(1)

    # Agent mode
    if agent_name is not None:
        parsed_tools = tool_names.split(",") if tool_names else []
        try:
            result = _run_agent(
                agent_name, query_text, engine, model_name,
                parsed_tools, config, bus, temperature, max_tokens,
            )
        except EngineConnectionError as exc:
            console.print(f"[red]Engine error:[/red] {exc}")
            sys.exit(1)

        if output_json:
            click.echo(json_mod.dumps({
                "content": result.content,
                "turns": result.turns,
                "tool_results": [
                    {
                        "tool_name": tr.tool_name,
                        "content": tr.content,
                        "success": tr.success,
                    }
                    for tr in result.tool_results
                ],
            }, indent=2))
        else:
            click.echo(result.content)

        if telem_store is not None:
            try:
                telem_store.close()
            except Exception:
                pass
        return

    # Direct-to-engine mode (no agent)
    messages = [Message(role=Role.USER, content=query_text)]

    # Memory-augmented context injection
    if not no_context and config.agent.context_from_memory:
        try:
            from openjarvis.memory.context import (
                ContextConfig,
                inject_context,
            )
            backend = _get_memory_backend(config)
            if backend is not None:
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=(
                        config.memory.context_max_tokens
                    ),
                )
                messages = inject_context(
                    query_text, messages, backend,
                    config=ctx_cfg,
                )
        except Exception:
            pass  # context injection is best-effort

    # Generate
    try:
        result = instrumented_generate(
            engine,
            messages,
            model=model_name,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except EngineConnectionError as exc:
        console.print(f"[red]Engine error:[/red] {exc}")
        sys.exit(1)

    # Output
    if output_json:
        click.echo(json_mod.dumps(result, indent=2))
    else:
        click.echo(result.get("content", ""))

    # Cleanup
    if telem_store is not None:
        try:
            telem_store.close()
        except Exception:
            pass
