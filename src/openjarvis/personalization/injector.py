"""Prompt middleware injectors that personalise the system prompt.

* :class:`ProfileInjector` — append a compact "things I know about you"
  block from USER.md.
* :class:`SessionRecallInjector` — append "previously you said X" hints
  drawn from past sessions.
* :class:`ToolAffinityInjector` — surface the user's most-used tools so
  the model defaults to them.

All three play nice with the existing
:func:`openjarvis.agents.prompt_middleware.apply_chain` API and skip
gracefully when their data source is missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from openjarvis.personalization.profile import (
    DEFAULT_PROFILE_PATH,
    UserProfile,
)

logger = logging.getLogger(__name__)


def _wrap_block(title: str, body: str) -> str:
    return f"\n\n[{title}]\n{body.rstrip()}"


# ---------------------------------------------------------------------------
# ProfileInjector
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ProfileInjector:
    """Append the active user profile to the system prompt.

    When ``profile`` is given, uses it directly (useful for tests).
    Otherwise loads from ``profile_path`` on every call so manual edits
    take effect without restarting Jarvis.
    """

    profile_path: Path = field(default_factory=lambda: DEFAULT_PROFILE_PATH)
    profile: Optional[UserProfile] = None
    max_entries: int = 30

    def __call__(self, prompt: Optional[str]) -> Optional[str]:
        if prompt is None:
            return None
        profile = self.profile or UserProfile.load(self.profile_path)
        if profile.is_empty():
            return prompt
        lines: List[str] = []
        count = 0
        for section_name in profile.sections:
            section = profile.sections[section_name]
            if section.is_empty():
                continue
            lines.append(f"{section_name}:")
            for entry in section.entries:
                if count >= self.max_entries:
                    break
                if entry.key:
                    lines.append(f"  - {entry.key}: {entry.value}")
                else:
                    lines.append(f"  - {entry.value}")
                count += 1
            if count >= self.max_entries:
                break
        body = "\n".join(lines).strip()
        if not body:
            return prompt
        return prompt + _wrap_block("我知道關於你", body)


# ---------------------------------------------------------------------------
# SessionRecallInjector
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SessionRecallInjector:
    """Inject "previously you said" hints for the current query.

    Parameters
    ----------
    recaller:
        Object exposing ``recall(query: str, *, limit: int) -> list[str]``.
        Typically a :class:`SessionRecaller` instance, but tests can pass
        a stub.
    query_getter:
        Optional callable returning the user's current query. When
        ``None`` the injector becomes a no-op (the chain currently has
        no way to plumb runtime context through), but
        :meth:`for_query` can be used to construct a per-call injector.
    limit:
        Maximum number of past turns to inject.
    """

    recaller: object
    query: Optional[str] = None
    limit: int = 3

    def for_query(self, query: str) -> "SessionRecallInjector":
        return SessionRecallInjector(
            recaller=self.recaller,
            query=query,
            limit=self.limit,
        )

    def __call__(self, prompt: Optional[str]) -> Optional[str]:
        if prompt is None or not self.query:
            return prompt
        try:
            hints = self.recaller.recall(self.query, limit=self.limit)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("SessionRecaller failed: %s", exc)
            return prompt
        if not hints:
            return prompt
        body = "\n".join(f"- {h}" for h in hints)
        return prompt + _wrap_block("過去對話線索", body)


# ---------------------------------------------------------------------------
# ToolAffinityInjector
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ToolAffinityInjector:
    """Surface the user's most-used tools so the model picks them first."""

    tracker: object
    top_n: int = 5

    def __call__(self, prompt: Optional[str]) -> Optional[str]:
        if prompt is None:
            return prompt
        try:
            top = self.tracker.top_tools(self.top_n)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.debug("ToolAffinityTracker failed: %s", exc)
            return prompt
        if not top:
            return prompt
        body_lines: List[str] = []
        for name, count, success_rate in top:
            body_lines.append(
                f"- {name}（用過 {count} 次，成功率 {success_rate:.0%}）"
            )
        return prompt + _wrap_block("你常用的工具", "\n".join(body_lines))


__all__ = [
    "ProfileInjector",
    "SessionRecallInjector",
    "ToolAffinityInjector",
]
