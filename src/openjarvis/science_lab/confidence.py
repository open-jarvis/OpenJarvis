"""Confidence scoring and rendering for Science Lab results.

No existing convention to reuse here (confirmed during exploration) — this is
new code. Confidence is a plain 0.0-1.0 float (matching the rest of the
codebase's convention, e.g. ``DigestArtifact.quality_score``), always paired
with a short stated basis so it is never presented as bare certainty.
"""

from __future__ import annotations

from typing import List

from openjarvis.science_lab.models import (
    BASIS_CALCULATED,
    BASIS_EXPERIMENTAL,
    ConfidenceScore,
    Hypothesis,
    PropertyAnalysis,
    SimulationResult,
)


def score_confidence(
    analysis: PropertyAnalysis,
    hypotheses: List[Hypothesis],
    simulations: List[SimulationResult],
    *,
    default_basis: str = "heuristic: corroborating calculations + hypothesis spread",
) -> ConfidenceScore:
    """Heuristic confidence score.

    Starts at a low base and is nudged up by signals that make the answer
    more trustworthy, nudged down by signals that make it less so:

    - each ``SimulationResult`` with a calculated/experimental basis raises
      confidence a little (a purely-hypothesis-only answer stays lower);
    - having at least 2 target properties identified raises confidence
      slightly (the objective was concrete enough to decompose);
    - having many competing hypotheses (>3) lowers confidence slightly
      (more disagreement/uncertainty about the right mechanism);
    - the score is always clamped to [0.0, 1.0].

    This is a documented heuristic, not a calibrated probability — the
    ``basis`` string on the result should always be read alongside the
    number.
    """
    score = 0.3  # base: "some analysis was done"

    if len(analysis.target_properties) >= 2:
        score += 0.1

    strong_simulations = sum(
        1 for s in simulations if s.basis in (BASIS_CALCULATED, BASIS_EXPERIMENTAL)
    )
    score += min(0.4, 0.1 * strong_simulations)

    if hypotheses:
        if len(hypotheses) <= 3:
            score += 0.15
        else:
            score -= 0.05

    score = max(0.0, min(1.0, score))
    return ConfidenceScore(value=round(score, 2), basis=default_basis)


def render_confidence_bar(score: float, width: int = 10) -> str:
    """Render a ``"████████░░ 80%"``-style progress bar for CLI/voice output."""
    if not (0.0 <= score <= 1.0):
        raise ValueError("score must be between 0.0 and 1.0")
    filled = round(score * width)
    filled = max(0, min(width, filled))
    bar = "█" * filled + "░" * (width - filled)
    pct = round(score * 100)
    return f"{bar} {pct}%"


__all__ = ["render_confidence_bar", "score_confidence"]
