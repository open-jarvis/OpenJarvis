import json

from openjarvis.server.stream_bridge import AgentStreamBridge


def test_tool_call_start_serializes_arguments_for_sse_without_mutating_event():
    bridge = object.__new__(AgentStreamBridge)
    event_data = {
        "tool": "web_search",
        "arguments": {"query": "python"},
        "agent": "agent-1",
    }

    event = bridge._format_named_event("tool_call_start", event_data)
    payload = json.loads(event.split("data: ", 1)[1])

    assert payload["arguments"] == '{"query": "python"}'
    assert event_data["arguments"] == {"query": "python"}


def test_tool_call_start_preserves_already_serialized_arguments():
    bridge = object.__new__(AgentStreamBridge)

    event = bridge._format_named_event(
        "tool_call_start",
        {"tool": "web_search", "arguments": '{"query":"python"}'},
    )
    payload = json.loads(event.split("data: ", 1)[1])

    assert payload["arguments"] == '{"query":"python"}'
