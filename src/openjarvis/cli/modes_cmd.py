"""Tiered chat: ``short``, ``long`` (semantic hints), ``code`` (toolset)."""

from __future__ import annotations

from typing import Optional

import click

from openjarvis.cli.chat_cmd import run_chat_interactive

# Mirrors ``code-assistant`` preset; MCP stays in config ``tools.enabled``.
_CODE_DEFAULT_TOOLS = (
    "code_interpreter,file_read,file_write,shell_exec,web_search,think,calculator"
)

# Long mode: retrieval from indexed memory + web for fresh facts.
_LONG_DEFAULT_TOOLS = "web_search,memory_retrieve,think"

_CODE_EXTRA_SYSTEM = (
    "To inspect local files or list a directory without a confirmation prompt, use "
    "file_read (it lists top-level names when the path is a directory). shell_exec "
    "requires the user to approve each command; if they decline, that is not a "
    "filesystem permission error on the path. "
    "If qdrant-find is in your tools, use it only for collections the user already "
    "indexed — not for ad-hoc chat chunking."
)

_LONG_EXTRA_SYSTEM = (
    "Before answering about prior notes or project docs, call memory_retrieve. "
    "For current or external facts, call web_search. "
    "Index new corpora with ``jarvis memory index`` outside this session."
)


@click.command(
    "short",
    help=(
        "Interactive chat — session-scoped memory (same engine as ``chat``; "
        "default agent ``native_react`` when ``-a`` is omitted)."
    ),
)
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option(
    "-m",
    "--model",
    "model_name",
    default=None,
    help=(
        "Model id. Omit or ``smart`` for [intelligence] model_short, "
        "then default_model."
    ),
)
@click.option(
    "--pick-model",
    "pick_model",
    is_flag=True,
    default=False,
    help=(
        "Show the model list before chat (bare ``jarvis`` does this on a TTY unless "
        "JARVIS_SKIP_MODEL_PICK=1)."
    ),
)
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
@click.option("--tools", default=None, help="Comma-separated tool names.")
@click.option("--system", "system_prompt", default=None, help="Custom system prompt.")
def short(
    engine_key: Optional[str],
    model_name: Optional[str],
    pick_model: bool,
    agent_name: Optional[str],
    tools: Optional[str],
    system_prompt: Optional[str],
) -> None:
    run_chat_interactive(
        engine_key,
        model_name,
        agent_name,
        tools,
        system_prompt,
        default_agent_when_unset="native_react",
        default_tools_when_unset=None,
        extra_system_prompt=None,
        session_title="OpenJarvis · short",
        chat_variant="short",
        pick_model=pick_model,
    )


@click.command(
    "long",
    help=(
        "Interactive chat — indexed memory retrieval + web search (default "
        "``orchestrator``; merges config ``tools.enabled`` and MCP)."
    ),
)
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option(
    "-m",
    "--model",
    "model_name",
    default=None,
    help=(
        "Model id. Omit or ``smart`` for [intelligence] model_long, "
        "then default_model."
    ),
)
@click.option(
    "--pick-model",
    "pick_model",
    is_flag=True,
    default=False,
    help=(
        "Show the model list before chat (bare ``jarvis`` does this on a TTY unless "
        "JARVIS_SKIP_MODEL_PICK=1)."
    ),
)
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
@click.option("--tools", default=None, help="Comma-separated tool names.")
@click.option("--system", "system_prompt", default=None, help="Custom system prompt.")
def long(
    engine_key: Optional[str],
    model_name: Optional[str],
    pick_model: bool,
    agent_name: Optional[str],
    tools: Optional[str],
    system_prompt: Optional[str],
) -> None:
    run_chat_interactive(
        engine_key,
        model_name,
        agent_name,
        tools,
        system_prompt,
        default_agent_when_unset="orchestrator",
        default_tools_when_unset=_LONG_DEFAULT_TOOLS,
        extra_system_prompt=_LONG_EXTRA_SYSTEM,
        session_title="OpenJarvis · long",
        chat_variant="long",
        pick_model=pick_model,
    )


@click.command(
    "code",
    help=(
        "Interactive chat — code-oriented default tools (code-assistant strip); "
        "override with ``--tools``. Default agent ``orchestrator``."
    ),
)
@click.option("-e", "--engine", "engine_key", default=None, help="Engine backend.")
@click.option(
    "-m",
    "--model",
    "model_name",
    default=None,
    help=(
        "Model id. Omit or ``smart`` for [intelligence] model_code, "
        "then default_model."
    ),
)
@click.option(
    "--pick-model",
    "pick_model",
    is_flag=True,
    default=False,
    help=(
        "Show the model list before chat (bare ``jarvis`` does this on a TTY unless "
        "JARVIS_SKIP_MODEL_PICK=1)."
    ),
)
@click.option("-a", "--agent", "agent_name", default=None, help="Agent type.")
@click.option("--tools", default=None, help="Comma-separated tool names.")
@click.option("--system", "system_prompt", default=None, help="Custom system prompt.")
def code(
    engine_key: Optional[str],
    model_name: Optional[str],
    pick_model: bool,
    agent_name: Optional[str],
    tools: Optional[str],
    system_prompt: Optional[str],
) -> None:
    run_chat_interactive(
        engine_key,
        model_name,
        agent_name,
        tools,
        system_prompt,
        default_agent_when_unset="orchestrator",
        default_tools_when_unset=_CODE_DEFAULT_TOOLS,
        extra_system_prompt=_CODE_EXTRA_SYSTEM,
        session_title="OpenJarvis · code",
        chat_variant="code",
        pick_model=pick_model,
    )


__all__ = ["short", "long", "code"]
