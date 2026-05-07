"""Centralized env-var registry, fallback-chain reader, and alias pass.

Why this exists
---------------
1. Several Railway service variables use non-canonical casing — notably
   ``OpenAI_API`` (the OpenAI SDK reads ``OPENAI_API_KEY`` only) and
   ``Bridge_Zbigmodel_api`` (already handled ad-hoc in ``cloud.py``).
   :func:`apply_aliases` runs once at module import and copies aliased
   values into their canonical names so downstream code using raw
   ``os.environ.get`` keeps working without per-call-site changes.
2. :func:`get_env` is a shared fallback-chain reader for new call sites
   (mirrors the existing ``cloud.py:_first_env`` pattern but exposed as
   a public utility).
3. :data:`ENV_REGISTRY` is the single source of truth used by the
   ``/v1/integrations/status`` endpoint to render per-integration health
   in the frontend.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True, slots=True)
class EnvSpec:
    """Metadata for a known environment variable."""

    name: str
    aliases: tuple[str, ...] = ()
    purpose: str = ""
    integration: str = ""
    secret: bool = True


ENV_REGISTRY: dict[str, EnvSpec] = {
    # ----- Cloud providers (the engine and cloud_router read these
    # directly via os.environ — apply_aliases ensures non-canonical
    # casings populate the canonical names). -------------------------
    "OPENAI_API_KEY": EnvSpec(
        "OPENAI_API_KEY",
        ("OpenAI_API", "OPENAI_API"),
        "OpenAI Chat Completions API key",
        "openai",
    ),
    "ANTHROPIC_API_KEY": EnvSpec(
        "ANTHROPIC_API_KEY",
        (),
        "Anthropic Messages API key (direct, non-OpenRouter)",
        "anthropic",
    ),
    "ANTHROPIC_EMAIL": EnvSpec(
        "ANTHROPIC_EMAIL",
        (),
        "Email associated with the Anthropic account "
        "(used as identity metadata for login flows)",
        "anthropic",
        secret=False,
    ),
    "DEEPSEEK_API_KEY": EnvSpec(
        "DEEPSEEK_API_KEY",
        (),
        "DeepSeek chat/reasoner API key",
        "deepseek",
    ),
    # ----- Integrations --------------------------------------------
    "RAILWAY_TOKEN": EnvSpec(
        "RAILWAY_TOKEN",
        (),
        "Railway GraphQL API token (project/team-scoped)",
        "railway",
    ),
    "N8N_API_KEY": EnvSpec(
        "N8N_API_KEY",
        (),
        "n8n REST API key",
        "n8n",
    ),
    "N8N_BASE_URL": EnvSpec(
        "N8N_BASE_URL",
        (),
        "Base URL of the n8n instance "
        "(e.g. http://n8n.railway.internal:5678)",
        "n8n",
        secret=False,
    ),
    "SMTP_USER": EnvSpec(
        "SMTP_USER",
        (),
        "SMTP username/email",
        "email",
        secret=False,
    ),
    "SMTP_PASSWORD": EnvSpec(
        "SMTP_PASSWORD",
        (),
        "SMTP password or app-specific password",
        "email",
    ),
    "V0_API_KEY": EnvSpec(
        "V0_API_KEY",
        (),
        "V0 / Vercel UI generation API key",
        "v0",
    ),
    "GITHUB_PAT": EnvSpec(
        "GITHUB_PAT",
        ("GITHUB_TOKEN",),
        "GitHub personal access token (PAT) — falls back to GITHUB_TOKEN",
        "github",
    ),
    "CLOUDINARY_API_KEY": EnvSpec(
        "CLOUDINARY_API_KEY",
        (),
        "Cloudinary API key",
        "cloudinary",
    ),
    "CLOUDINARY_API_SECRET": EnvSpec(
        "CLOUDINARY_API_SECRET",
        (),
        "Cloudinary API secret",
        "cloudinary",
    ),
    "CLOUDINARY_CLOUD_NAME": EnvSpec(
        "CLOUDINARY_CLOUD_NAME",
        (),
        "Cloudinary cloud name (account identifier)",
        "cloudinary",
        secret=False,
    ),
    "DATABASE_URL": EnvSpec(
        "DATABASE_URL",
        (),
        "Postgres DSN (consumed by the elaboration store mirror)",
        "postgres",
    ),
    "OBSIDIAN_VAULT_URL": EnvSpec(
        "OBSIDIAN_VAULT_URL",
        (),
        "Base URL of the obsidian-vault MCP service "
        "(default http://obsidian-vault.railway.internal:22360)",
        "obsidian",
        secret=False,
    ),
}


def get_env(*aliases: str, default: Optional[str] = None) -> Optional[str]:
    """Return the first non-empty ``os.environ`` value across ``aliases``.

    Case-sensitive: each alias is tried verbatim. For case-insensitive
    fallback, include the case variants explicitly.
    """
    for name in aliases:
        v = os.environ.get(name)
        if v:
            return v
    return default


def apply_aliases() -> list[str]:
    """Copy aliased values into their canonical env-var names if missing.

    Idempotent. Returns the list of canonical names that were populated
    from an alias.

    Runs once at module import (see ``openjarvis/core/__init__.py``) so
    that downstream code using raw ``os.environ.get(canonical)`` — and
    third-party SDKs like ``openai.OpenAI()`` that read
    ``OPENAI_API_KEY`` directly — work without modification when the
    user only set the alias.
    """
    populated: list[str] = []
    for spec in ENV_REGISTRY.values():
        if os.environ.get(spec.name):
            continue
        for alias in spec.aliases:
            v = os.environ.get(alias)
            if v:
                os.environ[spec.name] = v
                populated.append(spec.name)
                break
    return populated


def is_configured(canonical: str) -> bool:
    """Return True if env var (or any of its aliases) is set non-empty."""
    spec = ENV_REGISTRY.get(canonical)
    if spec is None:
        return bool(os.environ.get(canonical))
    return bool(get_env(spec.name, *spec.aliases))


__all__ = [
    "ENV_REGISTRY",
    "EnvSpec",
    "apply_aliases",
    "get_env",
    "is_configured",
]
