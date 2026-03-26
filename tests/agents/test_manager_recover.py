"""Tests for AgentManager.recover_agent() always resetting status."""

import pytest

from openjarvis.agents.manager import AgentManager


@pytest.fixture
def manager(tmp_path):
    db = str(tmp_path / "agents.db")
    return AgentManager(db_path=db)


def test_recover_resets_to_idle_without_checkpoint(manager):
    """recover_agent must reset status to idle even when no checkpoint exists."""
    agent = manager.create_agent(name="test", agent_type="monitor_operative")
    manager.update_agent(agent["id"], status="error")

    result = manager.recover_agent(agent["id"])

    assert result is None
    refreshed = manager.get_agent(agent["id"])
    assert refreshed["status"] == "idle"


def test_recover_resets_to_idle_with_checkpoint(manager):
    """recover_agent returns checkpoint and resets status when checkpoint exists."""
    agent = manager.create_agent(name="test", agent_type="monitor_operative")
    manager.update_agent(agent["id"], status="error")
    manager.save_checkpoint(agent["id"], "tick-1", {"history": []}, {"tools": {}})

    result = manager.recover_agent(agent["id"])

    assert result is not None
    assert result["tick_id"] == "tick-1"
    refreshed = manager.get_agent(agent["id"])
    assert refreshed["status"] == "idle"
