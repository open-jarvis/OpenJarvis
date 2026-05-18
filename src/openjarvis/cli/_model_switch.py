"""Resolve chat CLI model: per-command presets, ``-m smart``, ``default_model``."""

from __future__ import annotations

from typing import Any, Optional

SMART_MODEL_TOKEN = "smart"

_VARIANT_ATTR: dict[str, str] = {
    "chat": "model_chat",
    "short": "model_short",
    "long": "model_long",
    "code": "model_code",
}


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
    if choice.isdigit():
        idx = int(choice)
        if 1 <= idx <= len(models):
            return models[idx - 1]
        return None
    for mid in models:
        if mid == choice or choice in mid:
            return mid
    return choice


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

    Interactive picking is handled in ``run_chat_interactive`` before this runs.
    """
    explicit = (cli_model or "").strip()
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
    "SMART_MODEL_TOKEN",
    "interactive_pick_model",
    "resolve_chat_cli_model",
    "variant_preset_model",
]
