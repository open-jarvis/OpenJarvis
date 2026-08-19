"""Route a transcribed voice utterance to an action.

Covers the fixed voice-command phrases from the brief: "abra o laboratório
científico", "analise este material", "compare esses dois materiais",
"simule essa mistura", "salve esse projeto" — with PT phrasing variants.
Anything that doesn't match falls through to ``chat_fallback``, which the
caller routes to the ordinary default chat agent. This fallthrough is the
intended extension point for the future Adaptive Learning module (routing
free-chat through usage-pattern-aware logic instead of the plain default
agent) — no redesign needed there, just a richer handler behind the same
``chat_fallback`` action.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

ACTION_OPEN_SCIENCE_LAB = "open_science_lab"
ACTION_ANALYZE_MATERIAL = "analyze_material"
ACTION_COMPARE_MATERIALS = "compare_materials"
ACTION_SIMULATE_MIXTURE = "simulate_mixture"
ACTION_SAVE_PROJECT = "save_project"
ACTION_CHAT_FALLBACK = "chat_fallback"


@dataclass(slots=True)
class VoiceIntent:
    """The resolved action + captured arguments for a voice utterance."""

    action: str
    args: Dict[str, Any] = field(default_factory=dict)
    matched_phrase: str = ""


# Ordered (regex, action) pairs — first match wins. Bilingual-leaning PT
# per the brief's example phrases, with light variation tolerance.
_PATTERNS: List[Tuple[str, str]] = [
    (r"(?i)abr[ae]?\s+(o\s+)?laborat[óo]rio\s+cient[íi]fico", ACTION_OPEN_SCIENCE_LAB),
    (r"(?i)abr[ae]?\s+(a\s+)?science\s*lab", ACTION_OPEN_SCIENCE_LAB),
    (r"(?i)analis[ae]r?\s+(este|esse|o)?\s*material", ACTION_ANALYZE_MATERIAL),
    (
        r"(?i)compar[ae]r?\s+(esses|estes)?\s*(dois\s+)?materiais",
        ACTION_COMPARE_MATERIALS,
    ),
    (r"(?i)simul[ae]r?\s+(essa|esta|a)?\s*mistura", ACTION_SIMULATE_MIXTURE),
    (r"(?i)salv[ae]r?\s+(esse|este|o)?\s*projeto", ACTION_SAVE_PROJECT),
]

_COMPILED = [(re.compile(pat), action) for pat, action in _PATTERNS]


class IntentRouter:
    """Matches transcribed text against the fixed voice-command phrases."""

    def route(self, text: str) -> VoiceIntent:
        stripped = (text or "").strip()
        for pattern, action in _COMPILED:
            m = pattern.search(stripped)
            if m:
                return VoiceIntent(action=action, args={}, matched_phrase=m.group(0))
        return VoiceIntent(action=ACTION_CHAT_FALLBACK, args={"text": stripped})


__all__ = [
    "ACTION_ANALYZE_MATERIAL",
    "ACTION_CHAT_FALLBACK",
    "ACTION_COMPARE_MATERIALS",
    "ACTION_OPEN_SCIENCE_LAB",
    "ACTION_SAVE_PROJECT",
    "ACTION_SIMULATE_MIXTURE",
    "IntentRouter",
    "VoiceIntent",
]
