"""Regression tests for managed-agent tool-call persistence."""

from __future__ import annotations

import json

import pytest

from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.executor import AgentExecutor, _tool_calls_for_storage
from openjarvis.agents.manager import AgentManager
from openjarvis.core.events import EventBus
from openjarvis.core.types import ToolResult


def test_tool_results_are_serialized_for_managed_messages() -> None:
    result = AgentResult(
        content="Finished",
        tool_results=[
            ToolResult(
                tool_name="knowledge_search",
                content="Found the requested note",
                success=True,
                latency_seconds=0.42,
                metadata={
                    "arguments": {
                        "query": "financial independence",
                        "limit": 3,
                    }
                },
            ),
            ToolResult(
                tool_name="shell_exec",
                content="Permission denied",
                success=False,
                latency_seconds=1.25,
                metadata={"arguments": '{"command":"whoami"}'},
            ),
        ],
    )

    calls = _tool_calls_for_storage(result)

    assert calls is not None
    assert len(calls) == 2

    knowledge_call = calls[0]
    assert knowledge_call["tool"] == "knowledge_search"
    assert isinstance(knowledge_call["arguments"], str)
    assert json.loads(knowledge_call["arguments"]) == {
        "query": "financial independence",
        "limit": 3,
    }
    assert knowledge_call["result"] == "Found the requested note"
    assert knowledge_call["success"] is True
    assert knowledge_call["latency"] == pytest.approx(420.0)

    failed_call = calls[1]
    assert failed_call["arguments"] == '{"command":"whoami"}'
    assert failed_call["result"] == "Permission denied"
    assert failed_call["success"] is False
    assert failed_call["latency"] == pytest.approx(1250.0)


def test_no_tool_results_serialize_as_none() -> None:
    assert _tool_calls_for_storage(AgentResult(content="Plain response")) is None


def test_finalize_tick_persists_tool_calls_round_trip(tmp_path) -> None:
    manager = AgentManager(str(tmp_path / "agents.db"))
    try:
        agent = manager.create_agent("researcher")
        manager.start_tick(agent["id"])
        result = AgentResult(
            content="Answer grounded in the knowledge base",
            tool_results=[
                ToolResult(
                    tool_name="knowledge_search",
                    content="Matching source text",
                    success=True,
                    latency_seconds=0.007,
                    metadata={"arguments": {"query": "grounded answer"}},
                )
            ],
        )

        executor = AgentExecutor(manager, EventBus())
        executor._finalize_tick(
            agent["id"],
            result,
            error=None,
            duration=0.01,
        )

        messages = manager.list_messages(agent["id"])
        assert len(messages) == 1
        stored = messages[0]
        assert stored["content"] == result.content
        assert stored["direction"] == "agent_to_user"
        assert stored["tool_calls"] == _tool_calls_for_storage(result)
        assert isinstance(stored["tool_calls"][0]["arguments"], str)
        assert json.loads(stored["tool_calls"][0]["arguments"]) == {
            "query": "grounded answer"
        }
        assert stored["tool_calls"][0]["latency"] == pytest.approx(7.0)
    finally:
        manager.close()


def test_finalize_tick_without_tools_stores_null_tool_calls(tmp_path) -> None:
    manager = AgentManager(str(tmp_path / "agents.db"))
    try:
        agent = manager.create_agent("plain-agent")
        manager.start_tick(agent["id"])

        executor = AgentExecutor(manager, EventBus())
        executor._finalize_tick(
            agent["id"],
            AgentResult(content="No tools needed"),
            error=None,
            duration=0.01,
        )

        stored = manager.list_messages(agent["id"])[0]
        assert stored["tool_calls"] is None
    finally:
        manager.close()
