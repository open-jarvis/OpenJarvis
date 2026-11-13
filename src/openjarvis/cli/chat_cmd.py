"""``jarvis chat`` — interactive multi-turn chat REPL."""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Iterator, Sequence
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
    question: str,
    engine_kwargs: dict,
    config: Any,
) -> None:
    """Describe the screen with a vision-capable model (the ``/see`` command).

    Captures the primary screen, attaches it to a fresh user message and
    streams the model's description back (spoken sentence-by-sentence in
    voice mode). The vision model comes from ``JARVIS_VISION_MODEL``,
    ``intelligence.vision_model``, or falls back to the active chat model.
    """
    from openjarvis.tools.screen import capture_screen_b64

    vision_model = (
        os.environ.get("JARVIS_VISION_MODEL")
        or getattr(config.intelligence, "vision_model", "")
        or default_model
    )
    prompt = question.strip() or "Décris ce qui est affiché à l'écran."

    try:
        image_b64 = capture_screen_b64()
    except Exception as exc:
        console.print(
            f"[red]Screen capture failed: {_safe_rich_label(exc)}[/red]"
        )
        return

    console.print(
        f"[dim]Describing the screen with "
        f"{_safe_rich_label(vision_model)}…[/dim]"
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
                "  /see [question] — describe the screen (local vision)\n"
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
                    # Speak sentence-by-sentence while the model keeps
                    # generating, so the voice reply starts as soon as the
                    # first sentence is complete (instead of after the full
                    # answer).
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
                if not streamed_reply:
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


__all__ = ["chat"]
