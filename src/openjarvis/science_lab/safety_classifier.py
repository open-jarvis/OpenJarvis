"""Two-layer dangerous-chemistry classifier for Science Lab.

Modeled on ``security/injection_scanner.py``'s shape (pattern list + result
dataclass) but implemented as pure Python regex, not routed through the Rust
bridge — this runs once per Science Lab request (a low-frequency call site),
unlike ``InjectionScanner`` which scans every prompt on a hot path.

Layer 1 (keyword/pattern, no LLM call) flags danger-category vocabulary and,
separately, operational/procedural-intent vocabulary. Only the combination of
both triggers a refusal — a purely theoretical question about a dangerous
substance's chemistry is allowed through. Layer 2 (LLM fallback) only runs
for ambiguous cases and can only add a stricter confirmation, never override
a Layer-1 hard match; a broken/unavailable Layer 2 defaults to *allowing*
the request through (soft failure), never to silently blocking it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

# (regex, category, pattern_name) — bilingual PT/EN, case-insensitive.
_DANGER_PATTERNS: List[Tuple[str, str, str]] = [
    (
        r"(?i)\b(explosivos?|explosives?|bomba|bombs?|detonador|detonators?|"
        r"TATP|nitroglicerina|nitroglycerin|dinamite|dynamite|C-?4|semtex)\b",
        "explosive",
        "explosive_terms",
    ),
    (
        r"(?i)\b(veneno|venenos|poison|toxina|toxinas?|toxins?|cianeto|cyanide|"
        r"ricina|ricin|arsênico|arsenic|tálio|thallium)\b",
        "toxin",
        "toxin_terms",
    ),
    (
        r"(?i)\b(g[áa]s\s+t[óo]xico|toxic\s+gas|cloro\s+gasoso|chlorine\s+gas|"
        r"fosg[êe]nio|phosgene|[áa]cido\s+cian[íi]drico|hydrogen\s+cyanide|"
        r"sarin|mostarda\s+sulf[úu]rica|mustard\s+gas)\b",
        "dangerous_gas",
        "gas_terms",
    ),
    (
        r"(?i)\b(arma\s+qu[íi]mica|chemical\s+weapon|arma\s+biol[óo]gica|"
        r"biological\s+weapon|agente\s+de\s+guerra|warfare\s+agent)\b",
        "weapon",
        "weapon_terms",
    ),
    (
        r"(?i)\b(rea[çc][ãa]o\s+descontrolada|uncontrolled\s+reaction|"
        r"rea[çc][ãa]o\s+violenta|violent\s+reaction|exot[ée]rmica\s+fora\s+de\s+controle)\b",
        "violent_reaction",
        "violent_reaction_terms",
    ),
]

# Procedural/operational-intent vocabulary — "how do I actually do this",
# distinct from "why does this happen" theoretical curiosity.
_OPERATIONAL_PATTERNS: List[str] = [
    r"(?i)\bcomo\s+(fazer|preparar|produzir|sintetizar|construir)\b",
    r"(?i)\bhow\s+(to|do\s+i)\s+(make|prepare|produce|synthesize|build)\b",
    r"(?i)\bpasso\s+a\s+passo\b",
    r"(?i)\bstep[\s-]by[\s-]step\b",
    r"(?i)\bpropor[çc][õo]es?\s+exatas?\b",
    r"(?i)\bexact\s+(proportions?|ratios?|quantities)\b",
    r"(?i)\bonde\s+comprar\b",
    r"(?i)\bwhere\s+(to\s+)?buy\b",
    r"(?i)\bquantidade\s+(necess[áa]ria\s+)?para\b",
    r"(?i)\breceita\s+(para|de)\b",
    r"(?i)\brecipe\s+for\b",
    r"(?i)\binstru[çc][õo]es\s+(de\s+)?(preparo|prepara[çc][ãa]o)\b",
]


@dataclass(slots=True)
class DangerFinding:
    """A single danger-category match."""

    category: str
    matched_text: str
    pattern_name: str


@dataclass(slots=True)
class ClassificationResult:
    """Verdict on whether a request must be refused."""

    is_dangerous: bool
    is_operational: bool
    findings: List[DangerFinding] = field(default_factory=list)
    refusal_text: str = ""
    basis: str = "clean"  # "keyword_match" | "llm_fallback" | "clean"

    @property
    def should_refuse(self) -> bool:
        return self.is_dangerous and self.is_operational


_COMPILED_DANGER = [
    (re.compile(pat), category, name) for pat, category, name in _DANGER_PATTERNS
]
_COMPILED_OPERATIONAL = [re.compile(pat) for pat in _OPERATIONAL_PATTERNS]


def _match_danger(text: str) -> List[DangerFinding]:
    findings: List[DangerFinding] = []
    for pattern, category, name in _COMPILED_DANGER:
        m = pattern.search(text)
        if m:
            findings.append(
                DangerFinding(
                    category=category, matched_text=m.group(0), pattern_name=name
                )
            )
    return findings


def _match_operational(text: str) -> bool:
    return any(p.search(text) for p in _COMPILED_OPERATIONAL)


_LLM_SAFETY_SYSTEM_PROMPT = """You are a safety classifier for a chemistry/\
materials-science education assistant. Given a user request, decide:
1. is_dangerous: does it concern explosives, toxins/poisons, dangerous gases, \
chemical/biological weapons, or uncontrolled violent reactions?
2. is_operational: does it ask HOW to actually make/prepare/obtain something \
(procedure, quantities, sourcing) rather than asking why/how something works \
theoretically?

Respond with ONLY a JSON object: \
{"is_dangerous": true|false, "is_operational": true|false, "category": "...", \
"reasoning": "..."}. No prose outside JSON."""


def _parse_llm_json(text: str) -> dict:
    """Brace-matching JSON parser — same discipline as skillorchestra.py."""
    s = (text or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    if start == -1:
        raise ValueError(f"safety classifier emitted no JSON: {s[:200]!r}")
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])
    raise ValueError(f"safety classifier JSON not balanced: {s[:200]!r}")


def _build_refusal_text(category: str) -> str:
    return (
        f"Não posso fornecer um procedimento operacional relacionado a "
        f"{category}, pois isso poderia ser usado para causar dano real. "
        "Posso, no entanto, explicar a química ou física envolvida de forma "
        "teórica e segura, sem detalhes de execução."
    )


def classify(
    text: str,
    *,
    engine: Optional[Any] = None,
    model: str = "",
    llm_fallback_enabled: bool = True,
) -> ClassificationResult:
    """Classify *text* for dangerous + operational content.

    Layer 1 (always runs): keyword/pattern matching, no LLM call.
    Layer 2 (only when Layer 1 is inconclusive and *llm_fallback_enabled* and
    *engine* is provided): one LLM call for an ambiguous verdict. Layer 2
    can only add a stricter "yes" on top of an inconclusive Layer 1 result —
    it never overrides a Layer-1 hard match, and any failure (bad JSON,
    engine error) defaults to allowing the request through.
    """
    danger_findings = _match_danger(text)
    operational = _match_operational(text)
    dangerous = bool(danger_findings)

    if dangerous and operational:
        category = danger_findings[0].category
        return ClassificationResult(
            is_dangerous=True,
            is_operational=True,
            findings=danger_findings,
            refusal_text=_build_refusal_text(category),
            basis="keyword_match",
        )

    if dangerous and not operational:
        # Theoretical question about a dangerous substance — allowed through,
        # Layer 2 cannot override this into a refusal (only Layer 1 hard
        # matches on both axes trigger a refusal).
        return ClassificationResult(
            is_dangerous=True,
            is_operational=False,
            findings=danger_findings,
            basis="keyword_match",
        )

    if not dangerous and not operational:
        return ClassificationResult(
            is_dangerous=False, is_operational=False, basis="clean"
        )

    # Ambiguous: operational-sounding language without a clear danger-category
    # keyword hit (e.g. paraphrased/obfuscated requests). Try Layer 2 if
    # available; otherwise soft-fail to "allow".
    if not llm_fallback_enabled or engine is None:
        return ClassificationResult(
            is_dangerous=False, is_operational=operational, basis="clean"
        )

    try:
        from openjarvis.core.types import Message, Role

        messages = [
            Message(role=Role.SYSTEM, content=_LLM_SAFETY_SYSTEM_PROMPT),
            Message(role=Role.USER, content=text),
        ]
        result = engine.generate(messages, model=model, temperature=0.0, max_tokens=256)
        verdict = _parse_llm_json(result.get("content", ""))
        is_dangerous = bool(verdict.get("is_dangerous", False))
        is_operational = bool(verdict.get("is_operational", False))
        category = str(verdict.get("category", "unspecified"))
        if is_dangerous and is_operational:
            return ClassificationResult(
                is_dangerous=True,
                is_operational=True,
                findings=[
                    DangerFinding(
                        category=category,
                        matched_text=text[:80],
                        pattern_name="llm_verdict",
                    )
                ],
                refusal_text=_build_refusal_text(category),
                basis="llm_fallback",
            )
        return ClassificationResult(
            is_dangerous=is_dangerous,
            is_operational=is_operational,
            basis="llm_fallback",
        )
    except Exception:
        # Soft failure: never let a broken safety-LLM path silently block
        # legitimate science education.
        return ClassificationResult(
            is_dangerous=False, is_operational=operational, basis="clean"
        )


_SAFE_EXPLANATION_SYSTEM_PROMPT = """You are explaining the underlying chemistry/\
physics of a topic in {category} for educational purposes ONLY. You must:
- Explain WHY the phenomenon/mechanism happens at a conceptual level.
- NEVER include specific quantities, ratios, temperatures, reagent sourcing, \
or step-by-step procedures.
- Keep it educational and safe — mechanism-level understanding only, not a recipe."""


def explain_safely(engine: Any, model: str, category: str, original_text: str) -> str:
    """Produce a mechanism-level (never procedural) explanation for a refused topic.

    Used to satisfy "refuse the procedure, still explain the science" —
    this call's system prompt explicitly forbids quantities/procedures.
    On failure, returns a short static fallback rather than raising, since
    this runs after a refusal has already been decided and must not crash
    the response.
    """
    try:
        from openjarvis.core.types import Message, Role

        messages = [
            Message(
                role=Role.SYSTEM,
                content=_SAFE_EXPLANATION_SYSTEM_PROMPT.format(category=category),
            ),
            Message(role=Role.USER, content=original_text),
        ]
        result = engine.generate(messages, model=model, temperature=0.3, max_tokens=512)
        text = (result.get("content", "") or "").strip()
        return text or _fallback_explanation(category)
    except Exception:
        return _fallback_explanation(category)


def _fallback_explanation(category: str) -> str:
    return (
        f"Posso explicar, de forma geral, os princípios químicos/físicos por trás de "
        f"tópicos relacionados a {category}, mas não foi possível gerar uma explicação "
        "detalhada neste momento."
    )


__all__ = [
    "ClassificationResult",
    "DangerFinding",
    "classify",
    "explain_safely",
]
