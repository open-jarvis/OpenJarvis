"""``jarvis ask`` — send a query to the assistant."""

from __future__ import annotations

import json as json_mod
import logging
import sys
import time

import click
from rich.console import Console
from rich.table import Table

from openjarvis.cli._tool_names import resolve_tool_names
from openjarvis.cli.hints import hint_no_engine
from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus, EventType
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
from openjarvis.telemetry.instrumented_engine import InstrumentedEngine
from openjarvis.telemetry.store import TelemetryStore

logger = logging.getLogger(__name__)


def _get_memory_backend(config):
    """Try to instantiate the memory backend, return None on failure."""
    try:
        import openjarvis.tools.storage  # noqa: F401
        from openjarvis.core.registry import MemoryRegistry

        key = config.memory.default_backend
        if not MemoryRegistry.contains(key):
            return None

        if key == "sqlite":
            backend = MemoryRegistry.create(
                key,
                db_path=config.memory.db_path,
            )
        else:
            backend = MemoryRegistry.create(key)

        # Check if there's actually anything indexed
        if hasattr(backend, "count") and backend.count() == 0:
            if hasattr(backend, "close"):
                backend.close()
            return None

        return backend
    except Exception as exc:
        logger.debug("Memory backend unavailable (optional): %s", exc)
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
    capability_policy=None,
):
    """Instantiate and run an agent, returning the AgentResult."""
    # Import agents to trigger registration
    import openjarvis.agents  # noqa: F401
    from openjarvis.agents._stubs import AgentContext
    from openjarvis.core.registry import AgentRegistry

    if not AgentRegistry.contains(agent_name):
        raise click.ClickException(
            f"Unknown agent: {agent_name}. Available: {', '.join(AgentRegistry.keys())}"
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
        agent_kwargs["interactive"] = True
        agent_kwargs["confirm_callback"] = lambda prompt: True
    if capability_policy is not None:
        agent_kwargs["capability_policy"] = capability_policy

    agent = agent_cls(engine, model_name, **agent_kwargs)
    ctx = AgentContext()

    # Inject memory context into conversation if available
    if config.agent.context_from_memory:
        try:
            from openjarvis.tools.storage.context import ContextConfig, inject_context

            backend = _get_memory_backend(config)
            if backend is not None:
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=config.memory.context_max_tokens,
                )
                context_messages = inject_context(
                    query_text,
                    [],
                    backend,
                    config=ctx_cfg,
                )
                for msg in context_messages:
                    ctx.conversation.add(msg)
        except Exception as exc:
            logger.warning("Failed to inject memory context for agent: %s", exc)

    return agent.run(query_text, context=ctx)


def _print_profile(
    bus: EventBus,
    wall_seconds: float,
    engine_name: str,
    model_name: str,
    console: Console,
    complexity_result=None,
) -> None:
    """Print an inference telemetry profile table from EventBus history."""
    # Collect all INFERENCE_END events (agents may fire multiple)
    inf_events = [e for e in bus.history if e.event_type == EventType.INFERENCE_END]
    if not inf_events:
        console.print("[dim]No inference telemetry recorded.[/dim]")
        return

    total_calls = len(inf_events)

    # Aggregate across all inference calls
    total_latency = sum(e.data.get("latency", 0.0) for e in inf_events)
    total_tokens = sum(
        e.data.get("usage", {}).get("completion_tokens", 0)
        or e.data.get("completion_tokens", 0)
        for e in inf_events
    )
    total_prompt = sum(
        e.data.get("usage", {}).get("prompt_tokens", 0) for e in inf_events
    )
    total_energy = sum(e.data.get("energy_joules", 0.0) for e in inf_events)
    avg_power = 0.0
    power_vals = [
        e.data.get("power_watts", 0.0)
        for e in inf_events
        if e.data.get("power_watts", 0.0) > 0
    ]
    if power_vals:
        avg_power = sum(power_vals) / len(power_vals)

    throughput = total_tokens / total_latency if total_latency > 0 else 0.0
    energy_per_tok = total_energy / total_tokens if total_tokens > 0 else 0.0
    tpw = throughput / avg_power if avg_power > 0 else 0.0
    tok_per_j = total_tokens / total_energy if total_energy > 0 else 0.0

    last = inf_events[-1].data
    ttft = last.get("ttft", 0.0)
    prefill_lat = last.get("prefill_latency_seconds", 0.0)
    decode_lat = last.get("decode_latency_seconds", 0.0)
    prefill_e = sum(e.data.get("prefill_energy_joules", 0.0) for e in inf_events)
    decode_e = sum(e.data.get("decode_energy_joules", 0.0) for e in inf_events)
    gpu_util = last.get("gpu_utilization_pct", 0.0)
    gpu_mem = last.get("gpu_memory_used_gb", 0.0)
    gpu_temp = last.get("gpu_temperature_c", 0.0)
    mean_itl = last.get("mean_itl_ms", 0.0)
    e_method = last.get("energy_method", "")
    e_vendor = last.get("energy_vendor", "")

    # Build the profile table
    table = Table(
        title=f"Inference Profile  ({engine_name} / {model_name})",
        show_header=True,
        header_style="bold bright_white",
        border_style="bright_blue",
        title_style="bold cyan",
    )
    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column("Value", justify="right", style="green")

    def _row(label: str, val: str) -> None:
        table.add_row(label, val)

    if complexity_result is not None:
        _row("Complexity score", f"{complexity_result.score:.3f}")
        _row("Complexity tier", complexity_result.tier)
        _row("Suggested max tokens", str(complexity_result.suggested_max_tokens))
        _row("", "")  # separator

    _row("Wall time", f"{wall_seconds:.3f} s")
    _row("Inference calls", str(total_calls))
    _row("Total latency", f"{total_latency:.3f} s")
    if ttft > 0:
        _row("TTFT", f"{ttft * 1000:.1f} ms")
    if prefill_lat > 0:
        _row("Prefill latency", f"{prefill_lat * 1000:.1f} ms")
    if decode_lat > 0:
        _row("Decode latency", f"{decode_lat:.3f} s")
    if mean_itl > 0:
        _row("Mean ITL", f"{mean_itl:.2f} ms")
    _row("Prompt tokens", str(total_prompt))
    _row("Completion tokens", str(total_tokens))
    _row("Throughput", f"{throughput:.1f} tok/s")

    if total_energy > 0:
        _row("", "")  # separator
        _row("Energy", f"{total_energy:.4f} J")
        if prefill_e > 0:
            _row("  Prefill energy", f"{prefill_e:.4f} J")
        if decode_e > 0:
            _row("  Decode energy", f"{decode_e:.4f} J")
        _row("Energy / output token", f"{energy_per_tok:.6f} J")
        _row("Tokens / joule", f"{tok_per_j:.1f}")
        _row("Throughput / watt", f"{tpw:.2f} tok/s/W")
        if avg_power > 0:
            _row("Avg power draw", f"{avg_power:.1f} W")
        if e_vendor:
            _row("Energy vendor", e_vendor)
        if e_method:
            _row("Energy method", e_method)

    if gpu_util > 0 or gpu_mem > 0 or gpu_temp > 0:
        _row("", "")  # separator
        if gpu_util > 0:
            _row("GPU utilization", f"{gpu_util:.1f} %")
        if gpu_mem > 0:
            _row("GPU memory used", f"{gpu_mem:.2f} GB")
        if gpu_temp > 0:
            _row("GPU temperature", f"{gpu_temp:.0f} °C")

    console.print()
    console.print(table)


@click.command()
@click.argument("query", nargs=-1, required=True)
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option(
    "-t",
    "--temperature",
    default=None,
    type=float,
    help="Sampling temperature (default: from config).",
)
@click.option(
    "--max-tokens",
    default=None,
    type=int,
    help="Max tokens to generate (default: from config).",
)
@click.option("--json", "output_json", is_flag=True, help="Output raw JSON result.")
@click.option("--no-stream", is_flag=True, help="Disable streaming (sync mode).")
@click.option(
    "--no-context",
    is_flag=True,
    help="Disable memory context injection.",
)
@click.option(
    "-a",
    "--agent",
    "agent_name",
    default=None,
    help="Agent to use (simple, orchestrator).",
)
@click.option(
    "--tools",
    "tool_names",
    default=None,
    help="Comma-separated tool names to enable (e.g. calculator,think).",
)
@click.option(
    "--profile",
    "enable_profile",
    is_flag=True,
    help="Print inference telemetry profile (latency, tokens, energy, IPW).",
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
    enable_profile: bool,
) -> None:
    """Ask Jarvis a question."""
    console = Console(stderr=True)
    query_text = " ".join(query)

    wall_start = time.monotonic() if enable_profile else None

    # Load config
    config = load_config()

    # Track whether the user explicitly set --max-tokens
    user_set_max_tokens = max_tokens is not None

    # Fall back to config values for generation params
    if temperature is None:
        temperature = config.intelligence.temperature
    if max_tokens is None:
        max_tokens = config.intelligence.max_tokens

    # Run complexity analysis on the query
    from openjarvis.learning.routing.complexity import (
        ComplexityResult,
        adjust_tokens_for_model,
        score_complexity,
    )

    complexity_result: ComplexityResult = score_complexity(query_text)
    logger.debug(
        "Complexity analysis: score=%.3f tier=%s suggested_max_tokens=%d",
        complexity_result.score,
        complexity_result.tier,
        complexity_result.suggested_max_tokens,
    )

    # Set up telemetry
    bus = EventBus(record_history=True)
    telem_store: TelemetryStore | None = None
    if config.telemetry.enabled:
        try:
            telem_store = TelemetryStore(config.telemetry.db_path)
            telem_store.subscribe_to_bus(bus)
        except Exception as exc:
            logger.debug("Failed to initialize telemetry store: %s", exc)

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
            "Or set OPENAI_API_KEY / ANTHROPIC_API_KEY for cloud inference.\n\n"
            "[dim]To use a remote engine:[/dim]\n"
            "  [cyan]jarvis config set engine.ollama.host http://<remote-ip>:11434[/cyan]\n"
            "  [dim]or[/dim] [cyan]export OLLAMA_HOST=http://<remote-ip>:11434[/cyan]"
        )
        sys.exit(1)

    engine_name, engine = resolved

    # Apply security guardrails
    from openjarvis.security import setup_security

    sec = setup_security(config, engine, bus)
    engine = sec.engine

    # Wrap engine with InstrumentedEngine for telemetry (energy + GPU metrics)
    energy_monitor = None
    want_energy = config.telemetry.gpu_metrics or enable_profile
    if want_energy:
        try:
            from openjarvis.telemetry.energy_monitor import create_energy_monitor

            energy_monitor = create_energy_monitor(
                prefer_vendor=config.telemetry.energy_vendor or None,
            )
        except Exception as exc:
            logger.debug("Failed to create energy monitor: %s", exc)
    engine = InstrumentedEngine(engine, bus, energy_monitor=energy_monitor)

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

    # Apply complexity-suggested token budget when user didn't override.
    # Use at least the config default so we never reduce tokens below what
    # the user would have gotten without the analyzer.
    if not user_set_max_tokens:
        suggested = adjust_tokens_for_model(
            complexity_result.suggested_max_tokens,
            model_name,
        )
        max_tokens = max(suggested, config.intelligence.max_tokens)
        logger.debug(
            "Using complexity-suggested max_tokens=%d (model=%s)",
            max_tokens,
            model_name,
        )

    # Agent mode
    if agent_name is not None:
        parsed_tools = resolve_tool_names(
            tool_names,
            getattr(config.tools, "enabled", None),
            getattr(config.agent, "tools", None),
        )
        try:
            result = _run_agent(
                agent_name,
                query_text,
                engine,
                model_name,
                parsed_tools,
                config,
                bus,
                temperature,
                max_tokens,
                capability_policy=sec.capability_policy,
            )
        except EngineConnectionError as exc:
            console.print(f"[red]Engine error:[/red] {exc}")
            console.print(hint_no_engine())
            sys.exit(1)

        if output_json:
            click.echo(
                json_mod.dumps(
                    {
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
                    },
                    indent=2,
                )
            )
        else:
            click.echo(result.content)

        if enable_profile:
            _print_profile(
                bus,
                time.monotonic() - wall_start,
                engine_name,
                model_name,
                console,
                complexity_result=complexity_result,
            )

        if telem_store is not None:
            try:
                telem_store.close()
            except Exception as exc:
                logger.debug("Error closing telemetry store: %s", exc)
        return

    # Direct-to-engine mode (no agent)
    messages = [Message(role=Role.USER, content=query_text)]

    # Memory-augmented context injection
    if not no_context and config.agent.context_from_memory:
        try:
            from openjarvis.tools.storage.context import (
                ContextConfig,
                inject_context,
            )

            backend = _get_memory_backend(config)
            if backend is not None:
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=(config.memory.context_max_tokens),
                )
                messages = inject_context(
                    query_text,
                    messages,
                    backend,
                    config=ctx_cfg,
                )
        except Exception as exc:
            logger.debug("Failed to inject memory context: %s", exc)

    # Generate (InstrumentedEngine handles telemetry + energy recording)
    try:
        with console.status("[bold green]Generating...[/bold green]"):
            result = engine.generate(
                messages,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )
    except EngineConnectionError as exc:
        console.print(f"[red]Engine error:[/red] {exc}")
        console.print(hint_no_engine())
        sys.exit(1)

    # Output
    if output_json:
        click.echo(json_mod.dumps(result, indent=2))
    else:
        click.echo(result.get("content", ""))

    if enable_profile:
        _print_profile(
            bus,
            time.monotonic() - wall_start,
            engine_name,
            model_name,
            console,
            complexity_result=complexity_result,
        )

    # Cleanup
    if energy_monitor is not None:
        try:
            energy_monitor.close()
        except Exception as exc:
            logger.debug("Error closing energy monitor: %s", exc)
    if telem_store is not None:
        try:
            telem_store.close()
        except Exception as exc:
            logger.debug("Error closing telemetry store: %s", exc)
