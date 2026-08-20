"""``jarvis chat`` — interactive multi-turn chat REPL."""

from __future__ import annotations

import logging
import sys
from typing import List, Optional

import click
from rich.console import Console
from rich.markdown import Markdown

from openjarvis.cli._tool_names import resolve_tool_names
from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.core.types import Message, Role
from openjarvis.memory import publish_completed_exchange

logger = logging.getLogger(__name__)


def _read_input(prompt: str = "You> ") -> Optional[str]:
    """Read user input with graceful EOF handling."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


_VOICE_EXIT = object()  # sentinel: user wants to quit


def _read_voice_input(console: "Console") -> "Optional[str] | object":
    """Accept a typed command/message, or record after an empty submission."""
    typed = _read_input("You> [type, or press Enter to speak] ")
    if typed is None:
        return _VOICE_EXIT
    typed = typed.strip()
    return typed if typed else _record_voice(console)


def _record_voice(console: "Console") -> "Optional[str] | object":
    """Record from mic, transcribe, and return text.

    Returns:
        str  — transcribed text to use as input
        None — nothing heard / transcription empty, try again
        _VOICE_EXIT — Ctrl-C / fatal error, caller should exit
    """
    from openjarvis.core.config import load_config
    from openjarvis.speech._discovery import get_speech_backend
    from openjarvis.speech.voice_io import record_until_silence

    config = load_config()
    backend = get_speech_backend(config)
    if backend is None:
        console.print(
            "[red]No speech-to-text backend available. "
            "Install faster-whisper: pip install faster-whisper[/red]"
        )
        return _VOICE_EXIT

    console.print("[dim cyan]Listening… (speak now, stops on silence)[/dim cyan]")
    try:
        audio_bytes = record_until_silence()
    except RuntimeError as exc:
        console.print(f"[red]Mic error: {exc}[/red]")
        return _VOICE_EXIT
    except KeyboardInterrupt:
        return _VOICE_EXIT

    console.print("[dim]Transcribing…[/dim]")
    try:
        result = backend.transcribe(audio_bytes, format="wav")
        text = result.text.strip()
        if text:
            console.print(f"[bold]You (voice):[/bold] {text}")
            return text
        console.print("[dim]Nothing heard — try again.[/dim]")
        return None
    except Exception as exc:
        console.print(f"[red]Transcription error: {exc}[/red]")
        return None


def _speak(text: str, console: "Console") -> None:
    """Synthesize text and play it back; silently skip on missing deps."""
    from openjarvis.core.registry import TTSRegistry
    from openjarvis.speech.voice_io import play_wav

    # Try kokoro first (local), then any registered TTS backend
    for key in ("kokoro", "openai_tts", "cartesia"):
        if TTSRegistry.contains(key):
            try:
                backend = TTSRegistry.get(key)()
                if not backend.health():
                    continue
                result = backend.synthesize(text, output_format="wav")
                if result.audio:
                    play_wav(result.audio, sample_rate=result.sample_rate)
                return
            except Exception:
                continue

    console.print(
        "[dim yellow]No TTS backend available — install kokoro: "
        "pip install kokoro[/dim yellow]"
    )


@click.command()
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option("-m", "--model", "model_name", default=None, help="Model to use.")
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
@click.option("--tools", default=None, help="Comma-separated tool names.")
@click.option("--system", "system_prompt", default=None, help="Custom system prompt.")
@click.option(
    "--persona",
    "persona_name",
    default=None,
    help=(
        "Named persona dir under ~/.openjarvis/personas/<name>/ "
        "(overrides config). Pass 'none' to disable all persona files."
    ),
)
@click.option(
    "--voice",
    "voice_mode",
    is_flag=True,
    default=False,
    help="Enable voice I/O: mic input with silence detection + TTS response playback.",
)
def chat(
    engine_key: str | None,
    model_name: str | None,
    agent_name: str | None,
    tools: str | None,
    system_prompt: str | None,
    persona_name: str | None,
    voice_mode: bool,
) -> None:
    """Start an interactive multi-turn chat session.

    Commands during chat:
      /quit, /exit  — end session
      /clear        — clear conversation history
      /model        — show current model
      /help         — show available commands
      /history      — show conversation history

    Pass --voice to use microphone input (silence-detection) and hear responses
    read back via text-to-speech (kokoro local or OpenAI TTS).
    """
    console = Console(stderr=True)

    config = load_config()
    bus = EventBus(record_history=False)

    import dataclasses as _dc

    effective_mf = (
        _dc.replace(config.memory_files, persona_name=persona_name)
        if persona_name is not None
        else config.memory_files
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

    # Resolve agent (optional)
    agent = None
    agent_key = agent_name or config.agent.default_agent
    if agent_key and agent_key != "none":
        try:
            import openjarvis.agents  # noqa: F401 — trigger registration
            from openjarvis.core.registry import AgentRegistry

            if AgentRegistry.contains(agent_key):
                agent_cls = AgentRegistry.get(agent_key)
                kwargs: dict = {"bus": bus}

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

                import inspect as _inspect

                if (
                    "prompt_builder"
                    in _inspect.signature(agent_cls.__init__).parameters
                ):
                    from openjarvis.prompt.builder import SystemPromptBuilder

                    kwargs["prompt_builder"] = SystemPromptBuilder(
                        agent_template=config.agent.default_system_prompt or "",
                        memory_files_config=effective_mf,
                        system_prompt_config=config.system_prompt,
                    )

                agent = agent_cls(engine, model, **kwargs)
        except Exception as exc:
            console.print(f"[yellow]Agent '{agent_key}' failed: {exc}[/yellow]")

    # Trigger TTS backend registration so _speak can find backends
    import openjarvis.speech  # noqa: F401

    # Print banner
    voice_hint = (
        "  [magenta]Voice mode ON[/magenta] — type normally, or press Enter "
        "to speak; silence stops recording.\n"
        if voice_mode
        else ""
    )
    console.print(
        f"[green bold]OpenJarvis Chat[/green bold]\n"
        f"  Engine: [cyan]{engine_name}[/cyan]  Model: [cyan]{model}[/cyan]"
        f"  Agent: [cyan]{agent_key or 'direct'}[/cyan]\n"
        f"{voice_hint}"
        f"  Type /help for commands, /quit to exit.\n"
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

    # Automatic long-term memory — extracts durable facts in the background.
    memory_service = None
    try:
        from openjarvis.memory import build_memory_service

        memory_service = build_memory_service(config, engine, model, event_bus=bus)
        if memory_service is not None:
            memory_service.start()
            console.print("[dim]  Memory: active[/dim]")
    except Exception as exc:
        console.print(f"[yellow]Memory service unavailable: {exc}[/yellow]")
        memory_service = None

    # The document backend and automatic fact store are separate persistence
    # mechanisms. Context injection combines both at read time so facts from
    # previous sessions are immediately available without a manual index step.
    memory_backend = None
    if config.agent.context_from_memory:
        from openjarvis.cli.ask import _get_memory_backend

        memory_backend = _get_memory_backend(config)

    # Conversation state
    if not system_prompt:
        from openjarvis.prompt.builder import SystemPromptBuilder

        builder = SystemPromptBuilder(
            agent_template=config.agent.default_system_prompt or "",
            memory_files_config=effective_mf,
            system_prompt_config=config.system_prompt,
        )
        system_prompt = builder.build()

    history: List[Message] = []
    if system_prompt:
        history.append(Message(role=Role.SYSTEM, content=system_prompt))

    # REPL loop
    while True:
        for note in _notifications.diff(get_status()):
            console.print(f"[dim cyan]{note}[/dim cyan]")

        if voice_mode:
            result = _read_voice_input(console)
            if result is _VOICE_EXIT:
                console.print("\n[dim]Goodbye![/dim]")
                break
            if result is None:
                continue  # nothing heard, loop again
            user_input = result
        else:
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
        elif cmd == "/help":
            console.print(
                "[bold]Commands:[/bold]\n"
                "  /quit, /exit  — end session\n"
                "  /clear        — clear conversation\n"
                "  /model        — show model info\n"
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

        generation_history = history
        agent_context_message = None
        if config.agent.context_from_memory:
            try:
                from openjarvis.memory import load_configured_facts
                from openjarvis.tools.storage.context import (
                    ContextConfig,
                    inject_context,
                )

                if memory_service is not None and hasattr(memory_service, "list_facts"):
                    facts = memory_service.list_facts()
                else:
                    facts = load_configured_facts(config)
                ctx_cfg = ContextConfig(
                    top_k=config.memory.context_top_k,
                    min_score=config.memory.context_min_score,
                    max_context_tokens=config.memory.context_max_tokens,
                )
                context_messages = inject_context(
                    user_input,
                    [] if agent is not None else history,
                    memory_backend,
                    config=ctx_cfg,
                    facts=facts,
                )
                if agent is not None:
                    if context_messages:
                        agent_context_message = context_messages[0]
                else:
                    generation_history = context_messages
            except Exception:
                logger.debug("Failed to inject memory context", exc_info=True)

        # Generate response even when optional memory context is unavailable.
        try:
            if agent is not None:
                from openjarvis.agents._stubs import AgentContext

                agent_context = AgentContext()
                if agent_context_message is not None:
                    agent_context.conversation.add(agent_context_message)
                for msg in history[:-1]:
                    if msg.role != Role.SYSTEM:
                        agent_context.conversation.add(msg)
                response = agent.run(user_input, context=agent_context)
                content = (
                    response.content if hasattr(response, "content") else str(response)
                )
            else:
                result = engine.generate(generation_history, model=model)
                content = (
                    result.get("content", "")
                    if isinstance(result, dict)
                    else str(result)
                )

            history.append(Message(role=Role.ASSISTANT, content=content))
            console.print()
            console.print(Markdown(content))
            console.print()
            if voice_mode:
                _speak(content, console)

            publish_completed_exchange(
                bus,
                user_input,
                content,
                source="cli.chat",
            )
        except KeyboardInterrupt:
            console.print("\n[dim]Generation interrupted.[/dim]")
        except Exception as exc:
            console.print(f"\n[red]Error: {exc}[/red]\n")

    if memory_service is not None:
        memory_service.stop()


__all__ = ["chat"]
