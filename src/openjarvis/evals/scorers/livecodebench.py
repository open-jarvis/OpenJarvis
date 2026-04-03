"""LiveCodeBench scorer — sandboxed code execution with test cases.

Extracts code from model output, runs it against test cases in a
sandboxed subprocess with timeout and resource limits, and scores
based on pass/fail of each test case.

Reference: https://livecodebench.github.io/
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

# Execution limits
_TIMEOUT_SECONDS = 30
_MAX_OUTPUT_BYTES = 1024 * 1024  # 1 MB


def _extract_code(answer: str) -> str:
    """Extract Python code from model answer, handling markdown fences."""
    # Try markdown code fence first (```python ... ``` or ``` ... ```)
    fence_match = re.search(
        r"```(?:python|py)?\s*\n(.*?)```",
        answer,
        re.DOTALL,
    )
    if fence_match:
        return fence_match.group(1).strip()

    # Look for common code patterns (import, def, class, or I/O operations)
    lines = answer.strip().split("\n")
    code_lines: list[str] = []
    in_code = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith(
            (
                "def ",
                "class ",
                "from ",
                "import ",
                "n = ",
                "t = ",
                "for ",
                "while ",
                "input(",
                "sys.stdin",
                "print(",
            )
        ):
            in_code = True
        if in_code:
            code_lines.append(line)

    if code_lines:
        return "\n".join(code_lines)

    # Last resort: return the whole answer (it might be pure code)
    return answer.strip()


def _run_single_test(
    code: str,
    test_input: str,
    expected_output: str,
    timeout: int = _TIMEOUT_SECONDS,
) -> Tuple[bool, str]:
    """Run code in a subprocess with the given input, compare output.

    Returns (passed, detail_message).
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".py",
        delete=False,
    ) as f:
        f.write(code)
        f.flush()
        script_path = f.name

    try:
        result = subprocess.run(
            ["python3", script_path],
            input=test_input,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                **os.environ,
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )

        actual_output = result.stdout.strip()
        expected_stripped = expected_output.strip()

        if result.returncode != 0:
            stderr_preview = result.stderr[:500] if result.stderr else ""
            return False, f"runtime_error (exit {result.returncode}): {stderr_preview}"

        if actual_output == expected_stripped:
            return True, "exact_match"

        # Try line-by-line comparison (ignore trailing whitespace per line)
        actual_lines = [line.rstrip() for line in actual_output.split("\n")]
        expected_lines = [line.rstrip() for line in expected_stripped.split("\n")]
        if actual_lines == expected_lines:
            return True, "match_after_strip"

        # Numeric tolerance comparison for floating point outputs
        if _numeric_match(actual_output, expected_stripped):
            return True, "numeric_match"

        return False, (
            f"wrong_answer: expected={expected_stripped[:200]!r}, "
            f"got={actual_output[:200]!r}"
        )

    except subprocess.TimeoutExpired:
        return False, f"timeout ({timeout}s)"
    except Exception as exc:
        return False, f"execution_error: {exc}"
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def _numeric_match(actual: str, expected: str, rel_tol: float = 1e-6) -> bool:
    """Check if outputs match numerically (for floating point problems)."""
    actual_parts = actual.split()
    expected_parts = expected.split()
    if len(actual_parts) != len(expected_parts):
        return False
    for a, e in zip(actual_parts, expected_parts):
        try:
            a_f = float(a)
            e_f = float(e)
            if e_f == 0.0:
                if abs(a_f) > rel_tol:
                    return False
            elif abs(a_f - e_f) / max(abs(e_f), 1e-15) > rel_tol:
                return False
        except ValueError:
            if a != e:
                return False
    return True


class LiveCodeBenchScorer(Scorer):
    """Score LiveCodeBench problems by running code against test cases.

    Executes model-generated code in a sandboxed subprocess with stdin/stdout
    test cases. Each test case is run independently with a timeout.
    """

    scorer_id = "livecodebench"

    def __init__(self, judge_backend=None, judge_model: str = "") -> None:
        # Accept same constructor args as LLMJudgeScorer for CLI compatibility
        # but test execution does not need an LLM judge
        pass

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        test_inputs: List[str] = record.metadata.get("test_inputs", [])
        test_outputs: List[str] = record.metadata.get("test_outputs", [])

        if not test_inputs or not test_outputs:
            return None, {"reason": "no_test_cases"}

        if len(test_inputs) != len(test_outputs):
            LOGGER.warning(
                "Test input/output count mismatch for %s: %d inputs, %d outputs",
                record.record_id,
                len(test_inputs),
                len(test_outputs),
            )
            # Use the minimum count
            count = min(len(test_inputs), len(test_outputs))
            test_inputs = test_inputs[:count]
            test_outputs = test_outputs[:count]

        code = _extract_code(model_answer)
        if not code:
            return False, {"reason": "no_code_extracted"}

        # Determine per-test timeout from metadata or default
        time_limit = record.metadata.get("time_limit")
        timeout = _TIMEOUT_SECONDS
        if time_limit is not None:
            try:
                # time_limit is usually in seconds; add buffer
                timeout = max(int(float(str(time_limit))) * 2, 5)
                timeout = min(timeout, 60)  # cap at 60s
            except (ValueError, TypeError):
                pass

        passed = 0
        total = len(test_inputs)
        test_details: List[Dict[str, Any]] = []

        for i, (inp, expected) in enumerate(zip(test_inputs, test_outputs)):
            ok, detail = _run_single_test(code, inp, expected, timeout=timeout)
            if ok:
                passed += 1
            test_details.append(
                {
                    "test_index": i,
                    "passed": ok,
                    "detail": detail,
                }
            )

        if total == 0:
            return None, {"reason": "no_test_cases_after_filtering"}

        pass_rate = passed / total
        is_correct = passed == total

        meta: Dict[str, Any] = {
            "match_type": "test_execution",
            "tests_passed": passed,
            "tests_total": total,
            "pass_rate": pass_rate,
            "difficulty": record.metadata.get("difficulty", ""),
            "platform": record.metadata.get("platform", ""),
        }

        # Include first few test details (avoid bloating metadata)
        meta["test_details"] = test_details[:5]
        if len(test_details) > 5:
            meta["test_details_truncated"] = True

        return is_correct, meta


__all__ = ["LiveCodeBenchScorer"]
