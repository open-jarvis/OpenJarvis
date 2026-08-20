"""Cloud-key auto-detection and initial-config writing.

Used by both ``install.sh`` (via ``jarvis _bootstrap --write-config``)
and ``jarvis init`` (so there is a single source of truth for the
TOML rendered at install time).
"""

from __future__ import annotations

import datetime as _dt
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import click

import openjarvis
from openjarvis.core import config as _cfg
from openjarvis.core.config import (
    HardwareInfo,
    detect_hardware,
    recommend_engine,
    recommend_model,
)

# Marker used to redact secret values in __repr__.
_REDACTED_PLACEHOLDER = "***redacted***"

# Precedence order matters: first match wins.
# OpenRouter first because one key unlocks the most models; Anthropic
# next because it's the highest-quality single-provider option; then
# OpenAI; then Google (with GEMINI_API_KEY as an alias).
_KEY_TO_PROVIDER: tuple[tuple[str, str], ...] = (
    ("OPENROUTER_API_KEY", "openrouter"),
    ("ANTHROPIC_API_KEY", "anthropic"),
    ("OPENAI_API_KEY", "openai"),
    ("GOOGLE_API_KEY", "google"),
    ("GEMINI_API_KEY", "google"),
)


@dataclass(slots=True)
class CloudProvider:
    """A detected cloud provider + the env var it came from."""

    provider: str
    env_var: str
    api_key: str

    def __repr__(self) -> str:
        return (
            f"CloudProvider(provider={self.provider!r}, "
            f"env_var={self.env_var!r}, api_key='{_REDACTED_PLACEHOLDER}')"
        )


def detect_cloud_keys() -> Optional[CloudProvider]:
    """Return the first matching cloud provider per precedence order, else None.

    Empty-string values are treated as unset (matches shell convention).
    """
    for env_var, provider in _KEY_TO_PROVIDER:
        value = os.environ.get(env_var, "")
        if value:
            return CloudProvider(provider=provider, env_var=env_var, api_key=value)
    return None


# ---------------------------------------------------------------------------
# Initial config writer
# ---------------------------------------------------------------------------

_DEFAULT_SOUL = "# Agent Persona\n\nYou are Jarvis, a helpful personal AI assistant.\n"
_DEFAULT_MEMORY = "# Agent Memory\n\n"
_DEFAULT_USER = "# User Profile\n\n"


def _toml_quote(value: str) -> str:
    """Escape a runtime value for use inside TOML "..." double-quoted string.

    Per TOML spec: backslash and double-quote must be backslash-escaped in
    basic strings.  Other control chars are not common in our values, so we
    don't escape them — keeping this helper minimal.
    """
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _installer_version() -> str:
    return openjarvis.__version__


def _render_provenance_lines() -> str:
    return (
        f"installed_at = {_toml_quote(_now_iso())}\n"
        f"installer_version = {_toml_quote(_installer_version())}\n"
    )


def write_initial_config(
    *,
    hardware: HardwareInfo,
    engine: str,
    model: str,
    cloud: Optional[CloudProvider] = None,
) -> Path:
    """Render the initial ``config.toml`` and seed memory files.

    Called by both ``install.sh`` (via ``jarvis _bootstrap --write-config``)
    and ``jarvis init`` so the TOML format has one definition.
    """
    _cfg.DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    gpu_comment = ""
    if hardware.gpu:
        mem_label = "unified memory" if hardware.gpu.vendor == "apple" else "VRAM"
        gpu_comment = (
            f"\n# GPU: {hardware.gpu.name} ({hardware.gpu.vram_gb} GB {mem_label})"
        )

    intelligence_section = f"default_model = {_toml_quote(model)}"
    if cloud is not None:
        intelligence_section += f"\nprovider = {_toml_quote(cloud.provider)}"

    # Provenance must come before table declarations to be top-level keys.
    provenance = _render_provenance_lines().rstrip("\n")

    hardware_line = (
        f"# Hardware: {hardware.cpu_brand} "
        f"({hardware.cpu_count} cores, {hardware.ram_gb} GB RAM)"
    )

    base_toml = (
        f"# OpenJarvis configuration\n"
        f"{hardware_line}{gpu_comment}\n"
        f"# Full reference config: jarvis init --full\n"
        f"\n"
        f"{provenance}\n"
        f"\n"
        f"[engine]\n"
        f"default = {_toml_quote(engine)}\n"
        f"\n"
        f"[engine.{engine}]\n"
        f"# host = "
        f'"http://localhost:11434"  '
        f"# set to remote URL if engine runs elsewhere\n"
        f"\n"
        f"[intelligence]\n"
        f"{intelligence_section}\n"
        f"\n"
        f"[agent]\n"
        f'default_agent = "simple"\n'
        f"\n"
        f"[tools]\n"
        f'enabled = ["code_interpreter", "web_search", '
        f'"file_read", "shell_exec"]\n'
    )

    _cfg.DEFAULT_CONFIG_PATH.write_text(base_toml)

    _seed_memory_files()

    return _cfg.DEFAULT_CONFIG_PATH


def _seed_memory_files() -> None:
    """Create SOUL.md / MEMORY.md / USER.md / skills/ if absent."""
    home = _cfg.DEFAULT_CONFIG_DIR
    if not (home / "SOUL.md").exists():
        (home / "SOUL.md").write_text(_DEFAULT_SOUL)
    if not (home / "MEMORY.md").exists():
        (home / "MEMORY.md").write_text(_DEFAULT_MEMORY)
    if not (home / "USER.md").exists():
        (home / "USER.md").write_text(_DEFAULT_USER)
    (home / "skills").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# CLI command — invoked by install.sh, hidden from `jarvis --help`
# ---------------------------------------------------------------------------

# Default model picked at install time when a cloud key is detected via
# --prefer-cloud-when-available.  These IDs will rot as new model versions
# ship; bump them when sub-project A's release notes track new defaults.
_CLOUD_PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "openrouter": "anthropic/claude-opus-4-6",
    "anthropic": "claude-opus-4-6",
    "openai": "gpt-5",
    "google": "gemini-3-pro",
}


@click.command("_bootstrap", hidden=True)
@click.option(
    "--write-config",
    is_flag=True,
    default=False,
    help="Render config.toml from detected hardware + provided engine/model.",
)
@click.option(
    "--engine",
    default="",
    help="Inference engine slug (e.g. ollama). Empty = auto-recommend.",
)
@click.option(
    "--model",
    default="",
    help="Model id (e.g. qwen3.5:2b). Empty = auto-recommend.",
)
@click.option(
    "--prefer-cloud-when-available",
    is_flag=True,
    default=False,
    help="If a known cloud-API key is in env, override engine/model to cloud.",
)
def bootstrap_cmd(
    write_config: bool,
    engine: str,
    model: str,
    prefer_cloud_when_available: bool,
) -> None:
    """Internal helper used by install.sh — not for direct user invocation."""
    if not write_config:
        raise click.UsageError("--write-config is required")

    hw = detect_hardware()
    chosen_engine = engine or recommend_engine(hw)
    chosen_model = model or recommend_model(hw, chosen_engine)

    cloud = None
    if prefer_cloud_when_available:
        cloud = detect_cloud_keys()
        if cloud is not None:
            chosen_engine = "cloud"
            chosen_model = _CLOUD_PROVIDER_DEFAULT_MODELS.get(
                cloud.provider, chosen_model
            )

    write_initial_config(
        hardware=hw,
        engine=chosen_engine,
        model=chosen_model,
        cloud=cloud,
    )
    click.echo(f"Wrote {_cfg.DEFAULT_CONFIG_PATH}")
