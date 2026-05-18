"""``jarvis chat`` — interactive multi-turn chat REPL."""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, List, Optional

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape

from openjarvis.cli._chat_context import (
    LONG_MEMORY_SYSTEM,
    WEB_GROUNDING_SYSTEM,
    ensure_chat_tool_names,
    memory_context_messages,
    preflight_web_block,
    tool_names_include_web,
)
from openjarvis.cli._tool_names import (
    _normalize_tool_names,
    resolve_tool_names,
)
from openjarvis.core.config import JarvisConfig
from openjarvis.core.config import load_config
from openjarvis.core.types import Conversation, Message, Role


def _read_input(prompt: str = "You> ") -> Optional[str]:
    """Read user input with graceful EOF handling."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


_AUTO_LEARN_DEFAULT_SOURCES = (
    "web_search,file_read,get_file_contents,search_code,search_repositories"
)


def _auto_learn_from_tool_results(
    *,
    config: JarvisConfig,
    tool_results: list[Any],
    status: Callable[[str], None] | None = None,
) -> None:
    """Persist high-value tool outputs to Qdrant without model micromanagement."""
    tools_cfg = getattr(config, "tools", None)
    if tools_cfg is None:
        return
    if not bool(getattr(tools_cfg, "auto_learn_qdrant", True)):
        return
    if not tool_results:
        return

    mcp_cfg = getattr(tools_cfg, "mcp", None)
    if mcp_cfg is None or not bool(getattr(mcp_cfg, "enabled", True)):
        return

    allow_sources = set(
        _normalize_tool_names(
            getattr(tools_cfg, "auto_learn_sources", _AUTO_LEARN_DEFAULT_SOURCES)
        )
    )
    if not allow_sources:
        allow_sources = set(_normalize_tool_names(_AUTO_LEARN_DEFAULT_SOURCES))

    min_chars = int(getattr(tools_cfg, "auto_learn_min_chars", 160) or 160)
    max_chars = int(getattr(tools_cfg, "auto_learn_max_chars", 8000) or 8000)
    min_chunk_size = int(getattr(tools_cfg, "auto_learn_min_chunk_size", 20) or 20)

    candidates: list[tuple[str, str]] = []
    for tr in tool_results:
        name = str(getattr(tr, "tool_name", "") or "").strip()
        if not name or name not in allow_sources:
            continue
        if not bool(getattr(tr, "success", False)):
            continue
        content = str(getattr(tr, "content", "") or "").strip()
        if len(content) < min_chars:
            continue
        candidates.append((name, content[:max_chars]))

    if not candidates:
        return

    try:
        from openjarvis.tools.learn_qdrant import LearnQdrantTool

        learner = LearnQdrantTool()
    except Exception:
        return

    stored = 0
    for tool_name, text in candidates:
        result = learner.execute(
            text=text,
            source=f"auto:{tool_name}",
            origin=tool_name,
            min_chunk_size=min_chunk_size,
        )
        if result.success:
            stored += 1

    if status and stored:
        status(f"Auto-memory: stored {stored} tool result(s) in Qdrant.")


def run_chat_interactive(
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
    tools: str | None,
    system_prompt: str | None,
    *,
    default_agent_when_unset: str | None = None,
    default_tools_when_unset: str | None = None,
    extra_system_prompt: str | None = None,
    session_title: str | None = None,
    chat_variant: str | None = None,
    pick_model: bool = False,
) -> None:
    """Run the interactive REPL (shared by ``chat``, ``short``, ``long``, ``code``)."""
    console = Console(stderr=True)

    def _mcp_progress(msg: str) -> None:
        console.print(f"[dim]{escape(msg)}[/dim]")

    config = load_config()

    if agent_name is not None:
        eff_agent = agent_name
    elif default_agent_when_unset is not None:
        eff_agent = default_agent_when_unset
    else:
        eff_agent = config.agent.default_agent

    if tools is not None:
        eff_tools = tools
    elif default_tools_when_unset is not None:
        merged = list(_normalize_tool_names(default_tools_when_unset))
        seen = set(merged)
        for n in _normalize_tool_names(getattr(config.tools, "enabled", None)):
            if n not in seen:
                merged.append(n)
                seen.add(n)
        eff_tools = ",".join(merged)
    else:
        eff_tools = None

    if extra_system_prompt:
        eff_system = (
            f"{system_prompt}\n\n{extra_system_prompt}"
            if system_prompt
            else extra_system_prompt
        )
    else:
        eff_system = system_prompt

    if eff_agent not in (None, "none", "simple"):
        grounding = WEB_GROUNDING_SYSTEM
        if (chat_variant or "chat") in ("long", "chat"):
            grounding = f"{grounding}\n{LONG_MEMORY_SYSTEM}"
        eff_system = (
            f"{eff_system}\n\n{grounding}" if eff_system else grounding
        )

    # Resolve engine
    from openjarvis.engine import get_engine
    from openjarvis.intelligence import register_builtin_models

    register_builtin_models()

    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print("[red]No inference engine available.[/red]")
        sys.exit(1)

    engine_name, engine = resolved
    from openjarvis.cli._model_switch import interactive_pick_model, resolve_chat_cli_model

    model = ""
    if pick_model:
        console.print(
            "[dim]Pick a model below, or press Enter for config default "
            "(intelligence presets / default_model).[/dim]\n",
        )
        picked = interactive_pick_model(console, engine)
        if picked:
            model = picked
    if not model:
        model = resolve_chat_cli_model(
            console=console,
            config=config,
            engine=engine,
            engine_name=engine_name,
            cli_model=model_name,
            chat_variant=chat_variant or "chat",
        )
    if not model:
        console.print("[red]No model available.[/red]")
        sys.exit(1)

    agent_key = eff_agent
    banner_title = session_title or "OpenJarvis Chat"
    console.print(
        f"[green bold]{banner_title}[/green bold]\n"
        f"  Engine: [cyan]{engine_name}[/cyan]  Model: [cyan]{model}[/cyan]"
        f"  Agent: [cyan]{agent_key or 'direct'}[/cyan]\n"
        f"  Type /help for commands, /quit to exit.\n",
    )
    mcp_cfg = getattr(config.tools, "mcp", None)
    mcp_servers = (getattr(mcp_cfg, "servers", None) or "").strip()
    mcp_startup_hint = False
    will_load_mcp = False
    if (
        agent_key
        and agent_key != "none"
        and mcp_cfg
        and getattr(mcp_cfg, "enabled", True)
        and mcp_servers
    ):
        try:
            import openjarvis.agents  # noqa: F401 — registration for AgentRegistry
            from openjarvis.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls_probe = AgentRegistry.get(agent_key)
                if getattr(agent_cls_probe, "accepts_tools", False):
                    preview_tools = resolve_tool_names(
                        eff_tools,
                        getattr(config.tools, "enabled", None),
                        getattr(config.agent, "tools", None),
                    )
                    will_load_mcp = bool(preview_tools)
        except Exception:
            will_load_mcp = False

    if will_load_mcp:
        console.print(
            "[dim]The LLM model above is already selected — this step starts MCP "
            "(external tool processes), not model weights. Each line below is one "
            "server; first run can be slow (e.g. npx). Ctrl+C aborts startup.[/dim]\n",
        )
        mcp_startup_hint = True

    # Resolve agent (optional)
    agent = None
    if agent_key and agent_key != "none":
        try:
            import openjarvis.agents  # noqa: F401 — trigger registration
            from openjarvis.core.events import EventBus
            from openjarvis.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls = AgentRegistry.get(agent_key)
                kwargs: dict = {"bus": EventBus()}

                if getattr(agent_cls, "accepts_tools", False):
                    tool_names_list = resolve_tool_names(
                        eff_tools,
                        getattr(config.tools, "enabled", None),
                        getattr(config.agent, "tools", None),
                    )
                    if tool_names_list:
                        import openjarvis.tools  # noqa: F401 — trigger registration
                        from openjarvis.cli.ask import _build_tools

                        require_web = bool(
                            getattr(config.tools, "require_web_search", True),
                        )
                        require_mem = (chat_variant or "chat") in ("long", "chat")
                        tool_names_list = ensure_chat_tool_names(
                            tool_names_list,
                            require_web_search=require_web,
                            require_memory_retrieve=(
                                require_mem
                                and bool(
                                    getattr(
                                        config.agent,
                                        "context_from_memory",
                                        True,
                                    ),
                                )
                            ),
                        )
                        tool_instances = _build_tools(
                            tool_names_list,
                            config,
                            engine,
                            model,
                            mcp_status=_mcp_progress,
                        )
                        if tool_instances:
                            kwargs["tools"] = tool_instances
                    kwargs["max_turns"] = config.agent.max_turns

                    def _confirm(prompt: str) -> bool:
                        console.print(
                            f"[yellow]Confirm:[/yellow] {prompt} [y/N] ",
                            end="",
                        )
                        ans = input().strip().lower()
                        return ans in ("y", "yes")

                    kwargs["interactive"] = True
                    kwargs["confirm_callback"] = _confirm
                agent = agent_cls(engine, model, **kwargs)
        except Exception as exc:
            console.print(f"[yellow]Agent '{agent_key}' failed: {exc}[/yellow]")

    if mcp_startup_hint:
        console.print("[dim]Startup complete — you can type below.[/dim]\n")

    # Background-work status banner (disappears after first user message)
    from openjarvis.cli._bg_state import get_status
    from openjarvis.cli._chat_banner import render_startup_banner

    _banner = render_startup_banner(get_status())
    if _banner:
        console.print(f"[dim cyan]{_banner}[/dim cyan]")

    # Completion-notification dispatcher (fires once per task per session)
    from openjarvis.cli._chat_notifications import NotificationDispatcher

    _notifications = NotificationDispatcher(get_status())

    # Conversation state
    history: List[Message] = []
    if eff_system:
        history.append(Message(role=Role.SYSTEM, content=eff_system))

    # REPL loop
    while True:
        for note in _notifications.diff(get_status()):
            console.print(f"[dim cyan]{note}[/dim cyan]")

        user_input = _read_input()
        if user_input is None:
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # Handle slash commands
        cmd = user_input.lower()
        if cmd in ("/quit", "/exit", "/q"):
            console.print("[dim]Goodbye![/dim]")
            break
        elif cmd == "/clear":
            history = []
            if eff_system:
                history.append(Message(role=Role.SYSTEM, content=eff_system))
            console.print("[dim]History cleared.[/dim]")
            continue
        elif cmd == "/model":
            console.print(
                f"Model: [cyan]{model}[/cyan]  Engine: [cyan]{engine_name}[/cyan]"
            )
            continue
        elif cmd in ("/tools", "/mcp"):
            tn = resolve_tool_names(
                eff_tools,
                getattr(config.tools, "enabled", None),
                getattr(config.agent, "tools", None),
            )
            console.print("[bold]Konfiguracja narzędzi[/bold] (config, nie model LLM)")
            if tn:
                joined = ", ".join(tn)
                console.print(f"  [bold]tools.enabled / agent.tools:[/bold] {joined}")
            else:
                console.print("  [dim]Brak listy narzędzi w configu[/dim]")
            sx = (getattr(config.tools, "searxng_url", "") or "").strip()
            if sx:
                console.print(f"  [bold]SearXNG[/bold] (web_search): [cyan]{sx}[/cyan]")
            mcp_on = getattr(config.tools.mcp, "enabled", False)
            raw_srv = (getattr(config.tools.mcp, "servers", "") or "").strip()
            if mcp_on and raw_srv:
                try:
                    sl = json.loads(raw_srv)
                    console.print("  [bold]MCP servers[/bold] ([tools.mcp].servers):")
                    for s in sl:
                        if isinstance(s, dict):
                            nm = s.get("name", "?")
                            url = s.get("url")
                            cmd_m = s.get("command")
                            line = f"    - [cyan]{nm}[/cyan]  {url or cmd_m or '?'}"
                            console.print(line)
                except json.JSONDecodeError as exc:
                    console.print(f"  [red]Zły JSON w tools.mcp.servers: {exc}[/red]")
            else:
                console.print("  [dim]MCP wyłączone albo puste servers[/dim]")
            if tn:
                try:
                    from openjarvis.cli._external_mcp_tools import (
                        discover_external_mcp_tools,
                    )

                    extra = discover_external_mcp_tools(
                        config,
                        allowed_tool_names=set(tn),
                        status=_mcp_progress,
                    )
                    if extra:
                        console.print(
                            "  [bold]Narzędzia MCP załadowane[/bold]: "
                            + ", ".join(t.spec.name for t in extra)
                        )
                    else:
                        console.print(
                            "  [dim]Żadne narzędzie MCP nie pasuje do listy powyżej "
                            "(dopisz nazwy z serwera do tools.enabled).[/dim]"
                        )
                except Exception as exc:
                    console.print(f"  [yellow]Połączenie MCP: {exc}[/yellow]")
            ex = getattr(agent, "_executor", None) if agent is not None else None
            reg = sorted(getattr(ex, "_tools", {}).keys()) if ex is not None else []
            if reg:
                console.print(
                    "  [bold]Runtime (executor)[/bold]: " + ", ".join(reg)
                )
            console.print(
                "\n[dim]Tip: aktualne fakty → web_search; zindeksowana wiedza → "
                "memory_retrieve / jarvis memory index; MCP qdrant-find tylko "
                "dla istniejących kolekcji.[/dim]"
            )
            continue
        elif cmd == "/help":
            console.print(
                "[bold]Commands:[/bold]\n"
                "  /quit, /exit  — end session\n"
                "  /clear        — clear conversation\n"
                "  /model        — show model info\n"
                "  /tools, /mcp  — tools + MCP from config\n"
                "  /history      — show conversation\n"
                "  /help         — this message"
            )
            continue
        elif cmd == "/history":
            if not history:
                console.print("[dim]No history yet.[/dim]")
            else:
                for msg in history:
                    role_str = msg.role if isinstance(msg.role, str) else msg.role.value
                    role = role_str.upper()
                    console.print(f"[bold]{role}:[/bold] {msg.content[:200]}")
            continue

        # Add user message
        history.append(Message(role=Role.USER, content=user_input))

        # Generate response
        try:
            if agent is not None:
                from openjarvis.agents._stubs import AgentContext

                # Prior turns only: _build_messages() appends this user_input again.
                prior = list(history[:-1])
                conv = Conversation(messages=prior) if prior else Conversation()
                ctx = AgentContext(conversation=conv)
                for mem_msg in memory_context_messages(user_input, config):
                    ctx.conversation.add(mem_msg)
                agent_input = user_input
                agent_tools = getattr(agent, "_tools", None) or []
                if tool_names_include_web(agent_tools):
                    web_block = preflight_web_block(user_input)
                    if web_block:
                        console.print(
                            "[dim]web_search (preflight) — wyniki wstrzyknięte do "
                            "kontekstu; model ma odpowiadać tylko na ich podstawie.[/dim]",
                        )
                        agent_input = (
                            f"{user_input}\n\n"
                            "[Wyniki web_search — odpowiadaj WYŁĄCZNIE na tej "
                            "podstawie; nie używaj wiedzy z treningu o bieżących "
                            "wydarzeniach. Język odpowiedzi = język użytkownika.]\n\n"
                            f"{web_block}"
                        )
                response = agent.run(agent_input, context=ctx)
                content = (
                    response.content if hasattr(response, "content") else str(response)
                )
                _auto_learn_from_tool_results(
                    config=config,
                    tool_results=list(getattr(response, "tool_results", []) or []),
                    status=_mcp_progress,
                )
            else:
                result = engine.generate(history, model=model)
                content = (
                    result.get("content", "")
                    if isinstance(result, dict)
                    else str(result)
                )

            history.append(Message(role=Role.ASSISTANT, content=content))
            console.print()
            console.print(Markdown(content))
            console.print()
        except KeyboardInterrupt:
            console.print("\n[dim]Generation interrupted.[/dim]")
        except Exception as exc:
            console.print(f"\n[red]Error: {exc}[/red]\n")


@click.command()
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option(
    "-m",
    "--model",
    "model_name",
    default=None,
    help=(
        "Model id. Omit or use ``smart`` for preset: [intelligence] model_chat / "
        "model_short / model_long / model_code, then default_model."
    ),
)
@click.option(
    "--pick-model",
    "pick_model",
    is_flag=True,
    default=False,
    help=(
        "Show the model list before chat. Bare ``jarvis`` already does this on a TTY "
        "unless JARVIS_SKIP_MODEL_PICK=1."
    ),
)
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
@click.option("--tools", default=None, help="Comma-separated tool names.")
@click.option("--system", "system_prompt", default=None, help="Custom system prompt.")
def chat(
    engine_key: str | None,
    model_name: str | None,
    pick_model: bool,
    agent_name: str | None,
    tools: str | None,
    system_prompt: str | None,
) -> None:
    """Start an interactive multi-turn chat session.

    Model: omit ``-m`` to use ``[intelligence] model_chat`` if set, else
    ``default_model``; ``-m smart`` is the same. Use ``--pick-model`` to open the
    engine list first (bare ``jarvis`` does this on a TTY unless
    ``JARVIS_SKIP_MODEL_PICK=1``).

    Commands during chat:
      /quit, /exit  — end session
      /clear        — clear conversation history
      /model        — show current model
      /help         — show available commands
      /history      — show conversation history
      /tools, /mcp  — show tools + MCP from config (not from the model)

    Tiered shortcuts (same REPL, different defaults): ``jarvis short``, ``jarvis long``,
    ``jarvis code``.
    """
    run_chat_interactive(
        engine_key,
        model_name,
        agent_name,
        tools,
        system_prompt,
        default_agent_when_unset=None,
        default_tools_when_unset=None,
        extra_system_prompt=None,
        session_title=None,
        chat_variant="chat",
        pick_model=pick_model,
    )


__all__ = ["chat", "run_chat_interactive"]
