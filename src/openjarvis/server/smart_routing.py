"""Smart model routing: keep everyday chat local, send hard work to Claude.

A client opts in by sending ``model="auto"`` to ``/v1/chat/completions``.
The server then picks a concrete model per request:

* Claude (``OPENJARVIS_CLAUDE_MODEL``, default ``claude-opus-5-5``) when it is
  configured and the request is complex, asks for Claude by name, or sets up
  an automation (scheduling and multi-step tool use need reliable tool calls);
* otherwise the server's local default model.

Claude counts as available only when ``ANTHROPIC_API_KEY`` is set and the
running engine advertises the Claude model, so a missing key silently keeps
everything local instead of failing requests.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Optional

AUTO_MODEL = "auto"
DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"

# Complexity tiers (see learning/routing/complexity.py) that go to Claude.
_CLAUDE_TIERS = frozenset({"complex", "very_complex"})

_EXPLICIT_CLAUDE = re.compile(
    r"\b(ask|use|with|via|using|let)\s+claude\b|^\s*claude\b[\s,:]",
    re.IGNORECASE,
)
_AUTOMATION_INTENT = re.compile(
    r"\b(every\s+(day|morning|evening|night|week|hour|\d+\s*(min|minute|hour)s?)"
    r"|daily|weekly|hourly|remind\s+me|schedule|automat(e|ion)|routine"
    r"|at\s+\d{1,2}(:\d{2})?\s*(am|pm)?\s+(every|each|daily)"
    r"|claude\s+code|refactor|write\s+(a\s+)?(script|program|code))\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RouteDecision:
    model: str
    reason: str
    used_claude: bool


def claude_model() -> str:
    return os.environ.get("OPENJARVIS_CLAUDE_MODEL", "").strip() or DEFAULT_CLAUDE_MODEL


def claude_available(engine: Any) -> bool:
    """True when Claude can actually serve requests on this server."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        models = engine.list_models() if engine is not None else []
    except Exception:
        return False
    return claude_model() in models


def choose_model(
    query: str,
    tier: Optional[str],
    *,
    local_model: str,
    engine: Any,
) -> RouteDecision:
    """Pick the model for one request sent with ``model="auto"``."""
    if claude_available(engine):
        target = claude_model()
        if _EXPLICIT_CLAUDE.search(query or ""):
            return RouteDecision(target, "asked for Claude", True)
        if _AUTOMATION_INTENT.search(query or ""):
            return RouteDecision(target, "automation or coding task", True)
        if tier in _CLAUDE_TIERS:
            return RouteDecision(target, f"{tier.replace('_', ' ')} request", True)
    return RouteDecision(local_model, "everyday request (local)", False)


__all__ = [
    "AUTO_MODEL",
    "DEFAULT_CLAUDE_MODEL",
    "RouteDecision",
    "choose_model",
    "claude_available",
    "claude_model",
]
