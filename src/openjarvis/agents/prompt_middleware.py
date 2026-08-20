"""Prompt middleware: composable transforms applied to the system prompt.

Each middleware is a callable ``(prompt: str | None, ctx: dict) -> str | None``.
The default middleware injects the current date/time into the prompt so local
models do not hallucinate "today's date" from training data.

The timezone is read from config (default: the machine's local timezone). A
``clock`` keyword can be passed to ``DateTimeInjector`` so tests can pin a
deterministic clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Callable, Optional

PromptMiddleware = Callable[[Optional[str]], Optional[str]]


def _resolve_tz(name: str) -> Optional[tzinfo]:
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:
        return None


@dataclass(slots=True)
class DateTimeInjector:
    """Append a "current date/time" note to a system prompt.

    - ``timezone``: IANA name; falls back to local if zoneinfo fails.
    - ``clock``: optional ``() -> datetime`` for tests. When omitted, uses
      ``datetime.now(tz)``.
    - Skips injection when called with ``None`` (i.e. context already supplied
      a SYSTEM message and we agreed not to add a second one).
    """

    timezone: str = ""
    clock: Optional[Callable[[], datetime]] = None

    def __call__(self, prompt: Optional[str]) -> Optional[str]:
        if prompt is None:
            return None
        note = self._build_note()
        return f"{prompt}{note}" if prompt else note.lstrip()

    def _build_note(self) -> str:
        if self.clock is not None:
            now = self.clock()
        else:
            tz = _resolve_tz(self.timezone)
            now = datetime.now(tz) if tz is not None else datetime.now().astimezone()
        timezone_label = self.timezone or now.tzname() or "local time"
        return (
            f"\n\n[Current date and time] {now.strftime('%Y-%m-%d %A %H:%M')} "
            f"({timezone_label}). Use this value for date and time questions "
            "instead of relying on the model's training cutoff."
        )


def build_default_middleware(cfg) -> list[PromptMiddleware]:
    """Build the default middleware chain from a loaded config object.

    Steps applied in order (each respects its own enable flag):

    1. ``DateTimeInjector`` — current date/time in configured timezone.
    2. ``ProfileInjector`` — append USER.md "things I know about you".
    3. ``ToolAffinityInjector`` — list the user's most-used tools.
    """
    chain: list[PromptMiddleware] = []
    agent_cfg = getattr(cfg, "agent", None)
    if agent_cfg is None:
        return chain

    if getattr(agent_cfg, "inject_datetime", True):
        tz = getattr(agent_cfg, "datetime_timezone", "") or ""
        chain.append(DateTimeInjector(timezone=tz))

    if getattr(agent_cfg, "inject_profile", True):
        try:
            from openjarvis.personalization.injector import ProfileInjector
            from openjarvis.personalization.profile import (
                DEFAULT_PROFILE_PATH,
            )

            profile_path = getattr(agent_cfg, "profile_path", str(DEFAULT_PROFILE_PATH))
            from pathlib import Path

            chain.append(ProfileInjector(profile_path=Path(profile_path).expanduser()))
        except Exception:
            pass

    if getattr(agent_cfg, "inject_tool_affinity", True):
        try:
            from openjarvis.personalization.injector import ToolAffinityInjector
            from openjarvis.personalization.tool_affinity import get_default_tracker

            tracker = get_default_tracker()
            chain.append(ToolAffinityInjector(tracker=tracker))
        except Exception:
            pass

    return chain


def apply_chain(prompt: Optional[str], chain: list[PromptMiddleware]) -> Optional[str]:
    """Apply middleware in order. Each step may return a new string or None."""
    out = prompt
    for step in chain:
        out = step(out)
    return out


__all__ = [
    "DateTimeInjector",
    "PromptMiddleware",
    "apply_chain",
    "build_default_middleware",
]
