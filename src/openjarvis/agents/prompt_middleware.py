"""Prompt middleware: composable transforms applied to the system prompt.

Each middleware is a callable ``(prompt: str | None, ctx: dict) -> str | None``.
The default middleware injects the current date/time into the prompt so local
models do not hallucinate "today's date" from training data.

The timezone is read from config (default Asia/Taipei). A ``clock`` keyword can
be passed to ``DateTimeInjector`` so tests can pin a deterministic clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Callable, Optional

PromptMiddleware = Callable[[Optional[str]], Optional[str]]

_WEEKDAY = ["一", "二", "三", "四", "五", "六", "日"]


def _resolve_tz(name: str) -> Optional[tzinfo]:
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

    timezone: str = "Asia/Taipei"
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
            now = datetime.now(tz) if tz is not None else datetime.now()
        weekday = _WEEKDAY[now.weekday()]
        return (
            f"\n\n[即時資訊] 現在時間：{now.strftime('%Y-%m-%d')} "
            f"星期{weekday} {now.strftime('%H:%M')}（{self.timezone}）。"
            f"問到日期、時間、今天、明天、星期幾時，以這個為準，不要用訓練資料的舊日期。"
        )


def build_default_middleware(cfg) -> list[PromptMiddleware]:
    """Build the default middleware chain from a loaded config object.

    Returns an empty list when ``cfg.agent.inject_datetime`` is False.
    """
    chain: list[PromptMiddleware] = []
    agent_cfg = getattr(cfg, "agent", None)
    if agent_cfg is None:
        return chain
    if not getattr(agent_cfg, "inject_datetime", True):
        return chain
    tz = getattr(agent_cfg, "datetime_timezone", "Asia/Taipei") or "Asia/Taipei"
    chain.append(DateTimeInjector(timezone=tz))
    return chain


def apply_chain(
    prompt: Optional[str], chain: list[PromptMiddleware]
) -> Optional[str]:
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
