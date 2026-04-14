"""
Lokales Secret-Loading fuer Clark/Jarvis.

Die Datei liest bevorzugt Umgebungsvariablen und faellt dann auf lokale,
nicht versionierte Dateien im Benutzerprofil zurueck.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

SECRET_FILE = Path.home() / ".openjarvis" / "clark_secrets.toml"
CONFIG_FILE = Path.home() / ".openjarvis" / "config.toml"

_secret_cache: dict[str, Any] | None = None
_config_cache: dict[str, Any] | None = None


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}


def _deep_get(data: dict[str, Any], path: tuple[str, ...]) -> str | None:
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    if current is None:
        return None
    value = str(current).strip()
    return value or None


def _secrets() -> dict[str, Any]:
    global _secret_cache
    if _secret_cache is None:
        _secret_cache = _load_toml(SECRET_FILE)
    return _secret_cache


def _config() -> dict[str, Any]:
    global _config_cache
    if _config_cache is None:
        _config_cache = _load_toml(CONFIG_FILE)
    return _config_cache


def load_secret(
    secret_name: str,
    *,
    env_names: tuple[str, ...] = (),
    config_path: tuple[str, ...] = (),
    default: str | None = None,
) -> str | None:
    for env_name in env_names:
        value = os.getenv(env_name, "").strip()
        if value:
            return value

    secret_value = _deep_get(_secrets(), ("keys", secret_name))
    if secret_value:
        return secret_value

    if config_path:
        config_value = _deep_get(_config(), config_path)
        if config_value:
            return config_value

    return default
