"""Generate and rank competing scientific hypotheses.

Adapts ``agents/hybrid/archon.py``'s "K candidates -> single ranker call ->
line-scan parse, fallback to index 0 on failure" discipline: here, one LLM
call returns 2-3 hypotheses directly as a JSON array (cheaper than K
independent calls, since these are competing explanations from one model,
not K independent rollouts), then an optional second call ranks them.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from openjarvis.core.types import Message, Role
from openjarvis.engine._stubs import InferenceEngine, ResponseFormat
from openjarvis.science_lab.models import Hypothesis, PropertyAnalysis

_GENERATE_SYSTEM_PROMPT = """You are a materials-science hypothesis generator. \
Given a set of target properties, propose {k_range} distinct, competing \
scientific mechanisms/approaches that could plausibly achieve them. Each \
hypothesis must be scientifically grounded (real chemistry/physics \
mechanisms), not a specific product recipe.

Respond with ONLY a JSON object: {{"hypotheses": [{{"id": "H1", "mechanism": \
"...", "key_properties": {{"property_name": "expected_value"}}, "pros": \
["..."], "cons": ["..."]}}]}}. No prose outside JSON."""

_HYPOTHESIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "mechanism": {"type": "string"},
                    "key_properties": {"type": "object"},
                    "pros": {"type": "array", "items": {"type": "string"}},
                    "cons": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "mechanism"],
            },
        }
    },
    "required": ["hypotheses"],
}

_RANKER_SYSTEM_PROMPT = """You are ranking competing scientific hypotheses \
by how well they satisfy the stated target properties, feasibility, and \
safety. Respond with ONLY the number (index, 0-based) of the single best \
hypothesis on its own line, e.g.:
1
No other text."""


def _parse_json(text: str) -> Dict[str, Any]:
    s = (text or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    if start == -1:
        raise ValueError(f"hypothesis engine emitted no JSON: {s[:200]!r}")
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])
    raise ValueError(f"hypothesis engine JSON not balanced: {s[:200]!r}")


def generate_hypotheses(
    engine: InferenceEngine,
    model: str,
    analysis: PropertyAnalysis,
    k: int = 3,
) -> List[Hypothesis]:
    """Generate up to *k* competing hypotheses for *analysis*.

    On a parse failure, raises ``ValueError`` (soft-failure convention —
    callers should catch and surface a LIMITAÇÕES note rather than crash).
    """
    props_text = "\n".join(
        f"- {p.name}: {p.target_value} {p.unit} ({p.rationale})".strip()
        for p in analysis.target_properties
    )
    user_content = (
        f"Objective: {analysis.objective}\n\nTarget properties:\n{props_text}"
    )
    messages = [
        Message(
            role=Role.SYSTEM,
            content=_GENERATE_SYSTEM_PROMPT.format(k_range=f"2 to {k}"),
        ),
        Message(role=Role.USER, content=user_content),
    ]
    result = engine.generate(
        messages,
        model=model,
        temperature=0.4,
        max_tokens=1536,
        response_format=ResponseFormat(type="json_schema", schema=_HYPOTHESIS_SCHEMA),
    )
    data = _parse_json(result.get("content", ""))
    raw_hypotheses = data.get("hypotheses", [])[:k]
    hypotheses = [Hypothesis.from_dict(h) for h in raw_hypotheses]
    # Ensure IDs are always present and unique, even if the model omitted them.
    for i, h in enumerate(hypotheses):
        if not h.id:
            h.id = f"H{i + 1}"
    return hypotheses


def rank_hypotheses(
    engine: InferenceEngine, model: str, hypotheses: List[Hypothesis]
) -> Tuple[int, str]:
    """Rank *hypotheses*, returning ``(chosen_index, reasoning_text)``.

    Follows archon.py's fallback discipline: any parse failure or
    out-of-range index falls back to index 0 rather than raising, since
    ranking is a refinement step, not a required one.
    """
    if not hypotheses:
        return 0, "No hypotheses to rank."
    listing = "\n\n".join(
        f"[{i}] {h.mechanism}\nPros: {', '.join(h.pros)}\nCons: {', '.join(h.cons)}"
        for i, h in enumerate(hypotheses)
    )
    messages = [
        Message(role=Role.SYSTEM, content=_RANKER_SYSTEM_PROMPT),
        Message(role=Role.USER, content=listing),
    ]
    result = engine.generate(messages, model=model, temperature=0.0, max_tokens=64)
    ranker_text = result.get("content", "")

    chosen_idx = 0
    for line in ranker_text.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            chosen_idx = int(stripped)
            break
    if not (0 <= chosen_idx < len(hypotheses)):
        chosen_idx = 0
    return chosen_idx, ranker_text.strip()


__all__ = ["generate_hypotheses", "rank_hypotheses"]
