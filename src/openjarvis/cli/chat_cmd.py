"""``jarvis chat`` — interactive multi-turn chat REPL."""

from __future__ import annotations

import sys
from typing import List, Optional

import click
from rich.console import Console
from rich.markdown import Markdown

from openjarvis.cli._runtime_panel import runtime_cli_options
from openjarvis.cli._tool_names import resolve_tool_names
from openjarvis.core.config import load_config
from openjarvis.core.types import Message, Role


def _read_input(prompt: str = "You> ") -> Optional[str]:
    """Read user input with graceful EOF handling."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


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
@runtime_cli_options
def chat(
    engine_key: str | None,
    model_name: str | None,
    pick_model: bool,
    agent_name: str | None,
    tools: str | None,
    system_prompt: str | None,
    num_ctx: int | None,
    num_gpu: int | None,
    skip_runtime_panel: bool,
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
      /runtime      — context + GPU offload for this session
      /help         — show available commands
      /history      — show conversation history
    """
    console = Console(stderr=True)

    config = load_config()

    # Resolve engine
    from openjarvis.engine import get_engine
    from openjarvis.intelligence import register_builtin_models

    register_builtin_models()

    resolved = get_engine(config, engine_key)
    if resolved is None:
        console.print("[red]No inference engine available.[/red]")
        sys.exit(1)

    engine_name, engine = resolved
    from openjarvis.cli._model_switch import (
        interactive_pick_model,
        resolve_chat_cli_model,
        tty_wants_model_picker,
    )

    model = ""
    if tty_wants_model_picker(pick_model):
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
            chat_variant="chat",
        )
    if not model:
        console.print("[red]No model available.[/red]")
        sys.exit(1)

    from openjarvis.cli._runtime_panel import (
        ChatRuntimeOptions,
        interactive_pick_runtime_options,
        tty_wants_runtime_panel,
    )

    if tty_wants_runtime_panel(skip_runtime_panel):
        runtime_opts = interactive_pick_runtime_options(
            console,
            engine_name=engine_name,
            cli_num_ctx=num_ctx,
            cli_num_gpu=num_gpu,
        )
    elif num_ctx is not None or num_gpu is not None:
        runtime_opts = ChatRuntimeOptions(num_ctx=num_ctx, num_gpu=num_gpu)
    else:
        runtime_opts = ChatRuntimeOptions()
    engine_kwargs = runtime_opts.to_engine_kwargs()

    # Resolve agent (optional)
    agent = None
    agent_key = agent_name or config.agent.default_agent
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
                        tools,
                        getattr(config.tools, "enabled", None),
                        getattr(config.agent, "tools", None),
                    )
                    if tool_names_list:
                        import openjarvis.tools  # noqa: F401 — trigger registration
                        from openjarvis.core.registry import ToolRegistry
                        from openjarvis.tools._stubs import BaseTool

                        tool_instances = []
                        for tname in tool_names_list:
                            if ToolRegistry.contains(tname):
                                tcls = ToolRegistry.get(tname)
                                if isinstance(tcls, type) and issubclass(
                                    tcls, BaseTool
                                ):
                                    tool_instances.append(tcls())
                                elif isinstance(tcls, BaseTool):
                                    tool_instances.append(tcls)
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
                if engine_kwargs:
                    kwargs["engine_options"] = engine_kwargs
                agent = agent_cls(engine, model, **kwargs)
        except Exception as exc:
            console.print(f"[yellow]Agent '{agent_key}' failed: {exc}[/yellow]")

    # Print banner
    console.print(
        f"[green bold]OpenJarvis Chat[/green bold]\n"
        f"  Engine: [cyan]{engine_name}[/cyan]  Model: [cyan]{model}[/cyan]"
        f"  Agent: [cyan]{agent_key or 'direct'}[/cyan]\n"
        f"  Runtime: [cyan]{runtime_opts.summary(engine_name=engine_name)}[/cyan]\n"
        f"  Type /help for commands, /quit to exit.\n",
    )

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
    if system_prompt:
        history.append(Message(role=Role.SYSTEM, content=system_prompt))

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
            if system_prompt:
                history.append(Message(role=Role.SYSTEM, content=system_prompt))
            console.print("[dim]History cleared.[/dim]")
            continue
        elif cmd == "/model":
            console.print(
                f"Model: [cyan]{model}[/cyan]  Engine: [cyan]{engine_name}[/cyan]"
            )
            continue
        elif cmd == "/runtime":
            console.print(
                f"Runtime: [cyan]{runtime_opts.summary(engine_name=engine_name)}[/cyan]"
            )
            if engine_kwargs:
                console.print(f"  engine kwargs: {engine_kwargs}")
            continue
        elif cmd == "/help":
            console.print(
                "[bold]Commands:[/bold]\n"
                "  /quit, /exit  — end session\n"
                "  /clear        — clear conversation\n"
                "  /model        — show model info\n"
                "  /runtime      — context + GPU offload for this session\n"
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
                response = agent.run(user_input)
                content = (
                    response.content if hasattr(response, "content") else str(response)
                )
            else:
                result = engine.generate(
                    history,
                    model=model,
                    **engine_kwargs,
                )
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


__all__ = ["chat"]
