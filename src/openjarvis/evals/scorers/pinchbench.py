"""PinchBench grading helpers and scorer.

Provides transcript translation (OpenJarvis events → PinchBench format),
automated grading (exec of embedded Python), LLM judge grading, and
hybrid combination. Used by PinchBenchTaskEnv.run_tests() and the
standalone PinchBenchScorer.

Reference: https://github.com/pinchbench/skill
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.event_recorder import EventType
from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool name mapping: OpenJarvis name → PinchBench-expected name
# ---------------------------------------------------------------------------
_TOOL_NAME_MAP: Dict[str, str] = {
    "file_read": "read_file",
    "file_write": "write_file",
    "image_generate": "generate_image",
    # web_search, calculator, shell_exec, etc. use the same names
}


# ---------------------------------------------------------------------------
# Transcript translation
# ---------------------------------------------------------------------------


def events_to_transcript(events: List[Any]) -> List[Dict[str, Any]]:
    """Build PinchBench-format transcript from raw EventRecorder events.

    Pairs TOOL_CALL_START/END events to extract tool name, arguments, and
    results. Called by run_tests() before QueryTrace exists.
    """
    transcript: List[Dict[str, Any]] = []

    for event in events:
        etype = event.event_type
        if isinstance(etype, str):
            # Normalize string event types to enum comparison
            pass
        if (
            etype == EventType.TOOL_CALL_START
            or etype == EventType.TOOL_CALL_START.value
        ):
            tool_name = event.metadata.get("tool", "unknown")
            mapped = _TOOL_NAME_MAP.get(tool_name, tool_name)
            arguments = event.metadata.get("arguments") or {}
            transcript.append(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "toolCall", "name": mapped, "params": arguments}
                        ],
                    },
                }
            )
        elif etype == EventType.TOOL_CALL_END or etype == EventType.TOOL_CALL_END.value:
            result_text = str(event.metadata.get("result", ""))
            transcript.append(
                {
                    "type": "message",
                    "message": {
                        "role": "toolResult",
                        "content": [{"text": result_text}],
                    },
                }
            )

    return transcript


def _trace_to_transcript(trace: Any) -> List[Dict[str, Any]]:
    """Convert QueryTrace to PinchBench transcript (for EvalRunner path)."""
    transcript: List[Dict[str, Any]] = []
    for turn in trace.turns:
        for tc in getattr(turn, "tool_calls", []):
            if tc is None:
                continue
            mapped = _TOOL_NAME_MAP.get(tc["name"], tc["name"])
            transcript.append(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "toolCall",
                                "name": mapped,
                                "params": tc.get("arguments") or {},
                            }
                        ],
                    },
                }
            )
            transcript.append(
                {
                    "type": "message",
                    "message": {
                        "role": "toolResult",
                        "content": [{"text": tc.get("result", "")}],
                    },
                }
            )

    # Capture final assistant text response (for tasks graded on text output)
    response_text = getattr(trace, "response_text", "")
    if response_text:
        transcript.append(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": response_text}],
                },
            }
        )
    return transcript


def _tool_results_to_transcript(
    tool_results: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build transcript from JarvisAgentBackend tool_results list."""
    transcript: List[Dict[str, Any]] = []
    for tr in tool_results:
        tool_name = tr.get("tool_name", "unknown")
        mapped = _TOOL_NAME_MAP.get(tool_name, tool_name)
        transcript.append(
            {
                "type": "message",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": mapped,
                            "params": tr.get("arguments", {}),
                        }
                    ],
                },
            }
        )
        transcript.append(
            {
                "type": "message",
                "message": {
                    "role": "toolResult",
                    "content": [{"text": tr.get("content", "")}],
                },
            }
        )
    return transcript


# ---------------------------------------------------------------------------
# Transcript summarization (replicates PinchBench _summarize_transcript)
# ---------------------------------------------------------------------------


def _summarize_transcript(transcript: List[Dict[str, Any]]) -> str:
    """Summarize transcript for LLM judge prompt.

    Produces the same format as PinchBench's lib_grading._summarize_transcript():
        Tool: function_name({"arg1": value1})
        Result: [first 200 chars]
        User: [message text]
    """
    parts: List[str] = []
    for event in transcript:
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        role = msg.get("role")
        if role == "assistant":
            for item in msg.get("content", []):
                if item.get("type") == "toolCall":
                    parts.append(
                        f"Tool: {item.get('name')}({json.dumps(item.get('params', {}))})"
                    )
                elif item.get("type") == "text":
                    parts.append(f"Assistant: {item.get('text', '')}")
        elif role == "toolResult":
            content = msg.get("content", [])
            if content:
                preview = str(content[0])[:200]
                parts.append(f"Result: {preview}")
        elif role == "user":
            content = msg.get("content", [])
            if content:
                parts.append(f"User: {content[0]}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Judge prompt and response parsing (replicates PinchBench exactly)
# ---------------------------------------------------------------------------


def _build_judge_prompt(
    *,
    task_prompt: str,
    expected_behavior: str,
    rubric: str,
    transcript_summary: str,
) -> str:
    """Build the LLM judge prompt matching PinchBench's format."""
    return f"""You are a strict evaluator assessing an AI agent's performance on a task.
Reserve a score of 1.0 for genuinely excellent performance.

## Task
{task_prompt}

## Expected Behavior
{expected_behavior}

## Agent Transcript
{transcript_summary}

## Grading Rubric
{rubric}

## Instructions
Evaluate the agent's performance against each criterion in the rubric.
Return your evaluation as JSON with this exact structure:
```json
{{
  "scores": {{"criterion_name": score, ...}},
  "total": overall_score_0_to_1,
  "notes": "brief justification"
}}
```
Be a strict evaluator. Deduct points for unnecessary steps, verbose output,
or inefficient tool usage."""


def _parse_judge_response(raw: str) -> Dict[str, Any]:
    """Parse LLM judge response with fallback chain.

    Tries: JSON code block → balanced braces → regex score extraction.
    Matches PinchBench's lib_grading._parse_judge_response() logic.
    """
    if not raw or not raw.strip():
        return {"scores": {}, "total": 0.0, "notes": "Empty judge response"}

    # Try JSON code block
    code_block = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if code_block:
        try:
            parsed = json.loads(code_block.group(1))
            if isinstance(parsed, dict):
                return _normalize_judge_response(parsed)
        except json.JSONDecodeError:
            pass

    # Try balanced braces extraction
    candidates: List[str] = []
    depth = 0
    current: List[str] = []
    for char in raw:
        if char == "{":
            if depth == 0:
                current = []
            depth += 1
        if depth > 0:
            current.append(char)
        if char == "}":
            depth -= 1
            if depth == 0 and current:
                candidates.append("".join(current))

    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict) and "scores" in parsed:
                return _normalize_judge_response(parsed)
        except json.JSONDecodeError:
            continue

    for candidate in reversed(candidates):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return _normalize_judge_response(parsed)
        except json.JSONDecodeError:
            continue

    # Regex fallback for prose scores
    score_match = re.search(
        r"(?:total|overall|final)\s*(?:score)?[:\s]*(0\.\d+|1\.0+)",
        raw,
        re.IGNORECASE,
    )
    if score_match:
        try:
            total = float(score_match.group(1))
            if 0.0 <= total <= 1.0:
                LOGGER.warning(
                    "Fell back to regex score extraction (total=%.2f)", total
                )
                return {
                    "scores": {},
                    "total": total,
                    "notes": "Score extracted from prose",
                }
        except ValueError:
            pass

    LOGGER.warning("Failed to parse judge response")
    return {"scores": {}, "total": 0.0, "notes": "Failed to parse judge response"}


def _normalize_judge_response(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize various judge response formats to standard structure.

    Matches PinchBench's lib_grading._normalize_judge_response().
    """
    result: Dict[str, Any] = {"scores": {}, "total": 0.0, "notes": ""}

    # Extract scores
    scores_data = parsed.get("scores", parsed.get("criteria_scores", {}))
    if isinstance(scores_data, dict):
        for key, value in scores_data.items():
            if isinstance(value, dict) and "score" in value:
                result["scores"][key] = float(value["score"])
            elif isinstance(value, (int, float)):
                result["scores"][key] = float(value)

    # Extract total
    for key in ("total", "score", "overall_score"):
        if key in parsed and isinstance(parsed[key], (int, float)):
            result["total"] = float(parsed[key])
            break
    else:
        if result["scores"]:
            values = [
                v for v in result["scores"].values() if isinstance(v, (int, float))
            ]
            if values:
                result["total"] = sum(values) / len(values)

    # Normalize summed totals back to 0..1
    values = [v for v in result["scores"].values() if isinstance(v, (int, float))]
    if (
        values
        and result["total"] is not None
        and result["total"] > 1.0
        and all(0.0 <= float(v) <= 1.0 for v in values)
    ):
        result["total"] = sum(values) / len(values)

    # Extract notes
    for key in ("notes", "justification", "reasoning"):
        if key in parsed:
            result["notes"] = str(parsed[key])
            break

    return result


# ---------------------------------------------------------------------------
# Grading functions
# ---------------------------------------------------------------------------


def _grade_automated(
    record: EvalRecord,
    transcript: List[Dict[str, Any]],
    workspace_path: str,
) -> Dict[str, Any]:
    """Run the embedded Python grade() function from the task definition."""
    code = record.metadata.get("automated_checks")
    if not code:
        return {"score": 0.0, "breakdown": {}, "notes": "No automated checks defined"}

    namespace: Dict[str, Any] = {}
    try:
        exec(code, namespace)  # noqa: S102
    except Exception as exc:
        LOGGER.error("Failed to compile grading code for %s: %s", record.record_id, exc)
        return {"score": 0.0, "breakdown": {}, "notes": f"Grading code error: {exc}"}

    grade_fn = namespace.get("grade")
    if not callable(grade_fn):
        return {
            "score": 0.0,
            "breakdown": {},
            "notes": "No grade() function found in automated checks",
        }

    try:
        scores = grade_fn(transcript, workspace_path)
    except Exception as exc:
        LOGGER.error("grade() failed for %s: %s", record.record_id, exc)
        return {"score": 0.0, "breakdown": {}, "notes": f"grade() error: {exc}"}

    if not isinstance(scores, dict) or not scores:
        return {
            "score": 0.0,
            "breakdown": {},
            "notes": "grade() returned empty or non-dict",
        }

    mean_score = sum(scores.values()) / len(scores)
    return {"score": mean_score, "breakdown": scores, "notes": ""}


def _grade_llm_judge(
    record: EvalRecord,
    transcript: List[Dict[str, Any]],
    workspace_path: str,
    judge_backend: Any,
    judge_model: str,
) -> Dict[str, Any]:
    """Grade using an LLM judge with the task's rubric."""
    rubric = record.metadata.get("llm_judge_rubric")
    if not rubric:
        return {"score": 0.0, "breakdown": {}, "notes": "No LLM judge rubric defined"}

    if judge_backend is None:
        return {"score": 0.0, "breakdown": {}, "notes": "No judge backend configured"}

    summary = _summarize_transcript(transcript)
    prompt = _build_judge_prompt(
        task_prompt=record.problem,
        expected_behavior=record.reference or "",
        rubric=rubric,
        transcript_summary=summary,
    )

    try:
        raw = judge_backend.generate(
            prompt, model=judge_model, temperature=0.0, max_tokens=2048
        )
    except Exception as exc:
        LOGGER.error("LLM judge call failed for %s: %s", record.record_id, exc)
        return {"score": 0.0, "breakdown": {}, "notes": f"Judge error: {exc}"}

    parsed = _parse_judge_response(raw)
    return {
        "score": parsed.get("total", 0.0),
        "breakdown": parsed.get("scores", {}),
        "notes": parsed.get("notes", ""),
    }


def _grade_hybrid(
    record: EvalRecord,
    transcript: List[Dict[str, Any]],
    workspace_path: str,
    judge_backend: Any,
    judge_model: str,
) -> Dict[str, Any]:
    """Run both automated and LLM judge grading, combine with weights."""
    weights = record.metadata.get("grading_weights") or {
        "automated": 0.5,
        "llm_judge": 0.5,
    }
    auto = _grade_automated(record, transcript, workspace_path)
    llm = _grade_llm_judge(
        record, transcript, workspace_path, judge_backend, judge_model
    )

    auto_w = float(weights.get("automated", 0.5))
    llm_w = float(weights.get("llm_judge", 0.5))
    total_w = auto_w + llm_w

    combined = (
        (auto["score"] * auto_w + llm["score"] * llm_w) / total_w
        if total_w > 0
        else 0.0
    )
    breakdown = {
        **{f"automated.{k}": v for k, v in auto["breakdown"].items()},
        **{f"llm_judge.{k}": v for k, v in llm["breakdown"].items()},
    }
    notes = " | ".join(filter(None, [auto.get("notes", ""), llm.get("notes", "")]))
    return {"score": combined, "breakdown": breakdown, "notes": notes}


def grade_pinchbench_task(
    *,
    record: EvalRecord,
    transcript: List[Dict[str, Any]],
    workspace_path: str,
    judge_backend: Any = None,
    judge_model: str = "anthropic/claude-opus-4-5",
) -> Dict[str, Any]:
    """Top-level grading entry point. Routes by grading_type.

    Returns {"score": float, "breakdown": dict, "notes": str}.
    """
    grading_type = record.metadata.get("grading_type", "automated")

    if grading_type == "automated":
        return _grade_automated(record, transcript, workspace_path)
    elif grading_type == "llm_judge":
        return _grade_llm_judge(
            record, transcript, workspace_path, judge_backend, judge_model
        )
    elif grading_type == "hybrid":
        return _grade_hybrid(
            record, transcript, workspace_path, judge_backend, judge_model
        )
    else:
        return {
            "score": 0.0,
            "breakdown": {},
            "notes": f"Unknown grading type: {grading_type}",
        }


# ---------------------------------------------------------------------------
# Standalone scorer (for EvalRunner non-agentic path)
# ---------------------------------------------------------------------------


class PinchBenchScorer(LLMJudgeScorer):
    """PinchBench scorer for the non-agentic EvalRunner path."""

    scorer_id = "pinchbench"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        trace = record.metadata.get("query_trace")
        if trace:
            transcript = _trace_to_transcript(trace)
        else:
            # No trace — build transcript from tool_results if available
            tool_results = record.metadata.get("tool_results", [])
            transcript = _tool_results_to_transcript(tool_results)

        # Always append final model answer as assistant text message
        # so grading functions that check for text responses can find it
        if model_answer:
            transcript.append(
                {
                    "type": "message",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": model_answer}],
                    },
                }
            )

        result = grade_pinchbench_task(
            record=record,
            transcript=transcript,
            workspace_path=record.metadata.get("workspace_path", ""),
            judge_backend=self._judge_backend,
            judge_model=self._judge_model,
        )
        is_correct = result["score"] >= 0.5
        return is_correct, {**result}


__all__ = [
    "PinchBenchScorer",
    "events_to_transcript",
    "grade_pinchbench_task",
    "_tool_results_to_transcript",
]
