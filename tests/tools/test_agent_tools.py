"""Tests for inter-agent lifecycle tools."""

from __future__ import annotations

import json

from friday_ai.tools.agent_tools import (
    _SPAWNED_AGENTS,
    AgentKillTool,
    AgentListTool,
    AgentSendTool,
    AgentSpawnTool,
)

# ---------------------------------------------------------------------------
# AgentSpawnTool
# ---------------------------------------------------------------------------


class TestAgentSpawnTool:
    def setup_method(self):
        _SPAWNED_AGENTS.clear()

    def test_spec(self):
        tool = AgentSpawnTool()
        spec = tool.spec
        assert spec.name == "agent_spawn"
        assert spec.category == "agents"
        assert "system:admin" in spec.required_capabilities
        assert "agent_type" in spec.parameters["required"]

    def test_spawn_creates_agent_entry(self):
        tool = AgentSpawnTool()
        result = tool.execute(agent_type="simple")
        assert result.success
        data = json.loads(result.content)
        assert data["agent_type"] == "simple"
        assert data["status"] == "running"
        assert data["agent_id"] in _SPAWNED_AGENTS

    def test_spawn_with_custom_id(self):
        tool = AgentSpawnTool()
        result = tool.execute(agent_type="orchestrator", agent_id="my-agent-1")
        assert result.success
        data = json.loads(result.content)
        assert data["agent_id"] == "my-agent-1"
        assert "my-agent-1" in _SPAWNED_AGENTS

    def test_spawn_with_query(self):
        tool = AgentSpawnTool()
        result = tool.execute(agent_type="native_react", query="Hello world")
        assert result.success
        data = json.loads(result.content)
        assert data["initial_query"] == "Hello world"

    def test_spawn_with_tools(self):
        tool = AgentSpawnTool()
        result = tool.execute(
            agent_type="orchestrator",
            tools="calculator,think",
        )
        assert result.success
        agent_id = json.loads(result.content)["agent_id"]
        assert _SPAWNED_AGENTS[agent_id]["tools"] == "calculator,think"

    def test_spawn_no_agent_type(self):
        tool = AgentSpawnTool()
        result = tool.execute()
        assert not result.success
        assert "agent_type" in result.content.lower()

    def test_spawn_auto_generates_id(self):
        tool = AgentSpawnTool()
        result = tool.execute(agent_type="simple")
        data = json.loads(result.content)
        assert len(data["agent_id"]) > 0

    def test_spawn_records_created_at(self):
        tool = AgentSpawnTool()
        tool.execute(agent_type="simple", agent_id="ts-test")
        entry = _SPAWNED_AGENTS["ts-test"]
        assert "created_at" in entry
        assert isinstance(entry["created_at"], float)


# ---------------------------------------------------------------------------
# AgentSendTool
# ---------------------------------------------------------------------------


class TestAgentSendTool:
    def setup_method(self):
        _SPAWNED_AGENTS.clear()

    def test_spec(self):
        tool = AgentSendTool()
        spec = tool.spec
        assert spec.name == "agent_send"
        assert spec.category == "agents"
        assert "system:admin" in spec.required_capabilities
        assert "agent_id" in spec.parameters["required"]
        assert "message" in spec.parameters["required"]

    def test_send_to_nonexistent_agent_fails(self):
        tool = AgentSendTool()
        result = tool.execute(agent_id="no-such-agent", message="hi")
        assert not result.success
        assert "not found" in result.content

    def test_send_to_valid_agent_succeeds(self):
        _SPAWNED_AGENTS["agent-x"] = {
            "agent_id": "agent-x",
            "agent_type": "simple",
            "status": "running",
            "created_at": 0.0,
        }
        tool = AgentSendTool()
        result = tool.execute(agent_id="agent-x", message="Hello agent")
        assert result.success
        data = json.loads(result.content)
        assert data["delivered"] is True
        assert data["message"] == "Hello agent"

    def test_send_no_agent_id(self):
        tool = AgentSendTool()
        result = tool.execute(message="hi")
        assert not result.success

    def test_send_no_message(self):
        _SPAWNED_AGENTS["agent-y"] = {
            "agent_id": "agent-y",
            "agent_type": "simple",
            "status": "running",
            "created_at": 0.0,
        }
        tool = AgentSendTool()
        result = tool.execute(agent_id="agent-y")
        assert not result.success
        assert "message" in result.content.lower()


# ---------------------------------------------------------------------------
# AgentListTool
# ---------------------------------------------------------------------------


class TestAgentListTool:
    def setup_method(self):
        _SPAWNED_AGENTS.clear()

    def test_spec(self):
        tool = AgentListTool()
        spec = tool.spec
        assert spec.name == "agent_list"
        assert spec.category == "agents"
        assert "system:admin" in spec.required_capabilities

    def test_list_empty(self):
        tool = AgentListTool()
        result = tool.execute()
        assert result.success
        assert result.content == "No agents spawned."

    def test_list_after_spawn(self):
        _SPAWNED_AGENTS["a1"] = {
            "agent_id": "a1",
            "agent_type": "orchestrator",
            "status": "running",
            "created_at": 1000.0,
        }
        _SPAWNED_AGENTS["a2"] = {
            "agent_id": "a2",
            "agent_type": "native_react",
            "status": "stopped",
            "created_at": 2000.0,
        }
        tool = AgentListTool()
        result = tool.execute()
        assert result.success
        data = json.loads(result.content)
        assert len(data) == 2
        ids = {a["agent_id"] for a in data}
        assert ids == {"a1", "a2"}

    def test_list_shows_status(self):
        _SPAWNED_AGENTS["b1"] = {
            "agent_id": "b1",
            "agent_type": "simple",
            "status": "running",
            "created_at": 500.0,
        }
        tool = AgentListTool()
        result = tool.execute()
        data = json.loads(result.content)
        assert data[0]["status"] == "running"
        assert data[0]["agent_type"] == "simple"


# ---------------------------------------------------------------------------
# AgentKillTool
# ---------------------------------------------------------------------------


class TestAgentKillTool:
    def setup_method(self):
        _SPAWNED_AGENTS.clear()

    def test_spec(self):
        tool = AgentKillTool()
        spec = tool.spec
        assert spec.name == "agent_kill"
        assert spec.category == "agents"
        assert spec.requires_confirmation is True
        assert "system:admin" in spec.required_capabilities
        assert "agent_id" in spec.parameters["required"]

    def test_kill_nonexistent_fails(self):
        tool = AgentKillTool()
        result = tool.execute(agent_id="ghost")
        assert not result.success
        assert "not found" in result.content

    def test_kill_marks_stopped(self):
        _SPAWNED_AGENTS["k1"] = {
            "agent_id": "k1",
            "agent_type": "simple",
            "status": "running",
            "created_at": 0.0,
        }
        tool = AgentKillTool()
        result = tool.execute(agent_id="k1")
        assert result.success
        data = json.loads(result.content)
        assert data["status"] == "stopped"
        assert _SPAWNED_AGENTS["k1"]["status"] == "stopped"

    def test_kill_already_stopped(self):
        _SPAWNED_AGENTS["k2"] = {
            "agent_id": "k2",
            "agent_type": "orchestrator",
            "status": "stopped",
            "created_at": 0.0,
        }
        tool = AgentKillTool()
        result = tool.execute(agent_id="k2")
        assert result.success
        assert _SPAWNED_AGENTS["k2"]["status"] == "stopped"

    def test_kill_no_agent_id(self):
        tool = AgentKillTool()
        result = tool.execute()
        assert not result.success
