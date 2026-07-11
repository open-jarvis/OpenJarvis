"""Correctness verifier for orchestrator reasoning tasks (:mod:`.datasets`).

The verifier dispatches on :attr:`Task.domain`:

- **math** — normalize and compare. Extract ``\\boxed{...}`` from both sides,
  try ``sympy`` for symbolic / numeric equality, and fall back to a normalized
  string / number match. No network.
- **code** — best-effort: if a short expected output / answer exists, do a
  normalized substring match; otherwise defer to the LLM judge. (We don't run
  arbitrary code here.)
- **science / medical / chat / misc / unknown** — Gemini LLM judge given the
  question + gold answer + candidate, asked for ``PASS`` / ``FAIL``. When no
  ``GEMINI_API_KEY`` is set (e.g. offline tests) it falls back to a normalized
  string / token-F1 >= 0.6 match.

The OpenAI key is dead, so the LLM judge talks to Gemini through its
OpenAI-compatible endpoint. Normalization helpers are copied (not imported)
from ``hotpotqa.py`` to keep this module self-contained.
"""

from __future__ import annotations

import os
import re
import string
from typing import Any, Callable, Dict, Optional

from .datasets import Task

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
GEMINI_MODEL = "gemini-2.5-flash"
# LLM judge model. Switched from Gemini (free-tier rate limit stalled parallel gen)
# to Anthropic Haiku: fast (~0.6s), direct PASS/FAIL, high rate limits.
JUDGE_MODEL = "claude-haiku-4-5-20251001"
# Reused across calls — creating a fresh Anthropic client per judge call leaks an
# httpx connection pool (CLOSE-WAIT pileup under parallel generation). Thread-safe.
_JUDGE_CLIENT = None


# --- normalization (copied from hotpotqa.py — keep self-contained) -----------


def _normalize_answer(s: str) -> str:
    """Lowercase, strip punctuation / articles / extra whitespace (SQuAD/HotpotQA)."""
    s = s.lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def _f1(pred: str, gold: str) -> float:
    pt, gt = _normalize_answer(pred).split(), _normalize_answer(gold).split()
    if not pt or not gt:
        return float(pt == gt)
    common: Dict[str, int] = {}
    for w in pt:
        if w in gt:
            common[w] = common.get(w, 0) + 1
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pt)
    recall = num_same / len(gt)
    return 2 * precision * recall / (precision + recall)


def _string_or_f1(prediction: str, gold: str, *, f1_threshold: float = 0.6) -> bool:
    """Normalized whole-word substring OR token-F1 >= threshold."""
    np_, ng = _normalize_answer(prediction), _normalize_answer(gold)
    if not ng:
        return False
    if f" {ng} " in f" {np_} ":
        return True
    return _f1(prediction, gold) >= f1_threshold


# --- math --------------------------------------------------------------------

_BOXED_RE = re.compile(r"\\boxed\{")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _extract_boxed(text: str) -> Optional[str]:
    """Return the contents of the last ``\\boxed{...}`` (brace-balanced)."""
    last = None
    for m in _BOXED_RE.finditer(text):
        start = m.end()
        depth = 1
        i = start
        while i < len(text) and depth > 0:
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            i += 1
        if depth == 0:
            last = text[start : i - 1].strip()
    return last


def _clean_math(s: str) -> str:
    s = s.strip()
    boxed = _extract_boxed(s)
    if boxed is not None:
        s = boxed
    # Common LaTeX wrappers / delimiters.
    s = s.replace("$", "").replace("\\!", "").replace("\\,", "").replace("\\;", "")
    s = s.replace("\\left", "").replace("\\right", "")
    s = s.strip().strip("$ ")
    return s


def _to_float(s: str) -> Optional[float]:
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    m = _NUM_RE.search(s)
    if m:
        try:
            return float(m.group(0))
        except ValueError:
            return None
    return None


def _math_equal(prediction: str, gold: str) -> bool:
    pred = _clean_math(prediction)
    g = _clean_math(gold)
    if not g:
        return False

    # Exact normalized-string shortcut.
    if pred.replace(" ", "") == g.replace(" ", "") and pred:
        return True

    # Numeric comparison (handles "42" vs "42.0" vs trailing prose).
    pf, gf = _to_float(pred), _to_float(g)
    if pf is not None and gf is not None:
        if abs(pf - gf) <= 1e-6 * max(1.0, abs(gf)):
            return True

    # NOTE: a sympy/parse_latex symbolic-equality block used to live here, but
    # sympy.simplify / antlr parse_latex can hang on pathological \boxed{} answers
    # while holding the GIL -> deadlocks the whole threaded rejection sampler
    # (all worker threads freeze in futex_wait, server goes idle, 0 records).
    # Symbolic equivalence is now deferred to the Gemini judge in verify_answer().

    # Last resort: whole-word substring of the gold in the prediction.
    return _string_or_f1(prediction, g, f1_threshold=0.9)


# --- LLM judge (Gemini, OpenAI-compatible) -----------------------------------


def _gemini_judge(task: Task, prediction: str) -> Optional[bool]:
    """Ask Gemini PASS/FAIL. Returns None if unavailable (caller falls back)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
    except Exception:
        return None

    try:
        # Judge = Anthropic Haiku (fast ~0.6s, direct PASS/FAIL, high rate limits).
        # Switched off the Gemini judge: its free-tier rate limit + SDK retry/backoff
        # blocked worker threads for minutes under parallel generation and stalled
        # the run. Fail-fast (no retries, short timeout): on error return None and the
        # caller falls back to string/f1.
        global _JUDGE_CLIENT
        if _JUDGE_CLIENT is None:
            _JUDGE_CLIENT = anthropic.Anthropic(
                api_key=api_key, max_retries=0, timeout=15
            )
        client = _JUDGE_CLIENT
        prompt = (
            "You are grading a candidate answer against a gold reference.\n"
            "Reply with exactly one word: PASS if the candidate is correct and "
            "consistent with the gold answer, otherwise FAIL.\n\n"
            f"Question:\n{task.question}\n\n"
            f"Gold answer:\n{task.answer}\n\n"
            f"Candidate answer:\n{prediction}\n\n"
            "Verdict (PASS or FAIL):"
        )
        resp = client.messages.create(
            model=JUDGE_MODEL,
            max_tokens=8,
            messages=[{"role": "user", "content": prompt}],
        )
        verdict = (resp.content[0].text or "").strip().upper()
        if "PASS" in verdict:
            return True
        if "FAIL" in verdict:
            return False
        return None
    except Exception:
        return None


# --- public API --------------------------------------------------------------


def verify_answer(task: Task, prediction: str) -> bool:
    """Domain-dispatched correctness check for ``prediction`` vs ``task.answer``."""
    pred = (prediction or "").strip()
    if not pred or not (task.answer or "").strip():
        return False

    domain = (task.domain or "").lower()

    if domain == "math":
        # string + numeric + f1 only. sympy removed (GIL-deadlocked the threaded
        # sampler); Gemini judge NOT used here either (32 tasks x N samples of math
        # judge calls throttle Gemini and stall the whole run). Accept slightly lower
        # math yield for a fast, hang-free verifier.
        return _math_equal(pred, task.answer)

    if domain == "code":
        # Best-effort: short gold -> normalized substring; otherwise LLM judge.
        gold = task.answer.strip()
        if len(gold) <= 200:
            if _string_or_f1(pred, gold, f1_threshold=0.8):
                return True
        judged = _gemini_judge(task, pred)
        if judged is not None:
            return judged
        return _string_or_f1(pred, gold, f1_threshold=0.6)

    # science / medical / chat / misc / unknown -> LLM judge, then F1 fallback.
    judged = _gemini_judge(task, pred)
    if judged is not None:
        return judged
    return _string_or_f1(pred, task.answer, f1_threshold=0.6)


def make_verifier() -> Callable[[Any, Any], bool]:
    """Return ``verify_fn(task, rollout) -> bool`` for the rejection sampler."""

    def verify(task: Any, rollout: Any) -> bool:
        ans = getattr(rollout, "final_answer", "") or ""
        return verify_answer(task, ans)

    return verify


__all__ = [
    "GEMINI_BASE_URL",
    "GEMINI_MODEL",
    "make_verifier",
    "verify_answer",
]
