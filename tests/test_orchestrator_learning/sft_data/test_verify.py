"""Offline tests for the answer verifier.

Math and code paths run with no network. The Gemini judge is only reachable for
non-math/code domains; we monkeypatch ``_gemini_judge`` (or rely on its no-key
fallback) so nothing hits the network.
"""

from __future__ import annotations

from openjarvis.learning.intelligence.orchestrator.sft_data import verify as V
from openjarvis.learning.intelligence.orchestrator.sft_data.datasets import Task
from openjarvis.learning.intelligence.orchestrator.sft_data.verify import (
    make_verifier,
    verify_answer,
)


def _math(answer: str) -> Task:
    return Task(task_id="m", question="q", answer=answer, domain="math")


def test_math_boxed_vs_plain_true():
    assert verify_answer(_math("42"), "\\boxed{42}") is True


def test_math_boxed_both_sides():
    assert verify_answer(_math("\\boxed{42}"), "The answer is \\boxed{42}") is True


def test_math_wrong_number_false():
    assert verify_answer(_math("42"), "41") is False


def test_math_numeric_float_match():
    assert verify_answer(_math("42"), "42.0") is True


def test_math_symbolic_equivalence():
    # x^2 + 2x + 1 == (x+1)^2 via sympy (skips gracefully if sympy absent).
    t = _math("(x+1)^2")
    assert verify_answer(t, "x^2 + 2*x + 1") is True


def test_empty_prediction_false():
    assert verify_answer(_math("42"), "") is False


def test_code_short_gold_substring():
    t = Task(task_id="c", question="print hi", answer="hello", domain="code")
    assert verify_answer(t, "the output is hello") is True


def test_code_falls_back_to_judge(monkeypatch):
    # Long gold + no substring match -> hits judge; monkeypatch to PASS.
    monkeypatch.setattr(V, "_gemini_judge", lambda task, pred: True)
    t = Task(
        task_id="c",
        question="solve",
        answer="x" * 300,  # long -> skips substring shortcut
        domain="code",
    )
    assert verify_answer(t, "totally different") is True


def test_judge_domain_uses_gemini(monkeypatch):
    calls = {}

    def fake_judge(task, pred):
        calls["hit"] = (task.domain, pred)
        return True

    monkeypatch.setattr(V, "_gemini_judge", fake_judge)
    t = Task(task_id="s", question="q", answer="Oxygen", domain="science")
    assert verify_answer(t, "plants release oxygen") is True
    assert calls["hit"][0] == "science"


def test_judge_domain_fallback_f1_when_no_key(monkeypatch):
    # Judge unavailable (returns None) -> falls back to string / F1.
    monkeypatch.setattr(V, "_gemini_judge", lambda task, pred: None)
    t = Task(task_id="s", question="q", answer="the capital is paris", domain="misc")
    assert verify_answer(t, "I think the capital is paris indeed") is True
    assert verify_answer(t, "completely unrelated text here") is False


def test_make_verifier_reads_final_answer(monkeypatch):
    monkeypatch.setattr(V, "_gemini_judge", lambda task, pred: None)
    verify = make_verifier()

    class Rollout:
        final_answer = "\\boxed{42}"

    assert verify(_math("42"), Rollout()) is True

    class BadRollout:
        final_answer = "999"

    assert verify(_math("42"), BadRollout()) is False


def test_make_verifier_missing_final_answer():
    verify = make_verifier()

    class Empty:
        pass

    assert verify(_math("42"), Empty()) is False
