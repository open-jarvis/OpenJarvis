"""Tests for TurnTrace tool_calls field and PinchBench transcript translation."""

from openjarvis.evals.core.event_recorder import AgentEvent, EventType
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


def _make_event(etype, **metadata):
    """Helper to create a mock AgentEvent."""
    return AgentEvent(event_type=etype, timestamp=0.0, metadata=metadata)


def test_events_to_transcript_tool_call_pair():
    """TOOL_CALL_START + END produces assistant toolCall + toolResult messages."""
    from openjarvis.evals.scorers.pinchbench import events_to_transcript

    events = [
        _make_event(
            EventType.TOOL_CALL_START, tool="file_read", arguments={"path": "a.txt"}
        ),
        _make_event(EventType.TOOL_CALL_END, tool="file_read", result="file contents"),
    ]
    transcript = events_to_transcript(events)
    assert len(transcript) == 2
    assert transcript[0]["type"] == "message"
    assert transcript[0]["message"]["role"] == "assistant"
    assert transcript[0]["message"]["content"][0]["type"] == "toolCall"
    # Tool name mapped: file_read -> read_file
    assert transcript[0]["message"]["content"][0]["name"] == "read_file"
    assert transcript[1]["message"]["role"] == "toolResult"
    assert transcript[1]["message"]["content"][0]["text"] == "file contents"


def test_events_to_transcript_tool_name_mapping():
    """OpenJarvis tool names are mapped to PinchBench-expected names."""
    from openjarvis.evals.scorers.pinchbench import events_to_transcript

    events = [
        _make_event(
            EventType.TOOL_CALL_START,
            tool="image_generate",
            arguments={"prompt": "cat"},
        ),
        _make_event(EventType.TOOL_CALL_END, tool="image_generate", result="ok"),
    ]
    transcript = events_to_transcript(events)
    assert transcript[0]["message"]["content"][0]["name"] == "generate_image"


def test_events_to_transcript_empty():
    """Empty events produce empty transcript."""
    from openjarvis.evals.scorers.pinchbench import events_to_transcript

    assert events_to_transcript([]) == []


def test_events_to_transcript_ignores_non_tool_events():
    """Non-tool events are skipped."""
    from openjarvis.evals.scorers.pinchbench import events_to_transcript

    events = [
        _make_event(EventType.LM_INFERENCE_START),
        _make_event(EventType.LM_INFERENCE_END, prompt_tokens=10, completion_tokens=5),
    ]
    assert events_to_transcript(events) == []
