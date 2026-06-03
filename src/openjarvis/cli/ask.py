"""``jarvis ask`` — send a query to the assistant."""

from __future__ import annotations

import json as json_mod
import logging
import sys
import time

import click
from rich.console import Console
from rich.table import Table

from openjarvis.cli._banner import print_banner
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


def _run_research(
    *,
    query_text: str,
    engine,
    model_name: str | None,
    knowledge_db: str | None,
    output_json: bool,
    console: Console,
) -> None:
    """Run the hybrid-search research loop and print the result to the console.

    Lazy imports keep the cost of this branch off the cold-path of plain
    ``jarvis ask`` calls.
    """
    import re

    from rich.markdown import Markdown
    from rich.theme import Theme

    from openjarvis.agents.research_loop import DEFAULT_PLANNER_MODEL, ResearchAgent
    from openjarvis.connectors.embeddings import OllamaEmbedder
    from openjarvis.connectors.hybrid_search import HybridSearch
    from openjarvis.connectors.store import KnowledgeStore
    from openjarvis.engine.ollama import OllamaEngine

    store_kwargs: dict = {}
    if knowledge_db:
        store_kwargs["db_path"] = knowledge_db
    store = KnowledgeStore(**store_kwargs)

    # Research mode is wired specifically to Ollama: the planner prompt
    # (gemma4:31b) and the function-call schema for search/clarify both
    # assume Ollama's /api/chat tool semantics. Using the engine returned
    # by get_engine() here is a foot-gun — discovery can pick any
    # OpenAI-compatible engine registered on the same port as our own
    # API server. research_router.py hardcodes OllamaEngine() for the
    # same reason; mirror that here so CLI and HTTP behave identically.
    engine = OllamaEngine()

    chunk_count = store._conn.execute(
        "SELECT COUNT(*) FROM knowledge_chunks"
    ).fetchone()[0]
    logger.debug(
        "research: engine=%s.%s db=%s chunks=%d",
        type(engine).__module__,
        type(engine).__name__,
        store._db_path,
        chunk_count,
    )

    embedder = OllamaEmbedder()
    embedder_available = embedder.is_available()
    logger.debug("research: embedder available=%s", embedder_available)
    if not embedder_available:
        console.print(
            "[yellow]Ollama embedder unavailable — falling back to BM25-only "
            "retrieval. Run `ollama pull nomic-embed-text` for hybrid scoring.[/yellow]"
        )
        embedder = None

    planner_model = model_name or DEFAULT_PLANNER_MODEL
    logger.debug("research: planner_model=%s", planner_model)

    # ---- Output styling --------------------------------------------------
    # Two consoles by design: traces and the timing footer go to stderr
    # (so ``jarvis ask --research "..." > out.md`` still gives a clean
    # markdown file), while the rendered synthesis goes to stdout. The
    # ``markdown.code`` theme override is the cyan-citation hack — see
    # ``_style_citations`` below.
    trace = Console(stderr=True, soft_wrap=True, highlight=False)
    answer_console = Console(
        theme=Theme({"markdown.code": "cyan bold not italic"}),
        soft_wrap=True,
        highlight=False,
    )

    def _style_citations(text: str) -> str:
        """Wrap each ``[N]`` in inline code so it renders cyan.

        Rich's Markdown class doesn't expose any hook for styling
        arbitrary text spans, so we cheat: convert the citation tokens
        into inline-code markdown (`[1]` → `` `[1]` ``) and override
        the ``markdown.code`` theme entry above to colour them. Trims
        the implicit monospace background that some terminal themes
        give inline code so the result reads as text, not as code.
        """
        return re.sub(r"(\[\d+\])", r"`\1`", text)

    def _format_search_call(args: dict) -> str:
        q = args.get("query", "") or ""
        extras: list[str] = []
        person = args.get("person")
        if person:
            extras.append(f"person: {person}")
        time_range = args.get("time_range")
        if isinstance(time_range, dict):
            start = time_range.get("start") or ""
            end = time_range.get("end") or ""
            if start or end:
                bounds = f"{start or '…'} → {end or '…'}"
                extras.append(f"when: {bounds}")
        suffix = f" ({', '.join(extras)})" if extras else ""
        return f"'{q}'{suffix}"

    def on_event(event: dict) -> None:
        etype = event.get("type")
        if etype == "search_call":
            args = event.get("arguments", {})
            trace.print(
                f"  [dim]↳ Searching:[/dim] "
                f"[dim italic]{_format_search_call(args)}[/dim italic]"
            )
        elif etype == "search_result":
            n = event.get("num_hits", 0)
            label = "result" if n == 1 else "results"
            trace.print(f"  [dim]↳ Found {n} {label}[/dim]")
        elif etype == "clarify_call":
            q = event.get("question", "") or ""
            trace.print(f"  [dim]↳ Clarifying:[/dim] [dim italic]{q}[/dim italic]")
        # final_answer and clarify_response are handled outside the loop.

    agent = ResearchAgent(
        engine=engine,
        search=HybridSearch(store, embedder),
        model=planner_model,
        on_event=on_event,
    )

    started = time.monotonic()
    result = agent.run(query_text)
    elapsed = time.monotonic() - started

    logger.debug(
        "research: iterations=%d tool_calls=%d usage=%s",
        result.iterations,
        len(result.tool_calls),
        result.usage,
    )

    if output_json:
        click.echo(
            json_mod.dumps(
                {
                    "answer": result.answer,
                    "iterations": result.iterations,
                    "usage": result.usage,
                    "tool_calls": [
                        {
                            "arguments": inv.arguments,
                            "num_results": inv.num_results,
                            "top_titles": inv.top_titles,
                        }
                        for inv in result.tool_calls
                    ],
                },
                indent=2,
            )
        )
        return

    # Visual break between live traces and the synthesis.
    trace.print()

    # Render the synthesis as Markdown with inline citations coloured cyan.
    answer_console.print(Markdown(_style_citations(result.answer)))

    # Footer: how long it took + how many distinct sources the model
    # actually cited. Empty answers (rare; only if the model went silent)
    # skip the footer entirely.
    if result.answer:
        cited = {int(n) for n in re.findall(r"\[(\d+)\]", result.answer)}
        src_word = "source" if len(cited) == 1 else "sources"
        # Report the model and engine that actually served the query rather
        # than hardcoding: planner_model is the resolved model passed to the
        # agent, and engine_id is the backend's own identifier ("ollama").
        engine_label = getattr(engine, "engine_id", type(engine).__name__)
        trace.print()
        trace.print(
            f"[dim]Deep Research · {elapsed:.1f}s · "
            f"{len(cited)} {src_word} cited · {planner_model} · {engine_label}[/dim]"
        )


def _get_memory_backend(config):
    """Try to instantiate the memory backend.

    Returns None on failure and logs at DEBUG. Callers that *require*
    the backend (e.g. when a memory tool is being instantiated) should
    warn loudly themselves — silent failure of an explicitly-requested
    tool is the hallucination vector.
    """
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

        return backend
    except Exception as exc:
        logger.debug("Memory backend unavailable (optional): %s", exc)
        return None


_MEMORY_TOOLS = frozenset(
    {"retrieval", "memory_store", "memory_search", "memory_index", "memory_retrieve"}
)
_CHANNEL_TOOLS = frozenset({"channel_send", "channel_list", "channel_status"})


def _build_tools(
    tool_names: list[str],
    config,
    engine,
    model_name: str,
    *,
    channel=None,
):
    """Instantiate tool objects from names.

    ``channel`` is an optional :class:`BaseChannel` used by ``channel_*``
    tools. Threading it through here mirrors how memory backends are
    injected; without it, channel tools have no backend and fail at
    runtime.

    Emits a WARNING when a memory tool is requested but no backend is
    available, and when a channel tool is requested but no channel is
    provided — these are the failure modes that silently cascade into
    hallucinated or dropped replies downstream.
    """
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
        if name in _MEMORY_TOOLS:
            backend = _get_memory_backend(config)
            if backend is None:
                logger.warning(
                    "Tool %r was requested but no memory backend is "
                    "available (default=%r). The tool will load but "
                    "return no results — downstream agents may answer "
                    "without grounding.",
                    name,
                    getattr(config.memory, "default_backend", "?"),
                )
            tools.append(tool_cls(backend=backend))
        elif name in _CHANNEL_TOOLS:
            if channel is None:
                logger.warning(
                    "Tool %r was requested but no channel was injected. "
                    "The tool will load but every call will fail with "
                    "'No channel backend configured'.",
                    name,
                )
            tools.append(tool_cls(channel=channel))
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
    memory_files_config=None,
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

    # Wire the SystemPromptBuilder so SOUL.md / MEMORY.md / USER.md persona
    # files actually reach the model. Only passed to agents whose __init__
    # accepts a `prompt_builder` kwarg (BaseAgent does; agents that override
    # __init__ without forwarding it, e.g. OrchestratorAgent, opt out
    # automatically and keep their existing system-prompt machinery).
    import inspect as _inspect

    if "prompt_builder" in _inspect.signature(agent_cls.__init__).parameters:
        from openjarvis.prompt.builder import SystemPromptBuilder

        agent_kwargs["prompt_builder"] = SystemPromptBuilder(
            agent_template=config.agent.default_system_prompt or "",
            memory_files_config=memory_files_config or config.memory_files,
            system_prompt_config=config.system_prompt,
        )

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
    help=(
        "Agent to use (simple, orchestrator, ...). "
        "When omitted, falls back to ``agent.default_agent`` from config. "
        "Pass ``--agent ''`` to force direct-to-engine mode (no agent)."
    ),
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
@click.option(
    "--research",
    "research_mode",
    is_flag=True,
    help=(
        "Route the query through the hybrid-search research agent over the "
        "personal knowledge store (BM25 + dense embeddings, max 5 tool calls)."
    ),
)
@click.option(
    "--knowledge-db",
    "knowledge_db",
    default=None,
    help=(
        "Override the KnowledgeStore path used by --research "
        "(default: ~/.openjarvis/knowledge.db)."
    ),
)
@click.option(
    "--persona",
    "persona_name",
    default=None,
    help=(
        "Named persona dir under ~/.openjarvis/personas/<name>/ "
        "(overrides config). Pass 'none' to disable all persona files."
    ),
)
@click.pass_context
def ask(
    ctx: click.Context,
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
    research_mode: bool,
    knowledge_db: str | None,
    persona_name: str | None,
) -> None:
    """Ask Jarvis a question."""
    quiet = (ctx.obj or {}).get("quiet", False) or output_json
    print_banner(quiet=quiet)
    console = Console(stderr=True)
    query_text = " ".join(query)

    wall_start = time.monotonic() if enable_profile else None

    # Load config
    config = load_config()

    # Resolve effective MemoryFilesConfig with --persona override
    import dataclasses as _dc

    effective_mf = (
        _dc.replace(config.memory_files, persona_name=persona_name)
        if persona_name is not None
        else config.memory_files
    )

    # Honor `agent.default_agent` from config when --agent was not explicitly
    # passed. Pass `--agent ""` to opt out and use direct-to-engine mode.
    # Without this fallback, `[agent].default_system_prompt` and the
    # SOUL.md / MEMORY.md / USER.md persona system are silently bypassed for
    # the most common command (`jarvis ask "..."`).
    if agent_name is None:
        configured_default = (config.agent.default_agent or "").strip()
        if configured_default:
            agent_name = configured_default

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

    # ------------------------------------------------------------------
    # Research mode — hybrid search + agentic loop over the knowledge store
    # ------------------------------------------------------------------
    if research_mode:
        _run_research(
            query_text=query_text,
            engine=engine,
            model_name=model_name,
            knowledge_db=knowledge_db,
            output_json=output_json,
            console=console,
        )
        return

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

    # Agent mode (treat empty-string `--agent ""` as explicit opt-out)
    if agent_name:
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
                memory_files_config=effective_mf,
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
