"""Small persisted settings for automations (``~/.openjarvis/automation.json``).

Cron schedules are evaluated in an IANA timezone stored on each task. Tasks
created by voice through the ``schedule_task`` tool carry no timezone of their
own, so they use the default recorded here (the HUD reports the browser's
timezone on load). Without one, cron expressions are evaluated in UTC.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_FILENAME = "automation.json"


def _path() -> Path:
    from openjarvis.core.paths import get_config_dir

    return get_config_dir() / _FILENAME


def _load() -> Dict[str, Any]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def valid_timezone(name: str) -> bool:
    if not name:
        return False
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(name)
        return True
    except Exception:
        return False


def get_default_timezone() -> Optional[str]:
    tz = str(_load().get("default_timezone") or "")
    return tz if valid_timezone(tz) else None


def set_default_timezone(name: str) -> None:
    if not valid_timezone(name):
        raise ValueError(f"Unknown timezone: {name!r}")
    with _LOCK:
        data = _load()
        if data.get("default_timezone") == name:
            return
        data["default_timezone"] = name
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


__all__ = ["get_default_timezone", "set_default_timezone", "valid_timezone"]
