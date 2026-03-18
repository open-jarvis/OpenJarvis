"""Tests for the coding_assistant scorer."""

from openjarvis.evals.core.types import EvalRecord
from openjarvis.evals.scorers.coding_assistant import CodingAssistantScorer


def _make_record(buggy_code, test_code, originally_failing, originally_passing):
    return EvalRecord(
        record_id="test-1",
        problem="Fix the bug",
        reference="",
        category="agentic",
        metadata={
            "buggy_code": buggy_code,
            "test_code": test_code,
            "originally_failing_tests": originally_failing,
            "originally_passing_tests": originally_passing,
        },
    )


def test_all_tests_fixed():
    buggy = "def add(a, b): return a - b"
    tests = (
        "from solution import add\n"
        "def test_basic(): assert add(1, 2) == 3\n"
        "def test_zero(): assert add(0, 0) == 0\n"
        "def test_neg(): assert add(-1, 1) == 0\n"
    )
    record = _make_record(
        buggy,
        tests,
        ["test_basic", "test_neg"],
        ["test_zero"],
    )
    scorer = CodingAssistantScorer()
    model_answer = "```python\ndef add(a, b): return a + b\n```"
    is_correct, meta = scorer.score(record, model_answer)
    assert meta["tests_fixed"] == 2
    assert meta["tests_to_fix"] == 2
    assert meta["regressions"] == 0
    assert meta["fix_rate"] == 1.0


def test_partial_fix():
    buggy = "def div(a, b): return a / b"
    tests = (
        "from solution import div\n"
        "def test_normal(): assert div(10, 2) == 5.0\n"
        "def test_zero(): assert div(0, 1) == 0.0\n"
    )
    record = _make_record(
        buggy,
        tests,
        ["test_zero_div"],  # not actually testable here
        ["test_normal", "test_zero"],
    )
    scorer = CodingAssistantScorer()
    model_answer = "```python\ndef div(a, b): return a / b\n```"
    is_correct, meta = scorer.score(record, model_answer)
    assert meta["fix_rate"] == 0.0


def test_empty_answer():
    record = _make_record("def f(): pass", "assert f() is None", [], [])
    scorer = CodingAssistantScorer()
    is_correct, meta = scorer.score(record, "")
    assert is_correct is False
    assert meta["reason"] == "empty_response"
