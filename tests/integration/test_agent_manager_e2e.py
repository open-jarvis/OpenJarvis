"""End-to-end test: create agent from template, add task, verify state."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from openjarvis.agents.manager import AgentManager


@pytest.fixture
def manager():
    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        yield mgr
        mgr.close()


class TestResearchMonitorE2E:
    """Vertical slice: Research Monitor agent lifecycle."""

    def test_create_from_template(self, manager):
        templates = manager.list_templates()
        assert any(t["id"] == "research_monitor" for t in templates)

        agent = manager.create_from_template("research_monitor", "My Researcher")
        assert agent["name"] == "My Researcher"
        assert agent["agent_type"] == "monitor_operative"
        assert agent["status"] == "idle"
        config = agent["config"]
        assert "web_search" in config.get("tools", [])

    def test_full_lifecycle(self, manager):
        # Create
        agent = manager.create_agent(name="lifecycle_test", agent_type="simple")
        agent_id = agent["id"]

        # Add tasks
        t1 = manager.create_task(agent_id, "Find papers on reasoning")
        manager.create_task(agent_id, "Summarize findings")
        assert len(manager.list_tasks(agent_id)) == 2

        # Bind channel
        binding = manager.bind_channel(
            agent_id, "slack", {"channel": "#research", "typing_indicators": True}
        )
        assert binding["channel_type"] == "slack"

        # Update summary memory
        summary = "Found 3 papers on chain-of-thought reasoning."
        manager.update_summary_memory(agent_id, summary)
        agent = manager.get_agent(agent_id)
        assert "chain-of-thought" in agent["summary_memory"]

        # Pause / resume
        manager.pause_agent(agent_id)
        assert manager.get_agent(agent_id)["status"] == "paused"
        manager.resume_agent(agent_id)
        assert manager.get_agent(agent_id)["status"] == "idle"

        # Complete task
        manager.update_task(
            t1["id"],
            status="completed",
            findings=["Paper A", "Paper B"],
        )
        task = manager._get_task(t1["id"])
        assert task["status"] == "completed"
        assert len(task["findings"]) == 2

        # Soft delete
        manager.delete_agent(agent_id)
        assert manager.get_agent(agent_id)["status"] == "archived"
        # Archived agents not in default list
        assert agent_id not in [a["id"] for a in manager.list_agents()]

    def test_template_with_overrides(self, manager):
        agent = manager.create_from_template(
            "research_monitor",
            "Custom Researcher",
            overrides={"schedule_value": "0 */6 * * *", "temperature": 0.5},
        )
        config = agent["config"]
        assert config["schedule_value"] == "0 */6 * * *"
        assert config["temperature"] == 0.5
