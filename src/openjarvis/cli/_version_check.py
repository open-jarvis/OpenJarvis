"""Check for newer OpenJarvis releases on GitHub."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_CACHE_PATH = Path("~/.openjarvis/version-check.json").expanduser()
_CONFIG_PATH = Path("~/.openjarvis/config.toml").expanduser()
_CACHE_TTL = 86400  # 24 hours
_PYPI_API = "https://pypi.org/pypi/openjarvis/json"

# Commands that surface the "new version available" nudge. We deliberately
# cast a wide net for interactive commands (anything a human runs at a
# terminal and would benefit from knowing about an update), and skip
# automation-facing ones (``_bootstrap``, ``daemon``, ``host``) so we
# don't add noise to background processes or CI.
_CHECK_COMMANDS = {
    "ask",
    "chat",
    "serve",
    "doctor",
    "init",
    "quickstart",
    "model",
    "agents",
    "skill",
    "memory",
    "bench",
    "telemetry",
    "config",
    "eval",
    "optimize",
}

# Environment opt-outs (any truthy value disables the check):
# - ``OPENJARVIS_NO_UPDATE_CHECK=1`` — project-specific
# - ``CI=true`` — set by every major CI provider, suppresses by default
_OPT_OUT_ENV_VARS = ("OPENJARVIS_NO_UPDATE_CHECK",)


def _check_disabled() -> bool:
    """Return True when the user has opted out of update checks."""
    for name in _OPT_OUT_ENV_VARS:
        raw = os.environ.get(name, "")
        if raw and raw.strip().lower() not in ("", "0", "false", "no", "off"):
            return True
    # CI defaults to skipping. Users in CI can override with
    # ``OPENJARVIS_NO_UPDATE_CHECK=0`` if they want the nudge anyway.
    if os.environ.get("CI", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return _config_disabled()


def _config_disabled() -> bool:
    """Return True if ~/.openjarvis/config.toml has auto_update = false."""
    try:
        if not _CONFIG_PATH.exists():
            return False
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        with open(_CONFIG_PATH, "rb") as f:
            config = tomllib.load(f)
        return not config.get("updates", {}).get("auto_update", True)
    except Exception:
        return False


def check_for_updates(command_name: str) -> None:
    """Print a message if a newer version is available. Best-effort, never raises.

    Honors ``OPENJARVIS_NO_UPDATE_CHECK=1`` and ``CI=true`` — any
    truthy value (``1``, ``true``, ``yes``, ``on``) disables both the
    GitHub poll and the banner. See ``_check_disabled`` for the full
    list.
    """
    if command_name not in _CHECK_COMMANDS:
        return
    if _check_disabled():
        return
    try:
        _do_check()
    except Exception:
        pass


def _do_check() -> None:
    import openjarvis

    current = openjarvis.__version__
    latest = _get_latest_version(current)
    if latest is None:
        return

    from packaging.version import InvalidVersion, Version

    try:
        if Version(latest) > Version(current):
            from openjarvis.cli._install_detect import detect_install

            cmd = detect_install().upgrade_command
            sys.stderr.write(
                f"\033[33mA new version of OpenJarvis is available "
                f"(v{current} \u2192 v{latest})\n"
                f"Update: {cmd}\n"
                f"Or run: jarvis self-update\033[0m\n\n"
            )
    except InvalidVersion:
        pass


def _get_latest_version(current: str) -> str | None:
    """Return latest version string from cache or GitHub API."""
    try:
        if _CACHE_PATH.exists():
            data = json.loads(_CACHE_PATH.read_text())
            last_check = data.get("last_check", 0)
            if time.time() - last_check < _CACHE_TTL:
                return data.get("latest_version")
    except Exception:
        pass

    try:
        import urllib.request

        with urllib.request.urlopen(_PYPI_API, timeout=3) as resp:
            data = json.loads(resp.read())
            latest = data.get("info", {}).get("version", "")
    except Exception:
        return None

    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(
            json.dumps(
                {
                    "last_check": time.time(),
                    "latest_version": latest,
                    "current_version": current,
                }
            )
        )
    except Exception:
        pass

    return latest
