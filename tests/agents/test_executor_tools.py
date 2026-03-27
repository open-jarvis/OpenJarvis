"""Tests for tool wiring in AgentExecutor."""

from __future__ import annotations

from openjarvis.agents.executor import AgentExecutor
from openjarvis.agents.manager import AgentManager
from openjarvis.core.events import EventBus
from tests.agents.fake_engine import FakeEngine
from tests.agents.scenario_harness import FakeSystem


def _register_agent():
    """Re-register MonitorOperativeAgent (cleared by autouse fixture)."""
    from openjarvis.agents.monitor_operative import MonitorOperativeAgent
    from openjarvis.core.registry import AgentRegistry

    if not AgentRegistry.contains("monitor_operative"):
        AgentRegistry.register("monitor_operative")(MonitorOperativeAgent)


def test_executor_runs_with_tools_from_config(tmp_path):
    """Executor should resolve tool names from config and complete tick."""
    _register_agent()

    engine = FakeEngine([{"content": "test response"}])
    system = FakeSystem(engine=engine)

    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": ["think"],
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(system)

    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    assert result_agent["total_runs"] == 1
    mgr.close()


def test_executor_handles_missing_tools(tmp_path):
    """Executor should not crash if tool names don't exist in registry."""
    _register_agent()

    engine = FakeEngine([{"content": "test response"}])
    system = FakeSystem(engine=engine)

    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": ["nonexistent_tool_xyz"],
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(system)

    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    assert result_agent["total_runs"] == 1
    mgr.close()


def test_executor_handles_string_tools(tmp_path):
    """Executor should handle comma-separated tool string as well as list."""
    _register_agent()

    engine = FakeEngine([{"content": "test response"}])
    system = FakeSystem(engine=engine)

    mgr = AgentManager(db_path=str(tmp_path / "test.db"))
    agent = mgr.create_agent(
        "test",
        agent_type="monitor_operative",
        config={
            "system_prompt": "You are a test agent.",
            "tools": "think,calculator",
            "instruction": "test",
        },
    )
    mgr.send_message(agent["id"], "hello", mode="immediate")

    executor = AgentExecutor(manager=mgr, event_bus=EventBus())
    executor.set_system(system)

    executor.execute_tick(agent["id"])
    result_agent = mgr.get_agent(agent["id"])
    assert result_agent["status"] == "idle"
    mgr.close()
