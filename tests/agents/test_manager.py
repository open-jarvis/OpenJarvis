"""Tests for AgentManager persistent agent lifecycle."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def manager():
    """Create an AgentManager with a temp database."""
    from openjarvis.agents.manager import AgentManager

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "agents.db"
        mgr = AgentManager(db_path=str(db_path))
        yield mgr
        mgr.close()


class TestAgentCRUD:
    def test_create_agent(self, manager):
        agent = manager.create_agent(
            name="researcher",
            agent_type="monitor_operative",
            config={
                "tools": ["web_search"],
                "schedule_type": "cron",
                "schedule_value": "0 9 * * *",
            },
        )
        assert agent["id"]
        assert agent["name"] == "researcher"
        assert agent["agent_type"] == "monitor_operative"
        assert agent["status"] == "idle"

    def test_list_agents(self, manager):
        manager.create_agent(name="agent1", agent_type="simple")
        manager.create_agent(name="agent2", agent_type="orchestrator")
        agents = manager.list_agents()
        assert len(agents) == 2
        names = {a["name"] for a in agents}
        assert names == {"agent1", "agent2"}

    def test_get_agent(self, manager):
        created = manager.create_agent(name="test", agent_type="simple")
        fetched = manager.get_agent(created["id"])
        assert fetched is not None
        assert fetched["name"] == "test"

    def test_get_agent_not_found(self, manager):
        assert manager.get_agent("nonexistent") is None

    def test_update_agent(self, manager):
        created = manager.create_agent(name="old", agent_type="simple")
        updated = manager.update_agent(created["id"], name="new")
        assert updated["name"] == "new"

    def test_delete_agent_soft(self, manager):
        created = manager.create_agent(name="doomed", agent_type="simple")
        manager.delete_agent(created["id"])
        agent = manager.get_agent(created["id"])
        assert agent["status"] == "archived"

    def test_pause_resume(self, manager):
        created = manager.create_agent(name="pausable", agent_type="simple")
        manager.pause_agent(created["id"])
        assert manager.get_agent(created["id"])["status"] == "paused"
        manager.resume_agent(created["id"])
        assert manager.get_agent(created["id"])["status"] == "idle"


class TestTaskCRUD:
    def test_create_task(self, manager):
        agent = manager.create_agent(name="worker", agent_type="simple")
        task = manager.create_task(agent["id"], description="Find papers on reasoning")
        assert task["id"]
        assert task["description"] == "Find papers on reasoning"
        assert task["status"] == "pending"

    def test_list_tasks(self, manager):
        agent = manager.create_agent(name="worker", agent_type="simple")
        manager.create_task(agent["id"], description="task1")
        manager.create_task(agent["id"], description="task2")
        tasks = manager.list_tasks(agent["id"])
        assert len(tasks) == 2

    def test_update_task(self, manager):
        agent = manager.create_agent(name="worker", agent_type="simple")
        task = manager.create_task(agent["id"], description="task1")
        updated = manager.update_task(task["id"], status="completed")
        assert updated["status"] == "completed"

    def test_delete_task(self, manager):
        agent = manager.create_agent(name="worker", agent_type="simple")
        task = manager.create_task(agent["id"], description="task1")
        manager.delete_task(task["id"])
        tasks = manager.list_tasks(agent["id"])
        assert len(tasks) == 0


class TestChannelBindings:
    def test_bind_channel(self, manager):
        agent = manager.create_agent(name="slacker", agent_type="simple")
        binding = manager.bind_channel(
            agent["id"],
            channel_type="slack",
            config={
                "channel": "#research",
                "mention_only": False,
                "typing_indicators": True,
            },
        )
        assert binding["id"]
        assert binding["channel_type"] == "slack"

    def test_list_bindings(self, manager):
        agent = manager.create_agent(name="slacker", agent_type="simple")
        manager.bind_channel(
            agent["id"], channel_type="slack", config={"channel": "#a"}
        )
        manager.bind_channel(
            agent["id"], channel_type="telegram", config={"chat_id": "123"}
        )
        bindings = manager.list_channel_bindings(agent["id"])
        assert len(bindings) == 2

    def test_unbind_channel(self, manager):
        agent = manager.create_agent(name="slacker", agent_type="simple")
        binding = manager.bind_channel(agent["id"], channel_type="slack", config={})
        manager.unbind_channel(binding["id"])
        assert len(manager.list_channel_bindings(agent["id"])) == 0


class TestSummaryMemory:
    def test_initial_summary_empty(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        assert agent["summary_memory"] == ""

    def test_update_summary(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        manager.update_summary_memory(agent["id"], "Key finding: X is Y")
        updated = manager.get_agent(agent["id"])
        assert updated["summary_memory"] == "Key finding: X is Y"

    def test_summary_max_length(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        long_text = "x" * 3000
        manager.update_summary_memory(agent["id"], long_text)
        updated = manager.get_agent(agent["id"])
        assert len(updated["summary_memory"]) <= 2000


class TestConcurrency:
    def test_run_tick_guard(self, manager):
        agent = manager.create_agent(name="busy", agent_type="simple")
        # Simulate agent running
        manager._set_status(agent["id"], "running")
        # Trying to run again should raise
        with pytest.raises(ValueError, match="already executing"):
            manager.start_tick(agent["id"])


class TestCheckpoints:
    def test_save_checkpoint(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        manager.save_checkpoint(
            agent["id"],
            tick_id="tick-001",
            conversation_state={"messages": [{"role": "user", "content": "hello"}]},
            tool_state={"web_search": {"last_query": "test"}},
        )
        checkpoints = manager.list_checkpoints(agent["id"])
        assert len(checkpoints) == 1
        assert checkpoints[0]["tick_id"] == "tick-001"

    def test_get_latest_checkpoint(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        manager.save_checkpoint(agent["id"], "tick-001", {"v": 1}, {})
        manager.save_checkpoint(agent["id"], "tick-002", {"v": 2}, {})

        latest = manager.get_latest_checkpoint(agent["id"])
        assert latest is not None
        assert latest["tick_id"] == "tick-002"
        assert latest["conversation_state"]["v"] == 2

    def test_checkpoint_retention_max_5(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        for i in range(8):
            manager.save_checkpoint(agent["id"], f"tick-{i:03d}", {"v": i}, {})

        checkpoints = manager.list_checkpoints(agent["id"])
        assert len(checkpoints) == 5
        # Oldest should be tick-003 (0,1,2 pruned)
        assert checkpoints[-1]["tick_id"] == "tick-003"

    def test_recover_agent(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        manager.save_checkpoint(agent["id"], "tick-001", {"messages": []}, {})
        manager.update_agent(agent["id"], status="error")

        checkpoint = manager.recover_agent(agent["id"])
        assert checkpoint is not None
        assert manager.get_agent(agent["id"])["status"] == "idle"


class TestMessageQueue:
    def test_send_queued_message(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        msg = manager.send_message(agent["id"], "Focus on transformers", mode="queued")
        assert msg["id"]
        assert msg["direction"] == "user_to_agent"
        assert msg["mode"] == "queued"
        assert msg["status"] == "pending"

    def test_list_messages(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        manager.send_message(agent["id"], "msg1", mode="queued")
        manager.send_message(agent["id"], "msg2", mode="queued")
        messages = manager.list_messages(agent["id"])
        assert len(messages) == 2

    def test_get_pending_messages(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        manager.send_message(agent["id"], "pending1", mode="queued")
        manager.send_message(agent["id"], "pending2", mode="queued")
        pending = manager.get_pending_messages(agent["id"])
        assert len(pending) == 2
        assert all(m["status"] == "pending" for m in pending)

    def test_mark_messages_delivered(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        msg = manager.send_message(agent["id"], "test", mode="queued")
        manager.mark_message_delivered(msg["id"])
        messages = manager.list_messages(agent["id"])
        assert messages[0]["status"] == "delivered"

    def test_add_agent_response(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        manager.send_message(agent["id"], "What did you find?", mode="immediate")
        resp = manager.add_agent_response(agent["id"], "Found 3 papers")
        assert resp["direction"] == "agent_to_user"

    def test_store_agent_response_with_tool_calls(self, manager):
        """Tool calls captured during a turn must survive a list_messages
        round-trip so the UI can re-render them after a page reload."""
        agent = manager.create_agent(name="test", agent_type="simple")
        tool_calls = [
            {
                "tool": "file_read",
                "arguments": '{"path": "~/notes.md"}',
                "result": "hello world",
                "success": True,
                "latency": 12.3,
            },
            {
                "tool": "shell_exec",
                "arguments": '{"command": "ls"}',
                "result": "a.md b.md",
                "success": True,
                "latency": 4.5,
            },
        ]
        manager.store_agent_response(
            agent["id"], "Here is what I found", tool_calls=tool_calls
        )
        messages = manager.list_messages(agent["id"])
        assert len(messages) == 1
        assert messages[0]["content"] == "Here is what I found"
        assert messages[0]["tool_calls"] == tool_calls

    def test_store_agent_response_without_tool_calls(self, manager):
        agent = manager.create_agent(name="test", agent_type="simple")
        manager.store_agent_response(agent["id"], "plain reply")
        messages = manager.list_messages(agent["id"])
        assert messages[0]["tool_calls"] is None


def test_update_agent_budget_fields(tmp_path):
    """update_agent() accepts budget and stall kwargs."""
    import time

    from openjarvis.agents.manager import AgentManager

    mgr = AgentManager(str(tmp_path / "test.db"))
    agent = mgr.create_agent("budget-test")

    # Increment total_cost and total_tokens
    mgr.update_agent(agent["id"], total_cost_increment=1.50, total_tokens_increment=500)
    updated = mgr.get_agent(agent["id"])
    assert updated["total_cost"] == 1.50
    assert updated["total_tokens"] == 500

    # Accumulate
    mgr.update_agent(agent["id"], total_cost_increment=0.75, total_tokens_increment=200)
    updated = mgr.get_agent(agent["id"])
    assert updated["total_cost"] == 2.25
    assert updated["total_tokens"] == 700

    # Set last_activity_at
    now = time.time()
    mgr.update_agent(agent["id"], last_activity_at=now)
    updated = mgr.get_agent(agent["id"])
    assert updated["last_activity_at"] == now

    # Set stall_retries
    mgr.update_agent(agent["id"], stall_retries=3)
    updated = mgr.get_agent(agent["id"])
    assert updated["stall_retries"] == 3

    mgr.close()


def test_learning_log_crud(tmp_path):
    """AgentManager can write and read learning log entries."""
    from openjarvis.agents.manager import AgentManager

    mgr = AgentManager(str(tmp_path / "test.db"))
    agent = mgr.create_agent("learner")

    entry = mgr.add_learning_log(
        agent["id"],
        "cycle_completed",
        description="Analyzed 20 traces",
        data={"sft_pairs": 5, "status": "completed"},
    )
    assert entry["event_type"] == "cycle_completed"

    logs = mgr.list_learning_log(agent["id"])
    assert len(logs) == 1
    assert logs[0]["data"]["sft_pairs"] == 5

    # Add a second entry
    mgr.add_learning_log(agent["id"], "skill_discovered", description="Found new skill")
    logs = mgr.list_learning_log(agent["id"])
    assert len(logs) == 2

    mgr.close()


class TestSchemaAndThreading:
    def test_agent_has_runtime_columns(self, manager):
        """New columns from ALTER TABLE migration should exist."""
        agent = manager.create_agent(name="test", agent_type="simple")
        assert "total_tokens" in agent
        assert "total_cost" in agent
        assert "total_runs" in agent
        assert "last_run_at" in agent
        assert "last_activity_at" in agent
        assert agent["total_tokens"] == 0
        assert agent["total_cost"] == 0.0
        assert agent["total_runs"] == 0

    def test_thread_safety(self, manager):
        """AgentManager should be usable from a different thread."""
        import threading

        results = []

        def create_in_thread():
            agent = manager.create_agent(name="threaded", agent_type="simple")
            results.append(agent)

        t = threading.Thread(target=create_in_thread)
        t.start()
        t.join(timeout=5)
        assert len(results) == 1
        assert results[0]["name"] == "threaded"
