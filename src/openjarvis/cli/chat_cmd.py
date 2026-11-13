"""``jarvis chat`` — interactive multi-turn chat REPL."""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, List, Optional

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape

from openjarvis.cli._runtime_panel import runtime_cli_options
from openjarvis.cli._tool_names import resolve_tool_names
from openjarvis.cli._voice_chat import (
    SOURCE_TYPED,
    VOICE_EXIT,
    SentenceSpeaker,
    VoiceSession,
    _env_flag,
    read_voice_input,
    speak,
)
from openjarvis.core.config import load_config
from openjarvis.core.events import EventBus
from openjarvis.core.types import Message, Role
from openjarvis.memory import publish_completed_exchange

logger = logging.getLogger(__name__)


def _safe_rich_label(value: object) -> str:
    """Strip terminal controls and escape Rich markup in dynamic labels."""
    from openjarvis.cli._model_switch import sanitize_model_id

    return escape(sanitize_model_id(str(value)))


def _read_input(prompt: str = "You> ") -> Optional[str]:
    """Read user input with graceful EOF handling."""
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _stream_reply_tokens(
    engine: Any,
    messages: Sequence[Message],
    *,
    model: str,
    **engine_kwargs: Any,
) -> Iterator[str]:
    """Yield the assistant reply token by token, via the engine stream.

    Prefers the engine's synchronous token stream (``stream_sync``) so the
    first token arrives while the model is still generating — a faster
    perceived response than waiting for the full completion. Falls back to the
    blocking ``generate`` for engines without a native sync stream.
    """
    stream_sync = getattr(engine, "stream_sync", None)
    if stream_sync is None:
        result = engine.generate(messages, model=model, **engine_kwargs)
        content = (
            result.get("content", "") if isinstance(result, dict) else str(result)
        )
        if content:
            yield content
        return
    tokens = stream_sync(messages, model=model, **engine_kwargs)
    for token in tokens:
        if token:
            yield token


def _run_vision_reply(
    engine: Any,
    console: Console,
    voice_session: Optional[VoiceSession],
    default_model: str,
    spec: str,
    engine_kwargs: dict,
    config: Any,
) -> None:
    """Describe the screen / webcam / image file (the ``/see`` command).

    ``spec`` selects the source: empty = screen, ``cam`` = webcam,
    ``save[:path]`` = save the screenshot to a file, anything else = an image
    file path. The captured image is attached to a fresh user message and the
    model's description is streamed back (spoken sentence-by-sentence in
    voice mode).
    """
    from openjarvis.tools.screen import (
        capture_screen_b64,
        capture_webcam_b64,
        image_file_b64,
        save_screen,
    )

    spec = spec.strip()
    if spec.startswith("save"):
        path_arg = spec[len("save") :].strip().lstrip(":").strip()
        try:
            saved = save_screen(path_arg or None)
        except Exception as exc:
            console.print(
                f"[red]Screen capture failed: {_safe_rich_label(exc)}[/red]"
            )
            return
        console.print(f"[dim]Screenshot saved to {saved}[/dim]")
        return

    try:
        if not spec:
            image_b64 = capture_screen_b64()
            prompt = "Décris ce qui est affiché à l'écran."
        elif spec == "cam":
            image_b64 = capture_webcam_b64()
            prompt = "Décris ce que la webcam voit."
        else:
            image_b64 = image_file_b64(spec)
            prompt = "Décris cette image."
    except Exception as exc:
        console.print(
            f"[red]Vision capture failed: {_safe_rich_label(exc)}[/red]"
        )
        return

    vision_model = (
        os.environ.get("JARVIS_VISION_MODEL")
        or getattr(config.intelligence, "vision_model", "")
        or default_model
    )
    console.print(
        f"[dim]Describing with {_safe_rich_label(vision_model)}…[/dim]"
    )
    speaker: Optional[SentenceSpeaker] = None
    if voice_session is not None:
        speaker = SentenceSpeaker(voice_session, console)
    content = ""
    try:
        for token in _stream_reply_tokens(
            engine,
            [Message(role=Role.USER, content=prompt, images=[image_b64])],
            model=vision_model,
            **engine_kwargs,
        ):
            content += token
            console.print(token, end="", markup=False)
            if speaker is not None:
                speaker.feed(token)
        if speaker is not None:
            speaker.flush()
    except KeyboardInterrupt:
        console.print("\n[dim]Generation interrupted.[/dim]")
        return
    except Exception as exc:
        console.print(f"\n[red]Error: {exc}[/red]\n")
        return
    console.print()


def _handle_read(console: Console) -> None:
    """OCR the screen and print its text (the ``/read`` command)."""
    from openjarvis.tools.ocr import screen_text

    try:
        text = screen_text()
    except Exception as exc:
        console.print(f"[red]OCR failed: {_safe_rich_label(exc)}[/red]")
        return
    if not text:
        console.print("[dim]No text found on the screen.[/dim]")
        return
    console.print("[bold]Text on screen:[/bold]")
    console.print(text)


def _handle_speak(
    text: str,
    console: Console,
    voice_session: Optional[VoiceSession],
    config: Any,
) -> None:
    """Speak *text* aloud (the ``/speak`` command), even in muted voice mode."""
    if not text:
        console.print("[dim]Usage: /speak <text>[/dim]")
        return
    session = voice_session if voice_session is not None else VoiceSession(config)
    speak(text, console, session)


def _handle_shutup(
    console: Console,
    voice_session: Optional[VoiceSession],
) -> None:
    """Toggle spoken replies (the ``/shutup`` command)."""
    if voice_session is None:
        console.print("[dim]Voice mode is off — nothing to mute.[/dim]")
        return
    muted = voice_session.toggle_mute()
    console.print(
        f"[dim]Voice replies {'muted' if muted else 'unmuted'}.[/dim]"
    )


def _handle_voice(
    spec: str,
    console: Console,
    voice_session: Optional[VoiceSession],
) -> None:
    """Change the TTS voice/speed/backend mid-session (the ``/voice`` command)."""
    if voice_session is None:
        console.print(
            "[dim]Voice mode is off — start with --voice to control the "
            "voice.[/dim]"
        )
        return
    parts = spec.split()
    if not parts:
        console.print(
            "[dim]Usage: /voice <voice_id> | /voice speed <float> | "
            "/voice backend <id>[/dim]"
        )
        return
    kwargs: dict = {}
    if parts[0] == "speed" and len(parts) > 1:
        try:
            kwargs["speed"] = float(parts[1])
        except ValueError:
            console.print("[red]Invalid speed value.[/red]")
            return
    elif parts[0] == "backend" and len(parts) > 1:
        kwargs["backend"] = parts[1]
    else:
        kwargs["voice_id"] = parts[0]
    try:
        summary = voice_session.override_voice(**kwargs)
    except Exception as exc:
        console.print(
            f"[red]Could not change voice: {_safe_rich_label(exc)}[/red]"
        )
        return
    console.print(f"[dim]Voice updated — {summary}[/dim]")


def _transcript_path(config: Any) -> Path:
    """Return the file path for a new session transcript."""
    from openjarvis.core.paths import get_config_dir

    directory = get_config_dir() / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"chat_{time.strftime('%Y-%m-%d_%H%M%S')}.md"


def _save_transcript(
    history: Sequence[Message],
    config: Any,
) -> Optional[Path]:
    """Save the conversation as Markdown; returns the path or ``None``.

    Best-effort: a full transcript of only system messages (nothing said) is
    skipped, and any write failure returns ``None`` without raising.
    """
    if not history or all(msg.role == Role.SYSTEM for msg in history):
        return None
    try:
        path = _transcript_path(config)
        lines = [
            f"# OpenJarvis chat — {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]
        for msg in history:
            role_str = msg.role if isinstance(msg.role, str) else msg.role.value
            lines.append(f"## {role_str.upper()}")
            lines.append(str(msg.content))
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
    except Exception as exc:
        logger.debug("Failed to save session transcript: %s", exc)
        return None


def _handle_save(
    history: Sequence[Message],
    console: Console,
    config: Any,
) -> None:
    """Write the current conversation to a Markdown file (``/save``)."""
    path = _save_transcript(history, config)
    if path is None:
        console.print("[dim]Nothing to save yet.[/dim]")
        return
    console.print(f"[dim]Session saved to {path}[/dim]")


def _summarize_session(
    engine: Any,
    history: Sequence[Message],
    model: str,
    engine_kwargs: dict,
) -> str:
    """Summarize the conversation into durable third-person facts."""
    turns = [msg for msg in history if msg.role != Role.SYSTEM][-20:]
    transcript = "\n".join(
        f"{'Vous' if msg.role == Role.USER else 'Jarvis'}: "
        f"{str(msg.content)[:500]}"
        for msg in turns
    )
    prompt = (
        "Résume cette conversation en 2 ou 3 phrases factuelles, à la "
        "troisième personne, sur l'utilisateur (ses préférences, projets, "
        "décisions). Ne répète pas d'instructions.\n\n" + transcript
    )
    parts: List[str] = []
    for token in _stream_reply_tokens(
        engine,
        [Message(role=Role.USER, content=prompt)],
        model=model,
        **engine_kwargs,
    ):
        parts.append(token)
    return "".join(parts).strip()


def _store_summary_fact(
    text: str,
    memory_service: Any,
    config: Any,
) -> bool:
    """Persist a summarized fact, via the service or the on-disk store."""
    if memory_service is not None and hasattr(memory_service, "store_fact"):
        return bool(memory_service.store_fact(text, source="manual"))
    try:
        from openjarvis.memory.store import TRUST_AUTO, create_fact_store

        store = create_fact_store(
            getattr(config.memory, "backend", "local"),
            path=getattr(config.memory, "facts_path", None),
            max_facts=getattr(config.memory, "max_facts", 1000),
        )
        return bool(
            store.add_with_trust(text, source="manual", trust=TRUST_AUTO)
        )
    except Exception as exc:
        logger.debug("Failed to persist memory fact: %s", exc)
        return False


def _handle_remember(
    engine: Any,
    history: Sequence[Message],
    console: Console,
    config: Any,
    memory_service: Any,
    model: str,
    engine_kwargs: dict,
) -> None:
    """Summarize the conversation and store it in durable memory."""
    if not any(msg.role == Role.USER for msg in history):
        console.print("[dim]Nothing to remember yet.[/dim]")
        return
    try:
        summary = _summarize_session(engine, history, model, engine_kwargs)
    except Exception as exc:
        console.print(
            f"[red]Could not summarize: {_safe_rich_label(exc)}[/red]"
        )
        return
    if not summary:
        console.print("[dim]Nothing worth remembering.[/dim]")
        return
    if _store_summary_fact(summary, memory_service, config):
        console.print(f"[dim]Remembered: {summary}[/dim]")
    else:
        console.print("[yellow]Could not persist the memory fact.[/yellow]")


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
@runtime_cli_options
def chat(
    engine_key: str | None,
    model_name: str | None,
    pick_model: bool,
    agent_name: str | None,
    tools: str | None,
    system_prompt: str | None,
    persona_name: str | None,
    voice_mode: bool,
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
      /runtime      — Ollama context + GPU offload for this session
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

    if engine_name != "ollama" and (num_ctx is not None or num_gpu is not None):
        raise click.UsageError(
            "--num-ctx and --num-gpu are supported only with --engine ollama"
        )
    if engine_name == "ollama" and tty_wants_runtime_panel(skip_runtime_panel):
        runtime_opts = interactive_pick_runtime_options(
            console,
            engine_name=engine_name,
            cli_num_ctx=num_ctx,
            cli_num_gpu=num_gpu,
        )
    elif engine_name == "ollama" and (num_ctx is not None or num_gpu is not None):
        runtime_opts = ChatRuntimeOptions(num_ctx=num_ctx, num_gpu=num_gpu)
    else:
        runtime_opts = ChatRuntimeOptions()
    engine_kwargs = runtime_opts.to_engine_kwargs(engine_name=engine_name)

    # Interactive chat is a first-class tool execution path. Apply the same
    # configured engine guardrails, RBAC, rate limiting, and audit bus as ask,
    # serve, and the SDK before constructing any agent.
    from openjarvis.security import setup_security

    security = setup_security(config, engine, bus)
    engine = security.engine

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
                                    from openjarvis.tools._paths import file_tool_kwargs

                                    tool_instances.append(
                                        tcls(**file_tool_kwargs(tname, config))
                                    )
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

                from openjarvis.security.runtime import agent_security_kwargs

                kwargs.update(
                    agent_security_kwargs(
                        agent_cls,
                        capability_policy=security.capability_policy,
                        rate_limiter=security.rate_limiter,
                        agent_id=agent_key,
                    )
                )

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
                from openjarvis.security.runtime import wire_agent_security

                wire_agent_security(
                    agent,
                    bus=bus,
                    capability_policy=security.capability_policy,
                    rate_limiter=security.rate_limiter,
                    agent_id=agent_key,
                )
                if agent is not None and engine_kwargs:
                    # Agents like NativeReActAgent do not accept engine_options
                    # in __init__; session opts live on BaseAgent._engine_options.
                    setattr(agent, "_engine_options", dict(engine_kwargs))
        except Exception as exc:
            console.print(
                f"[yellow]Agent '{_safe_rich_label(agent_key)}' failed: "
                f"{escape(str(exc))}[/yellow]"
            )

    # Keep voice state outside the core chat path so picker/runtime changes can
    # be layered independently. Loaded speech models live for this session.
    voice_session = VoiceSession(config) if voice_mode else None

    # Print banner
    voice_hint = (
        "  [magenta]Voice mode ON[/magenta] — type normally, or press Enter "
        "to speak; silence stops recording.\n"
        if voice_mode
        else ""
    )
    console.print(
        f"[green bold]OpenJarvis Chat[/green bold]\n"
        f"  Engine: [cyan]{_safe_rich_label(engine_name)}[/cyan]  "
        f"Model: [cyan]{_safe_rich_label(model)}[/cyan]"
        f"  Agent: [cyan]{_safe_rich_label(agent_key or 'direct')}[/cyan]\n"
        f"  Runtime: [cyan]{runtime_opts.summary(engine_name=engine_name)}[/cyan]\n"
        f"{voice_hint}"
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

    # Semantic memory: rank facts by local embedding similarity (Ollama
    # /api/embed). Optional — built once per session, falls back to recency.
    semantic_ranker = None
    if getattr(config.memory, "semantic_enabled", False):
        try:
            from openjarvis.tools.storage.semantic import build_semantic_ranker

            semantic_ranker = build_semantic_ranker(config)
            if semantic_ranker is not None:
                console.print("[dim]  Memory: semantic recall ON[/dim]")
        except Exception as exc:
            logger.debug("Failed to build semantic ranker: %s", exc)

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

        source: str = SOURCE_TYPED
        if voice_mode:
            assert voice_session is not None
            result = read_voice_input(console, voice_session)
            if result is VOICE_EXIT:
                console.print("\n[dim]Goodbye![/dim]")
                break
            if result is None:
                continue  # nothing heard, loop again
            user_input, source = result
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
                f"Model: [cyan]{_safe_rich_label(model)}[/cyan]  "
                f"Engine: [cyan]{_safe_rich_label(engine_name)}[/cyan]"
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
                "  /runtime      — Ollama context + GPU offload for this session\n"
                "  /see [cam|file|save[:path]] — describe the screen / webcam / "
                "an image, or save a screenshot\n"
                "  /read         — OCR the text on the screen (Tesseract)\n"
                "  /speak <text> — read text aloud\n"
                "  /shutup       — mute/unmute spoken replies\n"
                "  /voice <id> | speed <x> | backend <id> — change the voice\n"
                "  /save         — save this conversation to a file\n"
                "  /remember     — summarize this conversation into memory\n"
                "  /history      — show conversation\n"
                "  /help         — this message"
            )
            continue
        elif cmd == "/see" or cmd.startswith("/see "):
            _run_vision_reply(
                engine,
                console,
                voice_session,
                model,
                user_input[len("/see") :].strip(),
                engine_kwargs,
                config,
            )
            continue
        elif cmd == "/read" or cmd.startswith("/read "):
            _handle_read(console)
            continue
        elif cmd.startswith("/speak"):
            _handle_speak(
                user_input[len("/speak") :].strip(),
                console,
                voice_session,
                config,
            )
            continue
        elif cmd == "/shutup":
            _handle_shutup(console, voice_session)
            continue
        elif cmd.startswith("/voice"):
            _handle_voice(user_input[len("/voice") :].strip(), console, voice_session)
            continue
        elif cmd == "/save":
            _handle_save(history, console, config)
            continue
        elif cmd == "/remember":
            _handle_remember(
                engine,
                history,
                console,
                config,
                memory_service,
                model,
                engine_kwargs,
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

        # Add user message (carries the utterance source for LLM comprehension)
        history.append(
            Message(role=Role.USER, content=user_input, metadata={"source": source})
        )

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
                    ranker=semantic_ranker,
                )
                if agent is not None:
                    if context_messages:
                        agent_context_message = context_messages[0]
                else:
                    generation_history = context_messages
            except Exception:
                logger.debug("Failed to inject memory context", exc_info=True)

        # Generate response even when optional memory context is unavailable.
        streamed_reply = False
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
                monitor: Any = None
                speaker: Optional[SentenceSpeaker] = None
                if voice_mode:
                    assert voice_session is not None
                    # Barge-in: watch the mic while Jarvis speaks so the user
                    # can interrupt the reply by starting to talk.
                    if _env_flag(
                        "JARVIS_BARGE_IN", getattr(config.speech, "barge_in", True)
                    ):
                        from openjarvis.speech.voice_io import BargeInMonitor

                        monitor = BargeInMonitor()
                        monitor.start()
                    if not voice_session.voice_muted:
                        # Speak sentence-by-sentence while the model keeps
                        # generating, so the voice reply starts as soon as the
                        # first sentence is complete (instead of after the
                        # full answer).
                        speaker = SentenceSpeaker(
                            voice_session,
                            console,
                            interrupt_check=monitor.consume if monitor else None,
                        )
                content = ""
                barge_interrupted = False
                try:
                    for token in _stream_reply_tokens(
                        engine,
                        generation_history,
                        model=model,
                        **engine_kwargs,
                    ):
                        content += token
                        # Stream the reply token by token so the user sees the
                        # answer start arriving immediately instead of waiting
                        # for the full completion.
                        console.print(token, end="", markup=False)
                        if speaker is not None:
                            speaker.feed(token)
                            if speaker.interrupted:
                                barge_interrupted = True
                                break
                    if speaker is not None and not barge_interrupted:
                        speaker.flush()
                finally:
                    if monitor is not None:
                        monitor.stop()
                if barge_interrupted:
                    console.print("\n[dim]Interrupted by speech.[/dim]")
                    continue
                streamed_reply = True

            history.append(Message(role=Role.ASSISTANT, content=content))
            if streamed_reply:
                # Tokens were already streamed to the terminal; just
                # terminate the line.
                console.print()
            else:
                console.print()
                console.print(Markdown(content))
                console.print()
            if voice_mode:
                assert voice_session is not None
                if not streamed_reply and not voice_session.voice_muted:
                    # Agent replies arrive whole — speak them in one go.
                    speak(content, console, voice_session)

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

    # Auto-save the session transcript (Markdown under <config-dir>/sessions/).
    # Disable with JARVIS_SAVE_SESSIONS=0; /save writes it on demand.
    if _env_flag("JARVIS_SAVE_SESSIONS", True):
        saved = _save_transcript(history, config)
        if saved is not None:
            console.print(f"[dim]Session saved to {saved}[/dim]")

    # Auto-summary → durable memory on exit (opt-in: JARVIS_REMEMBER_SESSION=1,
    # or use /remember on demand).
    if _env_flag("JARVIS_REMEMBER_SESSION", False):
        try:
            if any(msg.role == Role.USER for msg in history):
                console.print("[dim]Remembering session…[/dim]")
                _handle_remember(
                    engine,
                    history,
                    console,
                    config,
                    memory_service,
                    model,
                    engine_kwargs,
                )
        except Exception as exc:
            logger.debug("Auto-remember failed: %s", exc)


__all__ = ["chat"]
