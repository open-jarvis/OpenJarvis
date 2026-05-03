"""Cloud-key auto-detection and initial-config writing.

Used by both ``install.sh`` (via ``jarvis _bootstrap --write-config``)
and ``jarvis init`` (so there is a single source of truth for the
TOML rendered at install time).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

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
            f"env_var={self.env_var!r}, api_key='***redacted***')"
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
