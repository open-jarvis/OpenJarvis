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

import logging
import os
import re
import string
from typing import Any, Callable, Dict, Optional

from .datasets import Task

# LLM judge model. Switched from Gemini (free-tier rate limit stalled parallel gen)
# to Anthropic Haiku: fast (~0.6s), direct PASS/FAIL, high rate limits.
LOGGER = logging.getLogger(__name__)

JUDGE_MODEL = "claude-haiku-4-5-20251001"
# The Anthropic SDK's own retry does exponential backoff and honours Retry-After.
# A judge call that waits a few seconds beats a silently-wrong label.
JUDGE_MAX_RETRIES = 6
# Reused across calls — creating a fresh Anthropic client per judge call leaks an
# httpx connection pool (CLOSE-WAIT pileup under parallel generation). Thread-safe.
_JUDGE_CLIENT = None
# Every swallowed judge error, so a run can never again silently mislabel while
# reporting a clean bill of health.
_JUDGE_FAILURES: list[str] = []


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


# \frac{a}{b} / \dfrac{a}{b} / \tfrac{a}{b}  ->  (a)/(b)
_FRAC_RE = re.compile(r"\\[dt]?frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}")


def _clean_math(s: str) -> str:
    s = s.strip()
    boxed = _extract_boxed(s)
    if boxed is not None:
        s = boxed
    # Common LaTeX wrappers / delimiters.
    s = s.replace("$", "").replace("\\!", "").replace("\\,", "").replace("\\;", "")
    s = s.replace("\\left", "").replace("\\right", "")
    # Normalize LaTeX fractions to plain division. Without this, `\frac{15}{64}`
    # never becomes `15/64`, the exact/numeric comparisons both fail, and we fall
    # through to a crude "grab the first number" match — which reads `15` out of
    # BOTH sides and returns True. That is a FALSE POSITIVE: it passed
    #     gold \frac{15}{64}  vs  model 15/99   (different fraction)
    #     gold \frac{1}{2}    vs  model 1/3     (different denominator)
    #     gold \frac{15}{64}  vs  model 15      (just the numerator)
    # i.e. any wrong answer sharing a numerator with the gold was marked CORRECT
    # and fed into training. It also caused the mirror false-negative
    # (`-\dfrac{73}{143}` vs `-73/143`), because the minus sits outside the frac
    # and the number-grab loses it. (Audit 2026-07-13.)
    for _ in range(3):  # nested fractions
        s, n = _FRAC_RE.subn(r"(\1)/(\2)", s)
        if not n:
            break
    s = s.strip().strip("$ ")
    return s


# A pure rational expression: -73/143, (15)/(64), 3.5/2 — safe to evaluate.
_RATIONAL_RE = re.compile(r"^-?\(?\s*-?\d+(?:\.\d+)?\s*\)?\s*/\s*\(?\s*-?\d+(?:\.\d+)?\s*\)?$")


def _to_float(s: str) -> Optional[float]:
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except (ValueError, TypeError):
        pass
    # Evaluate a plain fraction rather than falling through to the number-grab
    # below, which would read only the NUMERATOR and happily equate 15/64 with
    # 15/99. Restricted by regex to digits and one '/', so nothing else is eval'd.
    if _RATIONAL_RE.match(s):
        try:
            num, den = s.replace("(", "").replace(")", "").split("/")
            d = float(den)
            if d != 0:
                return float(num) / d
        except (ValueError, ZeroDivisionError):
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


def _judge_route() -> Optional[tuple]:
    """(base_url, api_key, model) for the judge — OpenRouter if configured.

    The judge must NOT share a rate-limit bucket with the orchestrator. They're
    the same model (Haiku), but the orchestrator makes 5-10 calls per rollout and
    the judge makes 1; when they contend, the judge 429s, returns None, and the
    caller falls back to string matching — silently marking correct answers WRONG.
    Set ``OJ_JUDGE_VIA_OPENROUTER=1`` to give the judge its own quota (~$2.50 per
    3000 rollouts).
    """
    if os.environ.get("OJ_JUDGE_VIA_OPENROUTER") == "1":
        key = os.environ.get("OPENROUTER_API_KEY")
        if key:
            return ("https://openrouter.ai/api/v1", key, "anthropic/claude-haiku-4.5")
    key = os.environ.get("ANTHROPIC_API_KEY")
    return ("https://api.anthropic.com/v1/", key, JUDGE_MODEL) if key else None


def _gemini_judge(task: Task, prediction: str) -> Optional[bool]:
    """Ask the LLM judge PASS/FAIL. Returns None if unavailable (caller falls back)."""
    route = _judge_route()
    if route is None:
        return None
    base_url, api_key, model = route
    try:
        from openai import OpenAI  # OpenAI-compatible: works for both routes
    except Exception:
        return None

    try:
        # Judge = Haiku (fast ~0.6s, direct PASS/FAIL), reached over whichever route
        # _judge_route() picked.
        #
        # This used to be fail-fast (max_retries=0, timeout=15) so a slow judge
        # couldn't stall the threaded sampler. That was actively destroying data:
        # under parallel generation the judge 429s, this returns None, the caller
        # falls back to string/f1, and a CORRECT answer gets marked WRONG. The
        # failure is invisible — the exception is swallowed and never logged, so
        # the run reports "0 rate limits" while silently mislabelling.
        # (Audit 2026-07-12: 3 consecutive judge calls at concurrency 100 -> 2x429.)
        #
        # Retries alone were NOT enough: with the judge on the same bucket as the
        # orchestrator, the retries just parked every worker thread in backoff and
        # stalled the run. The real fix is giving the judge its own quota
        # (OJ_JUDGE_VIA_OPENROUTER=1); retries are the belt to that suspenders.
        global _JUDGE_CLIENT
        if _JUDGE_CLIENT is None:
            _JUDGE_CLIENT = OpenAI(
                base_url=base_url,
                api_key=api_key,
                max_retries=JUDGE_MAX_RETRIES,
                timeout=30,
            )
        client = _JUDGE_CLIENT
        # Grade on SEMANTIC equivalence, not surface form. The bare "correct and
        # consistent with the gold" instruction was far too strict: an audit
        # (2026-07-12) found ~half of all FAIL verdicts were correct answers the
        # judge rejected purely for phrasing —
        #   gold "0"                  vs "Order w.r.t. A = 1; Order w.r.t. B = 0"
        #   gold "use plt.figtext()"  vs "Use fig.text()"      (same matplotlib call)
        #   gold "<terse fragment>"   vs the same fact in a full sentence
        # Those FAILs silently threw away good training data. The guardrails at the
        # bottom keep it from swinging lenient: a different VALUE still fails.
        prompt = (
            "You are grading a candidate answer against a gold reference.\n\n"
            "The gold is often TERSE — a single word ('Yes'), a bare value ('0'), a "
            "compact expression ('4 > 3 > 1 > 2'). The candidate is typically a full "
            "sentence that states the same thing and adds correct supporting detail. "
            "That is a PASS.\n\n"
            "Your ONLY question is: does the candidate AGREE with the gold on the "
            "point the gold makes?\n\n"
            "PASS when:\n"
            "  * the candidate says the same thing more verbosely, or explains it;\n"
            "  * it uses different notation, exactly-converting units, or equivalent "
            "mathematical form (15/64 vs \\frac{15}{64});\n"
            "  * the gold is a fragment and the candidate states the same fact in "
            "prose, or answers additional parts of the question as well;\n"
            "  * for code: a different but equivalent implementation, or a different "
            "API call with the same effect.\n\n"
            "Do NOT fail the candidate merely for saying MORE than the gold, for "
            "being longer, for adding a derivation, or for answering other parts of "
            "the question too. Extra correct detail is never a reason to fail.\n\n"
            "FAIL only when the candidate gives a DIFFERENT VALUE, contradicts the "
            "gold, or does not actually answer the question.\n\n"
            f"Question:\n{task.question}\n\n"
            f"Gold answer:\n{task.answer}\n\n"
            f"Candidate answer:\n{prediction}\n\n"
            "Reply with exactly one word — PASS or FAIL.\nVerdict:"
        )
        # temperature=0: a grader must be DETERMINISTIC. Without it the SDK default
        # (1.0) sampled the PASS/FAIL token, so the same (question, gold, candidate)
        # could be graded differently on two runs — the label became a coin flip on
        # any borderline answer. (Audit 2026-07-13: gold "0" vs "order w.r.t. B is 0"
        # graded PASS in one run and FAIL in the next.)
        resp = client.chat.completions.create(
            model=model,
            max_tokens=8,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
        )
        verdict = (resp.choices[0].message.content or "").strip().upper()
        if "PASS" in verdict:
            return True
        if "FAIL" in verdict:
            return False
        return None
    except Exception as exc:  # noqa: BLE001
        # LOUDLY. Swallowing this silently is how a rate-limited judge quietly
        # mislabelled correct answers as wrong for a whole run while the monitor
        # cheerfully reported "0 rate limits" — the exception never reached a log.
        _JUDGE_FAILURES.append(type(exc).__name__)
        LOGGER.warning(
            "JUDGE CALL FAILED (%d so far this run) — falling back to string match, "
            "which will likely mark a correct answer WRONG: %s",
            len(_JUDGE_FAILURES),
            str(exc)[:160],
        )
        return None


# --- public API --------------------------------------------------------------


# The orchestrator is instructed to end with "FINAL_ANSWER: <answer>", so the raw
# rollout text is "<reasoning…>\n\nFINAL_ANSWER: A". Everything before the marker
# (and the marker itself) must come off before we compare, or we're matching the
# model's prose against a one-token gold.
_FINAL_ANSWER_RE = re.compile(r"(?im)FINAL[_\s]?ANSWER\s*:?")


def _answer_only(prediction: str) -> str:
    """The text AFTER the last FINAL_ANSWER marker (or the whole thing if absent).

    Without this, ``_math_equal("FINAL_ANSWER: A", "A")`` is False while
    ``_math_equal("A", "A")`` is True — the literal marker was never stripped, so
    every short non-numeric answer (multiple-choice letters, symbolic values) was
    auto-marked WRONG. Numeric answers happened to survive via float parsing,
    which is why this hid for so long. (audit 2026-07-12)
    """
    marks = list(_FINAL_ANSWER_RE.finditer(prediction))
    return (prediction[marks[-1].end() :] if marks else prediction).strip()


def verify_answer(task: Task, prediction: str) -> bool:
    """Domain-dispatched correctness check for ``prediction`` vs ``task.answer``."""
    pred = _answer_only(prediction or "")
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
    "make_verifier",
    "verify_answer",
]
