"""LiveCodeBench dataset provider — competitive programming code generation.

Loads problems from the LiveCodeBench HuggingFace dataset
(livecodebench/code_generation_lite) for evaluating code generation capability.

Reference: https://livecodebench.github.io/
           https://github.com/LiveCodeBench/LiveCodeBench
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any, Dict, Iterable, List, MutableMapping, Optional, Sequence

from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.splits import apply_split
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

_HF_DATASET = "livecodebench/code_generation_lite"
_HF_DATASET_FULL = "livecodebench/code_generation"
_DEFAULT_SPLIT = "test"

_PROMPT_TEMPLATE = """Solve the following competitive programming problem. Write a complete Python solution that reads from stdin and writes to stdout.

## Problem

{problem_statement}

## Input Format

{input_format}

## Output Format

{output_format}

## Constraints

{constraints}

## Examples

{examples}

Write ONLY the Python code solution. Do not include any explanations."""


def _format_examples(example_inputs: list, example_outputs: list) -> str:
    """Format input/output examples for the prompt."""
    parts = []
    for i, (inp, out) in enumerate(zip(example_inputs, example_outputs), 1):
        parts.append(f"Input {i}:\n{inp}\n\nOutput {i}:\n{out}")
    return "\n\n".join(parts) if parts else "No examples provided."


def _parse_json_field(value: Any) -> Any:
    """Parse a field that might be a JSON string or already parsed."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return value
    return value


class LiveCodeBenchDataset(DatasetProvider):
    """LiveCodeBench competitive programming benchmark.

    Loads problems from the LiveCodeBench HuggingFace dataset for
    evaluating code generation capability on fresh competitive
    programming problems from LeetCode, AtCoder, and CodeForces.
    """

    dataset_id = "livecodebench"
    dataset_name = "LiveCodeBench"

    def __init__(self) -> None:
        self._records: List[EvalRecord] = []

    def load(
        self,
        *,
        max_samples: Optional[int] = None,
        split: Optional[str] = None,
        seed: Optional[int] = None,
    ) -> None:
        from datasets import load_dataset

        use_split = (
            _DEFAULT_SPLIT
            if split in ("train", "test", "all") or split is None
            else split
        )

        # Try lite version first (smaller, faster download), fall back to full
        dataset = None
        for hf_path in [_HF_DATASET, _HF_DATASET_FULL]:
            try:
                dataset = load_dataset(hf_path, split=use_split)
                LOGGER.info("Loaded LiveCodeBench from %s (%s)", hf_path, use_split)
                break
            except Exception as exc:
                LOGGER.debug("Could not load %s: %s", hf_path, exc)

        if dataset is None:
            raise RuntimeError(
                "Failed to load LiveCodeBench dataset. "
                f"Tried: {_HF_DATASET}, {_HF_DATASET_FULL}. "
                "Ensure 'datasets' is installed and you have network access."
            )

        rows: Sequence[MutableMapping[str, object]]
        if hasattr(dataset, "to_list"):
            rows = dataset.to_list()
        else:
            rows = list(dataset)

        effective_seed = 42 if seed is None else seed
        if split in ("train", "test", "all"):
            rows = list(rows)
            rows = apply_split(rows, split=split, seed=effective_seed, train_frac=0.2)
        elif seed is not None:
            rng = random.Random(seed)
            rows = list(rows)
            rng.shuffle(rows)

        if max_samples is not None:
            rows = rows[:max_samples]

        self._records = []
        for idx, raw in enumerate(rows):
            record = self._convert_row(raw, idx)
            if record is not None:
                self._records.append(record)

        LOGGER.info("LiveCodeBench: loaded %d problems", len(self._records))

    def iter_records(self) -> Iterable[EvalRecord]:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def _convert_row(
        self,
        raw: MutableMapping[str, object],
        idx: int,
    ) -> Optional[EvalRecord]:
        # Extract problem statement — field names vary across dataset versions
        problem_text = str(
            raw.get("question_content")
            or raw.get("problem_description")
            or raw.get("question")
            or raw.get("problem")
            or ""
        ).strip()
        if not problem_text:
            LOGGER.debug("Skipping row %d: no problem text", idx)
            return None

        # Extract problem ID
        problem_id = str(
            raw.get("question_id")
            or raw.get("task_id")
            or raw.get("problem_id")
            or f"lcb-{idx}"
        )

        # Extract title
        title = str(
            raw.get("question_title") or raw.get("title") or raw.get("name") or ""
        ).strip()

        # Extract difficulty
        difficulty = str(
            raw.get("difficulty") or raw.get("question_difficulty") or ""
        ).strip()

        # Extract platform/source
        platform = str(
            raw.get("platform") or raw.get("source") or raw.get("contest_source") or ""
        ).strip()

        # Extract input/output format (may not always be separate fields)
        input_format = str(raw.get("input_format", "")).strip()
        output_format = str(raw.get("output_format", "")).strip()
        constraints = str(raw.get("constraints", "")).strip()

        # Extract test cases — various possible field names and formats
        test_inputs = _parse_json_field(raw.get("input", raw.get("test_inputs", [])))
        test_outputs = _parse_json_field(raw.get("output", raw.get("test_outputs", [])))
        public_test_cases = _parse_json_field(
            raw.get("public_test_cases", raw.get("sample_io", []))
        )
        hidden_test_cases = _parse_json_field(
            raw.get("hidden_test_cases", raw.get("test_cases", []))
        )

        # Normalize test cases into input/output lists
        all_test_inputs: List[str] = []
        all_test_outputs: List[str] = []

        # Process structured test cases (list of dicts with input/output keys)
        for cases in [public_test_cases, hidden_test_cases]:
            if isinstance(cases, list):
                for case in cases:
                    if isinstance(case, dict):
                        inp = str(case.get("input", "")).strip()
                        out = str(case.get("output", "")).strip()
                        if inp or out:
                            all_test_inputs.append(inp)
                            all_test_outputs.append(out)
                    elif isinstance(case, str):
                        # JSON-encoded test case
                        parsed = _parse_json_field(case)
                        if isinstance(parsed, dict):
                            inp = str(parsed.get("input", "")).strip()
                            out = str(parsed.get("output", "")).strip()
                            if inp or out:
                                all_test_inputs.append(inp)
                                all_test_outputs.append(out)

        # If no structured test cases, try the flat input/output lists
        if not all_test_inputs and isinstance(test_inputs, list):
            for inp in test_inputs:
                all_test_inputs.append(str(inp).strip())
        if not all_test_outputs and isinstance(test_outputs, list):
            for out in test_outputs:
                all_test_outputs.append(str(out).strip())

        # Build example section from public test cases (first 2)
        example_inputs = all_test_inputs[:2] if all_test_inputs else []
        example_outputs = all_test_outputs[:2] if all_test_outputs else []
        examples_str = _format_examples(example_inputs, example_outputs)

        # Build prompt
        problem = _PROMPT_TEMPLATE.format(
            problem_statement=problem_text,
            input_format=input_format or "(see problem statement)",
            output_format=output_format or "(see problem statement)",
            constraints=constraints or "(see problem statement)",
            examples=examples_str,
        )

        # Starter code (if available)
        starter_code = str(raw.get("starter_code", raw.get("code_stub", ""))).strip()

        # Metadata for scoring
        metadata: Dict[str, Any] = {
            "test_inputs": all_test_inputs,
            "test_outputs": all_test_outputs,
            "difficulty": difficulty,
            "platform": platform,
            "title": title,
        }
        if starter_code:
            metadata["starter_code"] = starter_code

        # Store raw data for any fields the scorer might need
        for key in ["time_limit", "memory_limit", "contest_id", "contest_date"]:
            val = raw.get(key)
            if val is not None:
                metadata[key] = val

        # Build subject from platform and difficulty
        subject = (
            f"{platform}/{difficulty}"
            if platform and difficulty
            else (platform or difficulty or "competitive-programming")
        )

        return EvalRecord(
            record_id=problem_id,
            problem=problem,
            reference="",  # No single reference answer; scored via test execution
            category="coding",
            subject=subject,
            metadata=metadata,
        )


__all__ = ["LiveCodeBenchDataset"]
