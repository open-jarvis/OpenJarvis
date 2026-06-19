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

    # Symbolic / exact equality via sympy when available.
    try:
        import sympy
        from sympy.parsing.latex import parse_latex  # noqa: F401  (optional)

        def _parse(x: str):
            try:
                return sympy.sympify(x.replace("^", "**"))
            except Exception:
                try:
                    return sympy.parsing.latex.parse_latex(x)
                except Exception:
                    return None

        pe, ge = _parse(pred), _parse(g)
        if pe is not None and ge is not None:
            try:
                if sympy.simplify(pe - ge) == 0:
                    return True
            except Exception:
                pass
    except Exception:
        pass

    # Last resort: whole-word substring of the gold in the prediction.
    return _string_or_f1(prediction, g, f1_threshold=0.9)


# --- LLM judge (Gemini, OpenAI-compatible) -----------------------------------


def _gemini_judge(task: Task, prediction: str) -> Optional[bool]:
    """Ask Gemini PASS/FAIL. Returns None if unavailable (caller falls back)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None

    try:
        client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)
        prompt = (
            "You are grading a candidate answer against a gold reference.\n"
            "Reply with exactly one word: PASS if the candidate is correct and "
            "consistent with the gold answer, otherwise FAIL.\n\n"
            f"Question:\n{task.question}\n\n"
            f"Gold answer:\n{task.answer}\n\n"
            f"Candidate answer:\n{prediction}\n\n"
            "Verdict (PASS or FAIL):"
        )
        resp = client.chat.completions.create(
            model=GEMINI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=8,
        )
        verdict = (resp.choices[0].message.content or "").strip().upper()
        if "PASS" in verdict:
            return True
        if "FAIL" in verdict:
            return False
        return None
    except Exception:
        return None


# --- public API --------------------------------------------------------------


def verify_answer(task: Task, prediction: str) -> bool:
    """Domain-dispatched correctness check for ``prediction`` against ``task.answer``."""
    pred = (prediction or "").strip()
    if not pred or not (task.answer or "").strip():
        return False

    domain = (task.domain or "").lower()

    if domain == "math":
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
