"""coding_assistant scorer — test-based evaluation of bug fixes.

Extracts fixed code from model output, runs the test suite, and computes:
- fix_rate: fraction of originally-failing tests now passing
- regressions: count of originally-passing tests that broke
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)


def _extract_code(answer: str) -> str:
    """Extract Python code from model answer, handling markdown fences."""
    fence_match = re.search(
        r"```(?:python)?\s*\n(.*?)```",
        answer,
        re.DOTALL,
    )
    if fence_match:
        return fence_match.group(1).strip()

    lines = answer.strip().split("\n")
    code_lines = []
    in_code = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(("def ", "class ", "from ", "import ")):
            in_code = True
        if in_code:
            code_lines.append(line)

    return "\n".join(code_lines) if code_lines else answer.strip()


def _extract_test_functions(test_code: str) -> Dict[str, str]:
    """Parse test code into individual test functions by name."""
    tests: Dict[str, str] = {}
    current_name: Optional[str] = None
    current_lines: list[str] = []
    preamble: list[str] = []

    for line in test_code.split("\n"):
        stripped = line.strip()
        if stripped.startswith("def test_"):
            if current_name:
                tests[current_name] = "\n".join(preamble + current_lines)
            match = re.match(r"def (test_\w+)", stripped)
            current_name = match.group(1) if match else None
            current_lines = [line]
        elif current_name is not None:
            if (
                line.strip()
                and not line.startswith((" ", "\t"))
                and not stripped.startswith("#")
            ):
                # New top-level definition — end of current test
                tests[current_name] = "\n".join(preamble + current_lines)
                current_name = None
                current_lines = []
                # Check if this is a new test
                if stripped.startswith("def test_"):
                    match = re.match(r"def (test_\w+)", stripped)
                    current_name = match.group(1) if match else None
                    current_lines = [line]
                else:
                    preamble.append(line)
            else:
                current_lines.append(line)
        else:
            preamble.append(line)

    if current_name:
        tests[current_name] = "\n".join(preamble + current_lines)

    return tests


def _run_single_test(code: str, test_code: str) -> bool:
    """Run a single test function against the given code. Returns True if passes."""
    # Make the code importable as 'solution'
    import types

    mod = types.ModuleType("solution")
    try:
        exec(code, mod.__dict__)  # noqa: S102
    except Exception:
        return False

    import sys

    sys.modules["solution"] = mod
    try:
        exec(test_code, {"__name__": "__main__"})  # noqa: S102
        return True
    except Exception:
        return False
    finally:
        sys.modules.pop("solution", None)


class CodingAssistantScorer(Scorer):
    """Score coding assistant bug fixes by test execution."""

    scorer_id = "coding_assistant"

    def __init__(self, judge_backend=None, judge_model: str = "") -> None:
        pass

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        test_code = record.metadata.get("test_code", "")
        originally_failing = record.metadata.get("originally_failing_tests", [])
        originally_passing = record.metadata.get("originally_passing_tests", [])

        if not test_code:
            return None, {"reason": "no_test_code"}

        fixed_code = _extract_code(model_answer)
        if not fixed_code:
            return False, {"reason": "no_code_extracted"}

        # Parse individual tests
        test_fns = _extract_test_functions(test_code)

        # Run each test with the fixed code
        tests_fixed = 0
        tests_to_fix = len(originally_failing)
        regressions = 0
        test_results: Dict[str, bool] = {}

        for name, fn_code in test_fns.items():
            passed = _run_single_test(fixed_code, fn_code)
            test_results[name] = passed

            if name in originally_failing and passed:
                tests_fixed += 1
            elif name in originally_passing and not passed:
                regressions += 1

        fix_rate = tests_fixed / tests_to_fix if tests_to_fix > 0 else 1.0
        total_passing = sum(1 for v in test_results.values() if v)
        total_tests = len(test_results)

        is_correct = fix_rate == 1.0 and regressions == 0

        return is_correct, {
            "match_type": "test_execution",
            "tests_fixed": tests_fixed,
            "tests_to_fix": tests_to_fix,
            "regressions": regressions,
            "fix_rate": fix_rate,
            "total_passing": total_passing,
            "total_tests": total_tests,
            "test_results": test_results,
        }


__all__ = ["CodingAssistantScorer"]
