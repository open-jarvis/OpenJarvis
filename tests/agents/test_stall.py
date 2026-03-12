"""Tests for activity-based stall detection."""

import time
from unittest.mock import patch

from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.executor import AgentExecutor
from openjarvis.agents.manager import AgentManager
from openjarvis.core.events import EventBus, EventType


def test_activity_tracking_updates_last_activity_at(tmp_path):
    """EventBus TOOL_CALL_START updates last_activity_at for the right agent."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("stall-test")

    def fake_invoke(agent_dict):
        bus.publish(EventType.TOOL_CALL_START, {
            "agent": agent_dict["id"],
            "tool": "web_search",
        })
        return AgentResult(content="done", metadata={})

    with patch.object(executor, "_invoke_agent", side_effect=fake_invoke):
        executor.execute_tick(agent["id"])

    updated = mgr.get_agent(agent["id"])
    assert updated["last_activity_at"] is not None
    assert updated["last_activity_at"] > 0
    mgr.close()


def test_activity_tracking_filters_by_agent_id(tmp_path):
    """Events from other agents don't update this agent's last_activity_at."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent_a = mgr.create_agent("agent-a")
    agent_b = mgr.create_agent("agent-b")

    def fake_invoke(agent_dict):
        # Emit event for agent_b while agent_a is executing
        bus.publish(EventType.TOOL_CALL_START, {
            "agent": agent_b["id"],
            "tool": "web_search",
        })
        return AgentResult(content="done", metadata={})

    with patch.object(executor, "_invoke_agent", side_effect=fake_invoke):
        executor.execute_tick(agent_a["id"])

    updated_b = mgr.get_agent(agent_b["id"])
    assert updated_b["last_activity_at"] is None
    mgr.close()


def test_reconcile_detects_stalled_agent(tmp_path):
    """_reconcile() marks agent as stalled when last_activity_at is too old."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)
    from openjarvis.agents.scheduler import AgentScheduler

    scheduler = AgentScheduler(mgr, executor, event_bus=bus)

    agent = mgr.create_agent("stall-me", config={
        "timeout_seconds": 10,
        "max_stall_retries": 3,
    })
    mgr.update_agent(agent["id"], status="running", last_activity_at=time.time() - 30)

    scheduler._reconcile()

    updated = mgr.get_agent(agent["id"])
    assert updated["stall_retries"] == 1

    stall_events = [
        e for e in bus.history
        if e.event_type == EventType.AGENT_STALL_DETECTED
    ]
    assert len(stall_events) == 1
    mgr.close()


def test_reconcile_skips_active_agent(tmp_path):
    """_reconcile() does NOT mark agent as stalled if activity is recent."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)
    from openjarvis.agents.scheduler import AgentScheduler

    scheduler = AgentScheduler(mgr, executor, event_bus=bus)

    agent = mgr.create_agent("active", config={"timeout_seconds": 10})
    mgr.update_agent(agent["id"], status="running", last_activity_at=time.time() - 2)

    scheduler._reconcile()

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "running"
    mgr.close()


def test_reconcile_retries_exhausted_sets_error(tmp_path):
    """After max_stall_retries, agent goes to error status."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)
    from openjarvis.agents.scheduler import AgentScheduler

    scheduler = AgentScheduler(mgr, executor, event_bus=bus)

    agent = mgr.create_agent("exhausted", config={
        "timeout_seconds": 10,
        "max_stall_retries": 2,
    })
    mgr.update_agent(agent["id"], status="running",
                     last_activity_at=time.time() - 30, stall_retries=2)

    scheduler._reconcile()

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "error"
    mgr.close()
