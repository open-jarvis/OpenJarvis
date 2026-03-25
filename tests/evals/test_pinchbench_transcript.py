"""Tests for TurnTrace tool_calls field and PinchBench transcript translation."""

from openjarvis.evals.core.trace import TurnTrace


def test_turn_trace_tool_calls_default_empty():
    """New tool_calls field defaults to empty list."""
    turn = TurnTrace(turn_index=0)
    assert turn.tool_calls == []


def test_turn_trace_tool_calls_to_dict():
    """tool_calls round-trips through to_dict/from_dict."""
    calls = [{"name": "file_read", "arguments": {"path": "a.txt"}, "result": "hello"}]
    turn = TurnTrace(turn_index=0, tool_calls=calls)
    d = turn.to_dict()
    assert d["tool_calls"] == calls


def test_turn_trace_tool_calls_from_dict():
    """from_dict restores tool_calls."""
    calls = [{"name": "web_search", "arguments": {"q": "test"}, "result": "results"}]
    d = {"turn_index": 0, "tool_calls": calls}
    turn = TurnTrace.from_dict(d)
    assert turn.tool_calls == calls


def test_turn_trace_tool_calls_from_dict_missing():
    """from_dict with missing tool_calls defaults to empty list."""
    d = {"turn_index": 0}
    turn = TurnTrace.from_dict(d)
    assert turn.tool_calls == []
