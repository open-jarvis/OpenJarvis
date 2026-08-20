"""Check for newer OpenJarvis releases on PyPI."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

from openjarvis.core.paths import get_config_dir

logger = logging.getLogger(__name__)

_CACHE_PATH = get_config_dir() / "version-check.json"
_CACHE_TTL = 86400  # 24 hours
_PYPI_API = "https://pypi.org/pypi/openjarvis/json"


def _config_path() -> Path:
    """Resolve the config path, honoring ``OPENJARVIS_CONFIG`` like core.config."""
    override = os.environ.get("OPENJARVIS_CONFIG")
    if override:
        return Path(override).expanduser()
    return get_config_dir() / "config.toml"


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
    """Return True if config.toml has ``[updates] auto_update = false``.

    On a malformed config we conservatively return ``True`` — if the user
    tried to express an opt-out and the file has a typo, we should not
    silently flip back to auto-checking against their intent.
    """
    path = _config_path()
    if not path.exists():
        return False
    try:
        import tomllib
    except ImportError:  # Python 3.10
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            logger.debug("tomli not available, skipping config opt-out check")
            return False
    try:
        with open(path, "rb") as f:
            config = tomllib.load(f)
    except OSError as exc:
        logger.debug("config read failed: %s", exc)
        return False
    except tomllib.TOMLDecodeError as exc:
        logger.debug("config malformed at %s: %s — treating as opt-out", path, exc)
        return True
    return not config.get("updates", {}).get("auto_update", True)


def check_for_updates(command_name: str) -> None:
    """Print a message if a newer version is available. Best-effort, never raises.

    Honors ``OPENJARVIS_NO_UPDATE_CHECK=1`` and ``CI=true`` — any
    truthy value (``1``, ``true``, ``yes``, ``on``) disables both the
    PyPI poll and the banner. See ``_check_disabled`` for the full list.
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
                f"(v{current} → v{latest})\n"
                f"Update: {cmd}\n"
                f"Or run: jarvis self-update\033[0m\n\n"
            )
    except InvalidVersion:
        pass


def _get_latest_version(current: str) -> str | None:
    """Return the latest non-prerelease version string from cache or PyPI.

    Returns ``None`` on network/parse failures rather than caching a stale
    or empty result. Dev/pre-release versions (``.devN``, ``aN``, ``bN``,
    ``rcN``) are filtered out so users on a stable release are not nudged
    to a rolling autotag build — they can still opt in via ``--pre``.
    """
    try:
        if _CACHE_PATH.exists():
            data = json.loads(_CACHE_PATH.read_text())
            last_check = data.get("last_check", 0)
            if time.time() - last_check < _CACHE_TTL:
                cached = data.get("latest_version")
                return cached or None
    except Exception:
        pass

    latest = _fetch_latest_stable()
    if not latest:
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


def _fetch_latest_stable() -> str | None:
    """Query PyPI and return the highest non-prerelease version, or ``None``."""
    try:
        import urllib.request

        with urllib.request.urlopen(_PYPI_API, timeout=3) as resp:
            data = json.loads(resp.read())
    except Exception as exc:
        logger.debug("PyPI poll failed: %s", exc)
        return None

    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:
        # Fall back to the raw info.version if packaging isn't installed.
        return data.get("info", {}).get("version") or None

    releases = data.get("releases", {})
    stable: list[Version] = []
    for raw in releases.keys():
        try:
            v = Version(raw)
        except InvalidVersion:
            continue
        if v.is_prerelease or v.is_devrelease:
            continue
        stable.append(v)

    if stable:
        return str(max(stable))

    # No stable releases yet — fall back to info.version (handles brand-new
    # projects that have only published dev releases).
    info_version = data.get("info", {}).get("version")
    return info_version or None
