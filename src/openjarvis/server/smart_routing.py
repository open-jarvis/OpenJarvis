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


_MALAYALAM_CHAR = re.compile(r"[ഀ-ൿ]")
_LATIN_CHAR = re.compile(r"[A-Za-z]")
# Share of letters that must be Malayalam: an English question quoting one
# Malayalam word stays an English question.
_MALAYALAM_SHARE = 0.3


# A trailing "(...)" paragraph is a client instruction (the HUD appends one in
# English to spoken turns), not the user's words: judge the language without it.
_TRAILING_INSTRUCTION = re.compile(r"\n\s*\n\s*\([^()]*\)\s*$")


def _is_malayalam(text: str) -> bool:
    text = _TRAILING_INSTRUCTION.sub("", text)
    ml = len(_MALAYALAM_CHAR.findall(text))
    if ml == 0:
        return False
    latin = len(_LATIN_CHAR.findall(text))
    return ml / (ml + latin) >= _MALAYALAM_SHARE


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


DEFAULT_OPENAI_MODEL = "gpt-5.4"

_EXPLICIT_GPT = re.compile(
    r"\b(ask|use|with|via|using|let)\s+(chat\s*gpt|gpt(-?\d[\w.]*)?|openai)\b"
    r"|^\s*(chat\s*gpt|gpt)\b[\s,:]",
    re.IGNORECASE,
)


def openai_model() -> str:
    return os.environ.get("OPENJARVIS_OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL


def openai_available(engine: Any) -> bool:
    """True when ChatGPT (OpenAI API) can serve requests on this server."""
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    try:
        models = engine.list_models() if engine is not None else []
    except Exception:
        return False
    return openai_model() in models


def choose_model(
    query: str,
    tier: Optional[str],
    *,
    local_model: str,
    engine: Any,
) -> RouteDecision:
    """Pick the model for one request sent with ``model="auto"``.

    Asking for ChatGPT / GPT or Claude by name goes to that model when it is
    configured. Otherwise hard work (automations, coding, complex requests)
    goes to Claude, or to ChatGPT when only an OpenAI key is set.
    """
    text = query or ""
    if _EXPLICIT_GPT.search(text) and openai_available(engine):
        return RouteDecision(openai_model(), "asked for ChatGPT", False)
    has_claude = claude_available(engine)
    if _EXPLICIT_CLAUDE.search(text) and has_claude:
        return RouteDecision(claude_model(), "asked for Claude", True)
    hard = None
    if _AUTOMATION_INTENT.search(text):
        hard = "automation or coding task"
    elif _is_malayalam(text):
        # Small local models write poor Malayalam; cloud models are far better.
        hard = "Malayalam request"
    elif tier in _CLAUDE_TIERS:
        hard = f"{tier.replace('_', ' ')} request"
    if hard:
        if has_claude:
            return RouteDecision(claude_model(), hard, True)
        if openai_available(engine):
            return RouteDecision(openai_model(), f"{hard} (ChatGPT)", False)
    return RouteDecision(local_model, "everyday request (local)", False)


__all__ = [
    "AUTO_MODEL",
    "DEFAULT_CLAUDE_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "RouteDecision",
    "choose_model",
    "claude_available",
    "claude_model",
    "openai_available",
    "openai_model",
]
