"""Turn a free-text objective into structured target properties.

One LLM call using ``ResponseFormat(type="json_schema", ...)`` (see
``engine/_stubs.py``), following the schema-building + brace-matching-parse
pattern from ``agents/hybrid/skillorchestra.py``. Tolerates providers that
ignore ``response_format`` entirely (OpenRouter/MiniMax/DeepSeek, per
``engine/cloud.py``) via the prompt's explicit "ONLY a JSON object"
instruction plus the fallback parser.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine, ResponseFormat
from openjarvis.science_lab.models import PropertyAnalysis

_SYSTEM_PROMPT = """You are a materials-science property analyzer. Given a \
free-text description of something the user wants to create or investigate, \
identify the underlying scientific property requirements — do NOT invent a \
specific recipe or substance, only decompose the request into measurable \
target properties (e.g. elasticity, viscosity, tensile strength, density, \
adhesion, solidification time, fiber-forming capacity, thermal stability).

Respond with ONLY a JSON object of this shape:
{"objective": "...", "target_properties": [{"name": "...", "target_value": \
"...", "unit": "...", "rationale": "..."}], "constraints": ["..."]}
No prose outside JSON."""

_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "objective": {"type": "string"},
        "target_properties": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "target_value": {"type": "string"},
                    "unit": {"type": "string"},
                    "rationale": {"type": "string"},
                },
                "required": ["name"],
            },
        },
        "constraints": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["objective", "target_properties"],
}


def _parse_json(text: str) -> Dict[str, Any]:
    """Brace-matching JSON parser — same discipline as skillorchestra.py."""
    s = (text or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    if start == -1:
        raise ValueError(f"property analyzer emitted no JSON: {s[:200]!r}")
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])
    raise ValueError(f"property analyzer JSON not balanced: {s[:200]!r}")


def analyze_objective(
    engine: InferenceEngine, model: str, description: str
) -> PropertyAnalysis:
    """Decompose *description* into a :class:`PropertyAnalysis`.

    Raises ``ValueError`` if the model's output cannot be parsed as JSON
    even after the fallback brace-matching pass — callers should treat this
    as a soft failure (log + surface a LIMITAÇÕES note), not a hard crash.
    """
    messages = [
        Message(role=Role.SYSTEM, content=_SYSTEM_PROMPT),
        Message(role=Role.USER, content=description),
    ]
    result = engine.generate(
        messages,
        model=model,
        temperature=0.2,
        max_tokens=1024,
        response_format=ResponseFormat(type="json_schema", schema=_SCHEMA),
    )
    data = _parse_json(result.get("content", ""))
    if not data.get("objective"):
        data["objective"] = description
    return PropertyAnalysis.from_dict(data)


__all__ = ["analyze_objective"]
