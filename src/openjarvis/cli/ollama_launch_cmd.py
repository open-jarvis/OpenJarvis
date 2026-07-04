from __future__ import annotations

import json
import os
import sys
import traceback
import typing
from typing import Dict, Optional, Tuple

import click

from openjarvis.core.types import Message, Role
from openjarvis.core.config import load_config
from openjarvis.engine import discover_engines
from openjarvis.engine.ollama import OllamaEngine
from openjarvis.engine.ollama_model_usage import OllamaModelUsageStore

LOGGER = __import__("logging").getLogger(__name__)

_OLLAMA_TASK_FIT = {
    "chat": ("qwen2.5-coder:7b-instruct-q4_K_M", "qwen3.6:27b", "gemma4:latest"),
    "research": ("gemma4:latest", "qwen3.6:27b", "qwen2.5-coder:7b-instruct-q4_K_M"),
    "code": ("qwen2.5-coder:7b-instruct-q4_K_M", "qwen3.6:27b", "gemma4:latest"),
    "embed": ("nomic-embed-text", "qwen3.6:27b", "gemma4:latest"),
    "vision": ("gemma4:latest", "qwen3.6:27b", "qwen2.5-coder:7b-instruct-q4_K_M"),
    "kingwen": ("gemma4:latest", "qwen3.6:27b", "qwen2.5-coder:7b-instruct-q4_K_M"),
    "default": ("qwen3.6:27b", "gemma4:latest", "qwen2.5-coder:7b-instruct-q4_K_M"),
}

_SUPPORTED_INTEGRATIONS = (
    "claude",
    "codex",
    "droid",
    "opencode",
    "openclaw",
    "vscode",
    "pi",
    "jarvis",
)
_ALIAS_MAP = {"clawdbot": "openclaw"}

_DEFAULT_CONTEXT = "64K tokens"
_BASE_URL = "http://localhost:11434"
_CLOUD_BASE_URL = "https://ollama.com/api"

_ENV_BY_INTEGRATION: Dict[str, Dict[str, str]] = {
    "claude": {
        "ANTHROPIC_BASE_URL": "http://localhost:11434",
        "ANTHROPIC_AUTH_TOKEN": "ollama",
    },
    "codex": {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY": "ollama",
    },
    "droid": {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY": "ollama",
    },
    "opencode": {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY": "ollama",
    },
    "openclaw": {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY": "ollama",
    },
    "vscode": {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY": "ollama",
    },
    "pi": {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY": "ollama",
    },
    "jarvis": {
        "OPENAI_BASE_URL": "http://localhost:11434/v1",
        "OPENAI_API_KEY": "ollama",
        "OPENJARVIS_ENGINE__OLLAMA__HOST": "http://localhost:11434",
    },
}

_CONFIG_TEMPLATES: Dict[str, Dict[str, object]] = {
    "codex": {
        "path": "~/.codex/ollama-launch.config.toml",
        "content": (
            'model = "{model}"\n'
            'model_provider = "ollama-launch"\n'
            'model_catalog_json = "~/.codex/model.json"\n'
            '\n'
            '[model_providers."ollama-launch"]\n'
            'name = "Ollama"\n'
            'base_url = "http://localhost:11434/v1/"\n'
            'wire_api = "responses"\n'
        ),
    },
    "opencode": {
        "path": "~/.config/opencode/opencode.json",
        "content": json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "provider": {
                    "ollama": {
                        "npm": "@ai-sdk/openai-compatible",
                        "name": "Ollama",
                        "options": {"baseURL": "http://localhost:11434/v1"},
                        "models": {"__MODEL__": {"name": "__MODEL__"}},
                    }
                },
            },
            indent=2,
        )
        .replace("__MODEL__", "{model}")
        + "\n",
    },
}


def _resolve_integration(name: str) -> Optional[str]:
    key = name.strip().lower()
    return _ALIAS_MAP.get(key, key if key in _SUPPORTED_INTEGRATIONS else None)


def _resolve_model(*, requested: Optional[str]) -> str:
    if requested:
        requested = requested.strip()
    if requested:
        return requested

    config = load_config()
    engines = discover_engines(config)
    for engine_key, engine in engines:
        if engine_key == "ollama":
            models = engine.list_models()
            if models:
                return models[0]
    return "qwen3.5"


def _run(cmd: list[str], env: Optional[Dict[str, str]] = None) -> int:
    import subprocess

    try:
        proc = subprocess.run(cmd, env=env, check=False)
        return proc.returncode
    except FileNotFoundError:
        return 127


def _integration_help(name: str) -> str:
    capabilities = {
        "claude": "Chat, tool calling, file edits, subagents, vision, web search/fetch, thinking",
        "codex": "Chat, tool calling, subagents, persistent Ollama profile",
        "droid": "Chat, tool calling, file edits, subagents",
        "opencode": "Chat, tool calling, file edits, subagents, web fetch, vision",
        "openclaw": "Chat, messaging channels, web search, gateway daemon",
        "vscode": "Copilot Chat model picker, custom Ollama provider",
        "pi": "Chat, read/write/edit, bash, extensible skills",
        "jarvis": "Chat, agents, research, embeddings, channels, tools, King Wen oracle persona",
    }
    return capabilities.get(name, "Chat and tool calling")


def _supported_list() -> str:
    return ", ".join(_SUPPORTED_INTEGRATIONS)


def _task_fit_for_query(query: str) -> str:
    q = query.lower()
    if any(t in q for t in ["king wen", "hexagram", "oracle", "consult", "emotion", "reflection"]):
        return "kingwen"
    if any(t in q for t in ["code", "function", "typescript", "python", "sql", "rust", "regex", "refactor", "debug"]):
        return "code"
    if any(t in q for t in ["research", "paper", "arxiv", "search", "compare", "analysis", "evidence"]):
        return "research"
    if any(t in q for t in ["image", "vision", "ocr", "diagram", "screenshot", "picture"]):
        return "vision"
    if any(t in q for t in ["embed", "retrieval", "rag", "vector"]):
        return "embed"
    return "chat"


def _list_local_ollama_models(engine: Optional[OllamaEngine] = None) -> list[str]:
    if engine is None:
        engine = OllamaEngine()
    try:
        return engine.list_models()
    except Exception as exc:
        LOGGER.debug("Failed to list ollama models: %s", exc)
        return []


def _choose_model(available_models: list[str], task: str) -> str:
    chain = _OLLAMA_TASK_FIT.get(task, _OLLAMA_TASK_FIT["default"])
    exact = next((m for m in chain if m in available_models), None)
    if exact:
        return exact
    fallback = next(
        (m for m in available_models if not any(s in m for s in ["embed", "whisper", "audio"])),
        available_models[0] if available_models else "",
    )
    return fallback or ""


def _task_depth(query: str) -> str:
    """Return a depth class based on task demands, not just keyword matching."""
    q = query.lower()
    short_signals = any(t in q for t in ["ping", "status", "health", "one short", "one sentence", "tldr", "brief"])
    fast_tasks = any(t in q for t in ["chat", "code", "embed"])
    long_tasks = any(t in q for t in ["research", "paper", "arxiv", "analysis", "long", "background", "summarize", "report"])

    if short_signals or fast_tasks and not long_tasks:
        return "fast"
    if long_tasks or any(t in q for t in ["research", "vision", "plan", "essay", "deep", "thought"]):
        return "slow"
    return "default"


def _pick_depth_model(available_models: list[str], task: str, depth_class: str) -> str:
    """Pick a model using observed return-time usage when possible."""
    try:
        store = OllamaModelUsageStore()
        if depth_class == "fast":
            prefix_order = ["qwen2.5-coder:7b-instruct-q4_K_M", "qwen3.6:27b", "gemma4:latest"]
        else:
            prefix_order = ["gemma4:latest", "qwen3.6:27b", "qwen2.5-coder:7b-instruct-q4_K_M"]
        ranked = [m for m in prefix_order if m in available_models]
        if ranked:
            return store.sorted_by_latency(ranked)[0]
    except Exception as exc:
        LOGGER.debug("Model usage routing failed: %s", exc)
    fallback = _choose_model(available_models, task)
    if not fallback and available_models:
        return available_models[0]
    return fallback or ""


@click.group(
    "ollama launch",
    invoke_without_command=False,
)
@click.pass_context
def launch_group(ctx: click.Context) -> None:
    """Launch local coding integrations against Ollama."""


@launch_group.command("run-query")
@click.argument("query", required=False)
@click.option("--task", "task_type", default=None, help="Task type override: chat, code, research, vision, embed, kingwen.")
@click.option("--model", "model_override", default=None, help="Explicit model override.")
@click.option("--max-tokens", default=512, type=int, show_default=True, help="Max completion tokens.")
@click.option("--temperature", default=0.15, type=float, show_default=True, help="Sampling temperature.")
def run_query(
    query: Optional[str],
    task_type: Optional[str],
    model_override: Optional[str],
    max_tokens: int,
    temperature: float,
) -> None:
    """Run a query through the local Ollama provider with ModelRolodex-style task routing."""
    query_text = (query or "").strip()
    if not query_text:
        click.echo("Provide a query: jarvis ollama run-query \"your query\"")
        sys.exit(1)

    task = task_type or _task_fit_for_query(query_text)
    engine = OllamaEngine()
    available_models = _list_local_ollama_models(engine)
    if not available_models:
        click.echo("No local Ollama models available.")
        sys.exit(1)

    model = model_override or _choose_model(available_models, task)
    click.echo(f"Task: {task}")
    click.echo(f"Model: {model}")

    messages = [
        Message(role=Role.SYSTEM, content="You are a concise, direct assistant. Do not fabricate. Return only what was requested."),
        Message(role=Role.USER, content=query_text),
    ]
    payload = {
        "model": model,
        "stream": False,
        "options": {"num_ctx": 16384, "num_predict": max_tokens, "temperature": temperature},
        "think": False,
    }

    try:
        result = engine.generate(messages, **payload)
    except Exception as exc:
        click.echo(f"Query failed: {exc}")
        sys.exit(1)

    click.echo(json.dumps({
        "status": "ok",
        "task": task,
        "model": model,
        "ollamaReportedModel": result.get("model"),
        "content": result.get("content", ""),
        "usage": result.get("usage", {}),
        "engine_timing": result.get("engine_timing", {}),
    }, indent=2))


@launch_group.command("launch")
@click.argument("integration", required=False)
@click.option("--model", "model_override", default=None, help="Model to use.")
@click.option(
    "--yes",
    "yes_mode",
    is_flag=True,
    help="Non-interactive mode. Requires --model.",
)
@click.option(
    "--config",
    "config_only",
    is_flag=True,
    help="Write integration config without launching.",
)
@click.option(
    "--restore",
    "restore_mode",
    is_flag=True,
    help="Remove Ollama launch profile where supported.",
)
@click.argument("passthrough", nargs=-1, type=click.UNPROCESSED)
def launch_integration(
    integration: Optional[str],
    model_override: Optional[str],
    yes_mode: bool,
    config_only: bool,
    restore_mode: bool,
    passthrough: Tuple[str, ...],
) -> None:
    """Launch an AI coding integration against local Ollama.

    Examples:

        ollama launch claude

        ollama launch codex --model gpt-oss:120b

        ollama launch openclaw --model kimi-k2.5:cloud --yes
    """
    if restore_mode and (integration or "").strip().lower() not in {"codex", ""}:
        click.echo("Restore/remove profile is only supported for Codex in this wrapper.")
        sys.exit(1)

    target = _resolve_integration(integration or "")
    if target is None:
        if not integration:
            click.echo("Choose an integration: " + _supported_list())
        else:
            click.echo(f"Unsupported integration: {integration}")
        sys.exit(1)

    if yes_mode and not model_override:
        click.echo("--yes requires --model.")
        sys.exit(1)

    model = _resolve_model(requested=model_override)
    click.echo(f"Integration: {target}")
    click.echo(f"Model: {model}")
    click.echo(f"Capabilities: {_integration_help(target)}")

    if config_only:
        _write_config(target, model)
        sys.exit(0)

    if restore_mode:
        click.echo("No-op: Codex profile restore/removal is handled by the codex command in this wrapper.")
        sys.exit(0)

    if not yes_mode and model_override is None:
        if not click.confirm("Launch with recommended model settings?", default=True):
            click.echo("Aborted.")
            sys.exit(0)

    env = dict(os.environ)
    env.update(_ENV_BY_INTEGRATION.get(target, {}))
    if model:
        env.setdefault("OLLAMA_MODEL", model)

    cmd = [target, *(list(passthrough))]
    click.echo(f"Launching: {' '.join(cmd)}")
    sys.exit(_run(cmd, env=env))


@launch_group.command("codex", context_settings=dict(ignore_unknown_options=True))
@click.option("--config", "config_only", is_flag=True, help="Configure Codex without launching.")
@click.option("--restore", "restore_mode", is_flag=True, help="Remove Codex Ollama launch profile.")
@click.option("--model", "model_override", default=None, help="Model to use.")
@click.argument("passthrough", nargs=-1, type=click.UNPROCESSED)
def codex_launch(
    ctx: click.Context,
    config_only: bool,
    restore_mode: bool,
    model_override: Optional[str],
    passthrough: Tuple[str, ...],
) -> None:
    """Codex integration entry point."""
    if restore_mode:
        click.echo("Removing Codex Ollama launch profile is a no-op in this wrapper.")
        sys.exit(0)
    launch_integration.callback(
        integration="codex",
        model_override=model_override,
        yes_mode=False,
        config_only=config_only,
        restore_mode=False,
        passthrough=passthrough,
    )


@launch_group.command("opencode", context_settings=dict(ignore_unknown_options=True))
@click.option("--config", "config_only", is_flag=True, help="Configure OpenCode without launching.")
@click.option("--model", "model_override", default=None, help="Model to use.")
@click.argument("passthrough", nargs=-1, type=click.UNPROCESSED)
def opencode_launch(
    ctx: click.Context,
    config_only: bool,
    restore_mode: bool,
    model_override: Optional[str],
    passthrough: Tuple[str, ...],
) -> None:
    """OpenCode integration entry point."""
    launch_integration.callback(
        integration="opencode",
        model_override=model_override,
        yes_mode=False,
        config_only=config_only,
        restore_mode=False,
        passthrough=passthrough,
    )


def _write_config(target: str, model: str) -> None:
    payload = {
        "integration": target,
        "model": model,
        "base_url": _BASE_URL,
        "cloud_base_url": _CLOUD_BASE_URL,
        "context_requirement": _DEFAULT_CONTEXT,
        "env": _ENV_BY_INTEGRATION.get(target, {}),
    }
    template = _CONFIG_TEMPLATES.get(target)
    if template:
        path = typing.cast(str, template["path"]).replace("~", os.path.expanduser("~"))
        content = typing.cast(str, template["content"]).replace("{model}", model)
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(content)
            click.echo(f"Config written: {path}")
        except OSError as exc:
            click.echo(f"Config write failed: {exc}")
    click.echo(json.dumps(payload, indent=2))


__all__ = ["launch_group"]
