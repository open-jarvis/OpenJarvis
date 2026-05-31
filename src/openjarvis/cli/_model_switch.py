"""Resolve chat CLI model: per-command presets, ``-m smart``, ``default_model``."""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Optional

SMART_MODEL_TOKEN = "smart"
MAX_MODEL_ID_LEN = 512
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_model_id(raw: str) -> str:
    """Normalize a model id from CLI or TTY input (length + control chars)."""
    text = _CONTROL_CHARS.sub("", (raw or "").strip())
    if len(text) > MAX_MODEL_ID_LEN:
        text = text[:MAX_MODEL_ID_LEN]
    return text


_VARIANT_ATTR: dict[str, str] = {
    "chat": "model_chat",
    "short": "model_short",
    "long": "model_long",
    "code": "model_code",
}


def tty_wants_model_picker(cli_flag: bool) -> bool:
    """Show model picker on TTY unless skipped via env or ``--pick-model``."""
    if cli_flag:
        return True
    skip = (os.environ.get("JARVIS_SKIP_MODEL_PICK", "") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    return sys.stdin.isatty() and not skip


def variant_preset_model(config: Any, chat_variant: str) -> str:
    """Return ``[intelligence] model_<variant>`` if set, else ``\"\"``."""
    intel = getattr(config, "intelligence", None)
    if intel is None:
        return ""
    attr = _VARIANT_ATTR.get(chat_variant, "model_chat")
    raw = (getattr(intel, attr, None) or "").strip()
    return raw


def interactive_pick_model(console: Any, engine: Any) -> Optional[str]:
    """List engine models and read user choice. Returns ``None`` if cancelled."""
    models: list[str] = []
    try:
        models = list(engine.list_models())
    except Exception:
        models = []
    if not models:
        console.print(
            "[yellow]Engine did not return any models — cannot pick "
            "interactively.[/yellow]",
        )
        return None
    console.print("[bold]Available models[/bold] (number or exact id):")
    for i, mid in enumerate(models, 1):
        console.print(f"  {i:2}) [cyan]{mid}[/cyan]")
    try:
        raw = input(
            "Choose model [1–%d], id, or Enter for config default: " % len(models)
        )
    except (EOFError, KeyboardInterrupt):
        return None
    choice = (raw or "").strip()
    if not choice:
        return None
    choice = sanitize_model_id(choice)
    if not choice:
        return None
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(models):
            return models[idx - 1]
        return None
    if choice in models:
        return choice
    return None


def resolve_chat_cli_model(
    *,
    console: Any,
    config: Any,
    engine: Any,
    engine_name: str,
    cli_model: Optional[str],
    chat_variant: str,
) -> str:
    """Resolve model from ``-m``, ``smart`` / presets, or ``default_model``.

    Interactive picking is handled in ``chat`` before this runs.
    """
    explicit = sanitize_model_id(cli_model or "")
    if explicit and explicit.lower() != SMART_MODEL_TOKEN:
        return explicit

    preset = variant_preset_model(config, chat_variant)
    if preset:
        return preset

    dm = (getattr(config.intelligence, "default_model", None) or "").strip()
    if dm:
        return dm

    from openjarvis.engine import discover_engines, discover_models

    all_engines = discover_engines(config)
    all_models = discover_models(all_engines)
    engine_models = all_models.get(engine_name, [])
    if engine_models:
        return engine_models[0]

    return ""


__all__ = [
    "MAX_MODEL_ID_LEN",
    "SMART_MODEL_TOKEN",
    "interactive_pick_model",
    "resolve_chat_cli_model",
    "sanitize_model_id",
    "tty_wants_model_picker",
    "variant_preset_model",
]
