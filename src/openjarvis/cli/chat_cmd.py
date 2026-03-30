"""``jarvis chat`` — interactive multi-turn chat REPL.

Includes Claude Code-style slash commands.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.shortcuts import CompleteStyle
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from openjarvis.cli._tool_names import resolve_tool_names
from openjarvis.core.config import load_config
from openjarvis.core.types import Message, Role

# ---------------------------------------------------------------------------
# Slash command registry
# ---------------------------------------------------------------------------

# (description, args-hint)
SLASH_COMMANDS: dict[str, tuple[str, str]] = {
    "/help": ("Show available slash commands", ""),
    "/quit": ("Exit the session", ""),
    "/clear": ("Clear conversation history", ""),
    "/compact": ("Summarize and compress history", ""),
    "/history": ("Show conversation history", ""),
    "/model": ("Show or switch model", "[model-name]"),
    "/engine": ("Show or switch inference engine", "[engine-key]"),
    "/agent": ("Show or switch agent", "[agent-name]"),
    "/system": ("Show or set system prompt", "[prompt]"),
    "/tools": ("List available tools", ""),
    "/status": ("Show session status", ""),
    "/multiline": ("Toggle multiline input (end with .)", ""),
    "/save": ("Save conversation to a JSON file", "<filename>"),
    "/load": ("Load conversation from a JSON file", "<filename>"),
}

_CMD_ALIASES: dict[str, str] = {
    "/exit": "/quit",
    "/q": "/quit",
}


# ---------------------------------------------------------------------------
# Completer — activates on '/', filters as you type
# ---------------------------------------------------------------------------


class _SlashCompleter(Completer):
    """Shows slash commands the moment '/' is typed; filters with each keystroke."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        # Only complete the first word and only when it starts with /
        if text.startswith("/") and " " not in text:
            for cmd, (desc, args) in SLASH_COMMANDS.items():
                if cmd.startswith(text):
                    meta = f"{desc}  {args}".strip() if args else desc
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display=cmd,
                        display_meta=meta,
                    )


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def _make_session() -> PromptSession:
    return PromptSession(
        completer=_SlashCompleter(),
        complete_while_typing=True,
        complete_style=CompleteStyle.MULTI_COLUMN,
        history=InMemoryHistory(),
    )


def _read_input(
    session: PromptSession, prompt_str: str, multiline: bool
) -> Optional[str]:
    """Read one user turn.

    Returns:
        str   — the input (may be empty if Ctrl+C cancelled the line)
        None  — EOF / Ctrl+D → caller should exit
    """
    try:
        line = session.prompt(prompt_str)
    except KeyboardInterrupt:
        return ""  # Ctrl+C cancels current line; REPL continues
    except EOFError:
        return None  # Ctrl+D exits

    if not multiline:
        return line

    # Multiline: accumulate until user enters a lone "."
    lines = [line]
    while True:
        try:
            nxt = session.prompt("... ")
        except (EOFError, KeyboardInterrupt):
            break
        if nxt.strip() == ".":
            break
        lines.append(nxt)
    return "\n".join(lines)


def _print_help(console: Console) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column("cmd", style="bold cyan", no_wrap=True)
    table.add_column("args", style="dim", no_wrap=True)
    table.add_column("desc", style="white")
    for cmd, (desc, args) in SLASH_COMMANDS.items():
        table.add_row(cmd, args or "", desc)
    console.print(
        Panel(
            table,
            title="[bold]Commands[/bold]",
            title_align="left",
            border_style="dim",
            padding=(0, 1),
        )
    )


# ---------------------------------------------------------------------------
# Main command
# ---------------------------------------------------------------------------


@click.command()
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
@click.option("--tools", default=None, help="Comma-separated tool names.")
@click.option("--system", "system_prompt", default=None, help="Custom system prompt.")
def chat(
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
    tools: str | None,
    system_prompt: str | None,
) -> None:
    """Start an interactive multi-turn chat session.

    Type / to browse slash commands with live filtering.
    """
    console = Console(stderr=True)
    session = _make_session()
    config = load_config()

    # ---- Engine ----------------------------------------------------------------
    from openjarvis.engine import get_engine
    from openjarvis.intelligence import register_builtin_models

    register_builtin_models()

    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print("[red]No inference engine available.[/red]")
        sys.exit(1)

    engine_name, engine = resolved
    model = model_name or config.intelligence.default_model
    if not model:
        from openjarvis.engine import discover_engines, discover_models

        all_engines = discover_engines(config)
        all_models = discover_models(all_engines)
        engine_models = all_models.get(engine_name, [])
        if engine_models:
            model = engine_models[0]
        else:
            console.print("[red]No model available.[/red]")
            sys.exit(1)

    # ---- Agent (optional) ------------------------------------------------------
    agent = None
    agent_key: str | None = agent_name or config.agent.default_agent

    def _load_agent(key: str | None) -> None:
        nonlocal agent, agent_key
        if not key or key == "none":
            agent = None
            agent_key = None
            return
        try:
            import openjarvis.agents  # noqa: F401
            from openjarvis.core.events import EventBus
            from openjarvis.core.registry import AgentRegistry

            if not AgentRegistry.contains(key):
                console.print(f"[yellow]Agent '{key}' not found.[/yellow]")
                return

            agent_cls = AgentRegistry.get(key)
            kwargs: dict = {"bus": EventBus()}

            if getattr(agent_cls, "accepts_tools", False):
                tool_names_list = resolve_tool_names(
                    tools,
                    getattr(config.tools, "enabled", None),
                    getattr(config.agent, "tools", None),
                )
                if tool_names_list:
                    import openjarvis.tools  # noqa: F401
                    from openjarvis.core.registry import ToolRegistry
                    from openjarvis.tools._stubs import BaseTool

                    tool_instances = []
                    for tname in tool_names_list:
                        if ToolRegistry.contains(tname):
                            tcls = ToolRegistry.get(tname)
                            if isinstance(tcls, type) and issubclass(tcls, BaseTool):
                                tool_instances.append(tcls())
                            elif isinstance(tcls, BaseTool):
                                tool_instances.append(tcls)
                    if tool_instances:
                        kwargs["tools"] = tool_instances

                kwargs["max_turns"] = config.agent.max_turns

                def _confirm(prompt: str) -> bool:
                    console.print(f"[yellow]Confirm:[/yellow] {prompt} [y/N] ", end="")
                    ans = input().strip().lower()
                    return ans in ("y", "yes")

                kwargs["interactive"] = True
                kwargs["confirm_callback"] = _confirm

            agent = agent_cls(engine, model, **kwargs)
            agent_key = key
        except Exception as exc:
            console.print(f"[yellow]Agent '{key}' failed to load: {exc}[/yellow]")

    _load_agent(agent_key)

    # ---- Banner ----------------------------------------------------------------
    import openjarvis

    console.print(
        Panel(
            f"[bold green]OpenJarvis[/bold green] "
            f"[dim]v{openjarvis.__version__}[/dim]\n"
            f"[dim]Engine:[/dim] [cyan]{engine_name}[/cyan]  "
            f"[dim]Model:[/dim] [cyan]{model}[/cyan]  "
            f"[dim]Agent:[/dim] [cyan]{agent_key or 'direct'}[/cyan]\n"
            f"[dim]Type [/dim][bold cyan]/[/bold cyan][dim] to browse commands, "
            f"[/dim][bold cyan]/quit[/bold cyan][dim] to exit.[/dim]",
            border_style="green",
            padding=(0, 1),
        )
    )

    # ---- Conversation state ----------------------------------------------------
    history: List[Message] = []
    active_system = system_prompt
    multiline = False

    def _messages_for_generate() -> List[Message]:
        if active_system:
            return [Message(role=Role.SYSTEM, content=active_system)] + history
        return list(history)

    # ---- REPL ------------------------------------------------------------------
    while True:
        prompt_str = "... > " if multiline else "> "
        user_input = _read_input(session, prompt_str, multiline)

        if user_input is None:
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input_stripped = user_input.strip()
        if not user_input_stripped:
            continue

        # Bare "/" — show help panel (mirrors Claude Code's behaviour when user
        # types / and hits Enter without selecting a command from the dropdown)
        if user_input_stripped == "/":
            _print_help(console)
            continue

        parts = user_input_stripped.split(None, 1)
        raw_cmd = parts[0].lower()
        cmd = _CMD_ALIASES.get(raw_cmd, raw_cmd)
        rest = parts[1].strip() if len(parts) > 1 else ""

        # ---- Slash command dispatch --------------------------------------------

        if cmd == "/quit":
            console.print("[dim]Goodbye![/dim]")
            break

        elif cmd == "/help":
            _print_help(console)

        elif cmd == "/clear":
            history.clear()
            console.print("[dim]History cleared.[/dim]")

        elif cmd == "/compact":
            if not history:
                console.print("[dim]Nothing to compact.[/dim]")
            else:
                try:
                    summary_msgs = _messages_for_generate() + [
                        Message(
                            role=Role.USER,
                            content=(
                                "Summarize this conversation so far "
                                "in a concise paragraph, "
                                "preserving all key facts and decisions."
                            ),
                        )
                    ]
                    result = engine.generate(summary_msgs, model=model)
                    summary = (
                        result.get("content", "")
                        if isinstance(result, dict)
                        else str(result)
                    )
                    history.clear()
                    history.append(
                        Message(
                            role=Role.ASSISTANT,
                            content=f"[Conversation summary]\n{summary}",
                        )
                    )
                    console.print("[dim]History compacted.[/dim]")
                except Exception as exc:
                    console.print(f"[red]Compact failed: {exc}[/red]")

        elif cmd == "/history":
            msgs = _messages_for_generate()
            if not msgs:
                console.print("[dim]No history yet.[/dim]")
            else:
                for msg in msgs:
                    role_str = msg.role if isinstance(msg.role, str) else msg.role.value
                    preview = msg.content[:300] + (
                        "…" if len(msg.content) > 300 else ""
                    )
                    console.print(
                        f"[bold cyan]{role_str.upper()}[/bold cyan]: {preview}"
                    )

        elif cmd == "/model":
            if rest:
                model = rest
                console.print(f"[dim]Model set to [cyan]{model}[/cyan].[/dim]")
            else:
                console.print(
                    f"[dim]Engine:[/dim] [cyan]{engine_name}[/cyan]  "
                    f"[dim]Model:[/dim] [cyan]{model}[/cyan]"
                )

        elif cmd == "/engine":
            if rest:
                from openjarvis.engine import get_engine as _ge

                resolved2 = _ge(config, rest)
                if resolved2:
                    engine_name, engine = resolved2
                    console.print(
                        f"[dim]Switched to engine [cyan]{engine_name}[/cyan].[/dim]"
                    )
                else:
                    console.print(f"[red]Engine '{rest}' not available.[/red]")
            else:
                console.print(f"[dim]Engine:[/dim] [cyan]{engine_name}[/cyan]")

        elif cmd == "/agent":
            if rest:
                _load_agent(rest)
                console.print(
                    f"[dim]Agent set to [cyan]{agent_key or 'direct'}[/cyan].[/dim]"
                )
            else:
                console.print(f"[dim]Agent:[/dim] [cyan]{agent_key or 'direct'}[/cyan]")

        elif cmd == "/system":
            if rest:
                active_system = rest
                console.print("[dim]System prompt updated.[/dim]")
            else:
                if active_system:
                    console.print(f"[dim]System prompt:[/dim] {active_system}")
                else:
                    console.print(
                        "[dim]No system prompt set. Usage: /system <prompt>[/dim]"
                    )

        elif cmd == "/tools":
            try:
                import openjarvis.tools  # noqa: F401
                from openjarvis.core.registry import ToolRegistry

                keys = (
                    list(ToolRegistry._registry.keys())
                    if hasattr(ToolRegistry, "_registry")
                    else []
                )
                if keys:
                    table = Table(show_header=False, box=None, padding=(0, 2))
                    table.add_column("name", style="cyan")
                    for tname in sorted(keys):
                        table.add_row(tname)
                    console.print(
                        Panel(
                            table,
                            title="[bold]Available Tools[/bold]",
                            title_align="left",
                            border_style="dim",
                        )
                    )
                else:
                    console.print("[dim]No tools registered.[/dim]")
            except Exception as exc:
                console.print(f"[red]Could not list tools: {exc}[/red]")

        elif cmd == "/status":
            n_user = sum(1 for m in history if m.role == Role.USER)
            console.print(
                f"[dim]Engine:[/dim] [cyan]{engine_name}[/cyan]  "
                f"[dim]Model:[/dim] [cyan]{model}[/cyan]  "
                f"[dim]Agent:[/dim] [cyan]{agent_key or 'direct'}[/cyan]\n"
                f"[dim]Turns:[/dim] [cyan]{n_user}[/cyan]  "
                f"[dim]Multiline:[/dim] [cyan]{multiline}[/cyan]  "
                f"[dim]System:[/dim] [cyan]{'set' if active_system else 'none'}[/cyan]"
            )

        elif cmd == "/multiline":
            multiline = not multiline
            hint = " (end each turn with a lone '.')" if multiline else ""
            console.print(f"[dim]Multiline {'on' if multiline else 'off'}.{hint}[/dim]")

        elif cmd == "/save":
            filename = rest or "conversation.json"
            try:
                data = [
                    {
                        "role": m.role if isinstance(m.role, str) else m.role.value,
                        "content": m.content,
                    }
                    for m in _messages_for_generate()
                ]
                Path(filename).write_text(json.dumps(data, indent=2))
                console.print(f"[dim]Saved to [cyan]{filename}[/cyan].[/dim]")
            except Exception as exc:
                console.print(f"[red]Save failed: {exc}[/red]")

        elif cmd == "/load":
            if not rest:
                console.print("[yellow]Usage: /load <filename>[/yellow]")
            else:
                try:
                    data = json.loads(Path(rest).read_text())
                    history.clear()
                    active_system = None
                    for entry in data:
                        role = Role(entry["role"])
                        if role == Role.SYSTEM:
                            active_system = entry["content"]
                        else:
                            history.append(Message(role=role, content=entry["content"]))
                    console.print(
                        f"[dim]Loaded {len(data)} messages "
                        f"from [cyan]{rest}[/cyan].[/dim]"
                    )
                except Exception as exc:
                    console.print(f"[red]Load failed: {exc}[/red]")

        elif user_input_stripped.startswith("/"):
            console.print(
                f"[yellow]Unknown command: [bold]{parts[0]}[/bold]. "
                f"Type [bold]/[/bold] to see available commands.[/yellow]"
            )

        # ---- Regular chat message ---------------------------------------------
        else:
            history.append(Message(role=Role.USER, content=user_input_stripped))

            try:
                if agent is not None:
                    response = agent.run(user_input_stripped)
                    content = (
                        response.content
                        if hasattr(response, "content")
                        else str(response)
                    )
                else:
                    result = engine.generate(_messages_for_generate(), model=model)
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
                if history and history[-1].role == Role.USER:
                    history.pop()
            except Exception as exc:
                console.print(f"\n[red]Error: {exc}[/red]\n")
                if history and history[-1].role == Role.USER:
                    history.pop()


__all__ = ["chat"]
