from __future__ import annotations

from openjarvis.security.types import ThreatLevel

_DEFAULT_ACTIONS = {
    ThreatLevel.CRITICAL: "block",
    ThreatLevel.HIGH: "warn",
    ThreatLevel.MEDIUM: "sanitize",
    ThreatLevel.LOW: "log",
}


class SeverityPolicy:
    """Maps ThreatLevel to configurable actions (block/warn/sanitize/log)."""

    def __init__(self, overrides: dict[ThreatLevel, str] | None = None) -> None:
        self._actions = dict(_DEFAULT_ACTIONS)
        if overrides:
            self._actions.update(overrides)

    def action_for(self, level: ThreatLevel) -> str:
        return self._actions.get(level, "log")
