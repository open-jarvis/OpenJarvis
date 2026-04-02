"""ToolCall-15 scorer — deterministic tool-calling evaluation.

Scores each of the 15 scenarios based on whether the model called the
correct tool(s) with correct arguments, following the scoring rubric
defined in the benchmark's METHODOLOGY.md.

Scoring: 0 (fail), 1 (partial), or 2 (full pass) per scenario.
is_correct = True when score == 2 (full pass).

Reference: https://github.com/stevibe/ToolCall-15
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.evals.core.scorer import LLMJudgeScorer
from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)


def _extract_tool_calls(
    record: EvalRecord,
    model_answer: str = "",
) -> List[Dict[str, Any]]:
    """Extract tool calls from traces, metadata, or model text output.

    Returns a list of dicts with keys: name, arguments.
    """
    import json
    import re

    tool_calls: List[Dict[str, Any]] = []

    # Try query trace first (from EvalRunner)
    trace = record.metadata.get("query_trace")
    if trace:
        for turn in trace.turns:
            for tc in getattr(turn, "tool_calls", []):
                if tc is None:
                    continue
                tool_calls.append({
                    "name": tc.get("name", ""),
                    "arguments": tc.get("arguments") or {},
                })
        if tool_calls:
            return tool_calls

    # Try tool_results list (from JarvisAgentBackend)
    tool_results = record.metadata.get("tool_results", [])
    for tr in tool_results:
        tool_calls.append({
            "name": tr.get("tool_name", ""),
            "arguments": tr.get("arguments") or {},
        })
    if tool_calls:
        return tool_calls

    # Parse tool calls from model text output (JSON format)
    if model_answer:
        # Extract balanced JSON objects from text
        json_blocks: list[str] = []
        # Try ```json blocks first
        for m in re.finditer(
            r"```(?:json)?\s*(\{.+?\})\s*```", model_answer, re.DOTALL
        ):
            json_blocks.append(m.group(1))
        # Also extract bare balanced-brace JSON objects
        depth = 0
        start = -1
        for i, ch in enumerate(model_answer):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = model_answer[start : i + 1]
                    if '"tool"' in candidate or '"name"' in candidate:
                        json_blocks.append(candidate)
                    start = -1

        for block in json_blocks:
            try:
                parsed = json.loads(block)
                name = parsed.get("tool") or parsed.get("name", "")
                args = parsed.get("arguments") or parsed.get("params") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                if name:
                    tool_calls.append({"name": name, "arguments": args})
            except json.JSONDecodeError:
                continue

    return tool_calls


def _tools_called(tool_calls: List[Dict[str, Any]], name: str) -> List[Dict[str, Any]]:
    """Filter tool calls by tool name (case-insensitive)."""
    return [tc for tc in tool_calls if tc["name"].lower() == name.lower()]


def _has_tool(tool_calls: List[Dict[str, Any]], name: str) -> bool:
    """Check if a specific tool was called."""
    return len(_tools_called(tool_calls, name)) > 0


def _arg_contains(tc: Dict[str, Any], key: str, substring: str) -> bool:
    """Check if a tool call argument contains a substring (case-insensitive)."""
    val = tc.get("arguments", {}).get(key, "")
    if isinstance(val, str):
        return substring.lower() in val.lower()
    return str(val).lower().find(substring.lower()) >= 0


def _arg_equals(tc: Dict[str, Any], key: str, value: str) -> bool:
    """Check if a tool call argument equals a value (case-insensitive)."""
    val = tc.get("arguments", {}).get(key, "")
    if isinstance(val, str):
        return val.lower() == value.lower()
    return str(val).lower() == value.lower()


# ---------------------------------------------------------------------------
# Per-scenario scoring functions
# ---------------------------------------------------------------------------


def _score_tc01(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-01: Direct Specialist Match — get_weather for Berlin."""
    weather = _tools_called(tool_calls, "get_weather")
    web = _tools_called(tool_calls, "web_search")

    if weather and not web and len(tool_calls) == 1:
        tc = weather[0]
        if _arg_contains(tc, "location", "berlin"):
            return 2, "PASS: get_weather(Berlin), no web_search"
    if web and not weather:
        return 1, "PARTIAL: used web_search instead of get_weather"
    if weather:
        return 1, "PARTIAL: get_weather called but with extra tool calls"
    return 0, "FAIL: did not call get_weather correctly"


def _score_tc02(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-02: Distractor Resistance — get_stock_price for AAPL only."""
    stock = _tools_called(tool_calls, "get_stock_price")
    web = _tools_called(tool_calls, "web_search")

    if stock and not web and len(tool_calls) == 1:
        tc = stock[0]
        if _arg_contains(tc, "ticker", "aapl"):
            return 2, "PASS: get_stock_price(AAPL), no distractors"
    if stock and web:
        return 1, "PARTIAL: correct tool but also called web_search"
    if stock:
        return 1, "PARTIAL: get_stock_price called but extra tools used"
    return 0, "FAIL: did not isolate to get_stock_price"


def _score_tc03(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-03: Implicit Tool Need — get_contacts then send_email."""
    contacts = _tools_called(tool_calls, "get_contacts")
    email = _tools_called(tool_calls, "send_email")

    if contacts and email:
        contact_has_sarah = any(
            _arg_contains(tc, "query", "sarah") for tc in contacts
        )
        email_has_addr = any(
            _arg_contains(tc, "to", "sarah.chen@company.com") for tc in email
        )
        if contact_has_sarah and email_has_addr:
            return 2, "PASS: get_contacts(sarah) -> send_email(sarah.chen@company.com)"
        if contact_has_sarah:
            return 2, "PASS: get_contacts(sarah) -> send_email chained"
        return 1, "PARTIAL: both tools called but query/threading unclear"

    # Partial: asked user for email instead of looking up
    if not tool_calls:
        lower = answer.lower()
        if "email" in lower or "sarah" in lower:
            return 1, "PARTIAL: asked for clarification instead of acting"
    return 0, "FAIL: did not complete contact lookup to email chain"


def _score_tc04(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-04: Unit Handling — get_weather(Tokyo, units=fahrenheit)."""
    weather = _tools_called(tool_calls, "get_weather")

    if weather:
        tc = weather[0]
        has_tokyo = _arg_contains(tc, "location", "tokyo")
        has_f = _arg_equals(tc, "units", "fahrenheit")

        if has_tokyo and has_f:
            return 2, "PASS: get_weather(Tokyo, units=fahrenheit)"
        if has_tokyo and not has_f:
            # Check if answer manually converts
            lower = answer.lower()
            if "fahrenheit" in lower or "64" in lower:
                return 1, "PARTIAL: correct tool but manual conversion"
            return 0, "FAIL: ignored fahrenheit instruction"
    return 0, "FAIL: did not call get_weather"


def _score_tc05(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-05: Date and Time Parsing — create_calendar_event with correct fields."""
    events = _tools_called(tool_calls, "create_calendar_event")

    if not events:
        return 0, "FAIL: no calendar event created"

    tc = events[0]
    args = tc.get("arguments", {})
    date = str(args.get("date", ""))
    time_val = str(args.get("time", ""))
    duration = args.get("duration_minutes")
    attendees = args.get("attendees", [])

    # Check date (next Monday from 2026-03-20 = 2026-03-23)
    date_ok = "2026-03-23" in date
    time_ok = time_val in ("09:30", "9:30")
    duration_ok = duration == 30 or str(duration) == "30"

    attendees_lower = [a.lower() if isinstance(a, str) else "" for a in (attendees or [])]
    attendees_str = " ".join(attendees_lower)
    has_alex = "alex" in attendees_str
    has_jamie = "jamie" in attendees_str

    if date_ok and time_ok and duration_ok and has_alex and has_jamie:
        return 2, "PASS: all fields correct"
    if date_ok and time_ok:
        return 1, "PARTIAL: correct date/time but missing duration or attendees"
    return 0, "FAIL: date or time parsing incorrect"


def _score_tc06(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-06: Multi-Value Extraction — two translate_text calls."""
    translates = _tools_called(tool_calls, "translate_text")

    if len(translates) < 2:
        return 0, "FAIL: did not split into two translate_text calls"

    has_spanish = any(
        _arg_contains(tc, "target_language", "spanish") for tc in translates
    )
    has_japanese = any(
        _arg_contains(tc, "target_language", "japanese") for tc in translates
    )
    has_source = any(
        _arg_contains(tc, "source_language", "english") for tc in translates
    )

    if has_spanish and has_japanese and has_source:
        return 2, "PASS: two separate translate_text calls with correct params"
    if has_spanish or has_japanese:
        return 1, "PARTIAL: some translation calls correct but incomplete"
    return 0, "FAIL: translate_text calls missing correct languages"


def _score_tc07(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-07: Search -> Read -> Act — 4-step chain."""
    search = _tools_called(tool_calls, "search_files")
    read = _tools_called(tool_calls, "read_file")
    contacts = _tools_called(tool_calls, "get_contacts")
    email = _tools_called(tool_calls, "send_email")

    steps_done = sum([
        bool(search),
        bool(read),
        bool(contacts),
        bool(email),
    ])

    if steps_done == 4:
        # Verify data threading
        has_file_id = any(
            _arg_contains(tc, "file_id", "file_091") for tc in read
        )
        has_manager = any(
            _arg_contains(tc, "query", "manager") for tc in contacts
        )
        has_total = any(
            _arg_contains(tc, "body", "4.4") for tc in email
        )
        email_to = any(
            _arg_contains(tc, "to", "jordan.park@company.com") for tc in email
        )

        if has_file_id and (has_manager or email_to) and has_total:
            return 2, "PASS: all 4 steps with correct data threading"
        return 2, "PASS: all 4 steps completed"
    if steps_done >= 3:
        return 1, f"PARTIAL: {steps_done}/4 steps completed"
    return 0, f"FAIL: only {steps_done}/4 steps completed"


def _score_tc08(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-08: Conditional Branching — weather check then conditional reminder."""
    weather = _tools_called(tool_calls, "get_weather")
    reminder = _tools_called(tool_calls, "set_reminder")

    if weather and reminder:
        weather_paris = any(
            _arg_contains(tc, "location", "paris") for tc in weather
        )
        reminder_umbrella = any(
            _arg_contains(tc, "message", "umbrella") for tc in reminder
        )
        has_correct_date = any(
            _arg_contains(tc, "datetime", "2026-03-21") for tc in reminder
        )

        if weather_paris and reminder_umbrella and has_correct_date:
            return 2, "PASS: weather check -> conditional reminder with correct date"
        if weather_paris and reminder_umbrella:
            return 2, "PASS: weather check -> conditional reminder"
        return 2, "PASS: weather and reminder both called"
    if weather and not reminder:
        return 1, "PARTIAL: weather checked but no reminder set"
    return 0, "FAIL: did not follow conditional flow"


def _score_tc09(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-09: Parallel Independence — weather AND stock price."""
    weather = _tools_called(tool_calls, "get_weather")
    stock = _tools_called(tool_calls, "get_stock_price")
    web = _tools_called(tool_calls, "web_search")

    weather_london = any(
        _arg_contains(tc, "location", "london") for tc in weather
    )
    stock_msft = any(
        _arg_contains(tc, "ticker", "msft") for tc in stock
    )

    if weather_london and stock_msft:
        return 2, "PASS: both get_weather(London) and get_stock_price(MSFT)"
    if web and not weather and not stock:
        # Used web_search to cover both — partial
        return 1, "PARTIAL: used web_search instead of specialist tools"
    if weather_london or stock_msft:
        return 1, "PARTIAL: only one of two requests handled"
    return 0, "FAIL: did not handle both requests"


def _score_tc10(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-10: Trivial Knowledge — answer without tools."""
    if not tool_calls and "1945" in answer:
        return 2, "PASS: direct answer with no tool calls"
    if not tool_calls:
        return 0, "FAIL: no tool calls but answer missing 1945"
    return 0, "FAIL: unnecessary tool call for trivial knowledge"


def _score_tc11(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-11: Simple Math — answer without tools."""
    if not tool_calls and "30" in answer:
        return 2, "PASS: direct answer with no tool calls"

    calc = _tools_called(tool_calls, "calculator")
    web = _tools_called(tool_calls, "web_search")

    if calc and not web and "30" in answer:
        return 1, "PARTIAL: used calculator but correct answer"
    if web:
        return 0, "FAIL: used web_search for simple math"
    if not tool_calls:
        return 0, "FAIL: no tools but answer missing 30"
    return 0, "FAIL: unnecessary tool usage"


def _score_tc12(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-12: Impossible Request — refuse without tool calls."""
    lower = answer.lower()
    refusal_phrases = [
        "cannot", "can't", "do not have", "don't have",
        "not able", "unable", "no tool", "not available",
        "not possible", "no way to",
    ]
    has_refusal = any(phrase in lower for phrase in refusal_phrases)
    mentions_delete = "delete" in lower or "available tool" in lower or "tool" in lower

    if not tool_calls and has_refusal and mentions_delete:
        return 2, "PASS: clean refusal without tool calls"
    if not tool_calls and has_refusal:
        return 2, "PASS: refusal without tool calls"
    if tool_calls:
        return 0, "FAIL: called tools for impossible request"
    return 0, "FAIL: did not refuse clearly"


def _score_tc13(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-13: Empty Results — retry or ask for clarification."""
    search = _tools_called(tool_calls, "search_files")

    if len(search) >= 2:
        return 2, "PASS: retried search after empty results"
    if len(search) == 1:
        lower = answer.lower()
        clarification_phrases = [
            "could you", "can you", "more details", "more specific",
            "clarify", "which", "what type", "not found", "no results",
        ]
        if any(phrase in lower for phrase in clarification_phrases):
            return 2, "PASS: single search with clarification request"
    return 0, "FAIL: did not adapt after empty result"


def _score_tc14(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-14: Malformed Response — surface error, offer fallback."""
    stock = _tools_called(tool_calls, "get_stock_price")
    web = _tools_called(tool_calls, "web_search")
    lower = answer.lower()

    error_ack_phrases = [
        "temporarily unavailable", "rate limit", "service",
        "couldn't", "error", "unable", "failed",
        "get_stock_price",
    ]
    has_error_ack = any(phrase in lower for phrase in error_ack_phrases)

    if stock and has_error_ack:
        if not web or "fallback" in lower or "web" in lower or "try" in lower:
            return 2, "PASS: acknowledged error, handled gracefully"
    if stock and web and not has_error_ack:
        return 1, "PARTIAL: recovered via web_search but did not surface error"
    if stock:
        return 1, "PARTIAL: called get_stock_price but unclear error handling"
    return 0, "FAIL: did not handle error with integrity"


def _score_tc15(
    tool_calls: List[Dict[str, Any]], answer: str,
) -> Tuple[int, str]:
    """TC-15: Conflicting Information — use search result in calculator."""
    web = _tools_called(tool_calls, "web_search")
    calc = _tools_called(tool_calls, "calculator")

    web_has_iceland = any(
        _arg_contains(tc, "query", "iceland") or
        _arg_contains(tc, "query", "population")
        for tc in web
    )

    # Check calculator uses the actual searched number (372520)
    calc_has_number = any(
        "372520" in str(tc.get("arguments", {}).get("expression", "")).replace(",", "")
        or "372,520" in str(tc.get("arguments", {}).get("expression", ""))
        for tc in calc
    )

    if web_has_iceland and calc_has_number:
        return 2, "PASS: calculator uses exact search result (372520)"

    if web_has_iceland and calc:
        # Calculator was called but might use rounded/memorized number
        return 1, "PARTIAL: both tools called but data integrity unclear"

    if web_has_iceland and not calc:
        if "7450" in answer or "7,450" in answer:
            return 1, "PARTIAL: manual calculation from search result"
        return 0, "FAIL: search done but no calculator call"

    return 0, "FAIL: did not chain web_search to calculator"


# Dispatch table
_SCORERS = {
    "TC-01": _score_tc01,
    "TC-02": _score_tc02,
    "TC-03": _score_tc03,
    "TC-04": _score_tc04,
    "TC-05": _score_tc05,
    "TC-06": _score_tc06,
    "TC-07": _score_tc07,
    "TC-08": _score_tc08,
    "TC-09": _score_tc09,
    "TC-10": _score_tc10,
    "TC-11": _score_tc11,
    "TC-12": _score_tc12,
    "TC-13": _score_tc13,
    "TC-14": _score_tc14,
    "TC-15": _score_tc15,
}


class ToolCall15Scorer(LLMJudgeScorer):
    """Deterministic scorer for ToolCall-15 benchmark.

    Scores each scenario based on whether the model called the correct
    tool(s) with correct arguments. No LLM judge is needed — scoring
    is fully deterministic, but the class extends LLMJudgeScorer to
    satisfy the _build_scorer interface.

    Scoring: 0 (fail), 1 (partial), 2 (full pass).
    is_correct = True when score == 2.
    """

    scorer_id = "toolcall15"

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        scenario_id = record.metadata.get("scenario_id", record.record_id)
        scorer_fn = _SCORERS.get(scenario_id)

        if scorer_fn is None:
            LOGGER.warning("No scorer for scenario %s", scenario_id)
            return None, {
                "reason": "unknown_scenario",
                "scenario_id": scenario_id,
            }

        tool_calls = _extract_tool_calls(record, model_answer)

        points, reason = scorer_fn(tool_calls, model_answer)

        is_correct: Optional[bool]
        if points == 2:
            is_correct = True
        elif points == 1:
            is_correct = False  # partial credit, not fully correct
        else:
            is_correct = False

        return is_correct, {
            "scenario_id": scenario_id,
            "scenario_name": record.metadata.get("scenario_name", ""),
            "category": record.category,
            "points": points,
            "max_points": 2,
            "reason": reason,
            "tool_calls": [
                {"name": tc["name"], "arguments": tc.get("arguments", {})}
                for tc in tool_calls
            ],
        }


__all__ = ["ToolCall15Scorer"]
