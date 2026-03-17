"""Agent lifecycle scenario tests.

Twelve+ scenarios exercising the full managed-agent stack (manager, executor,
scheduler) with real SQLite state and a scripted FakeEngine.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from openjarvis.agents.errors import RetryableError
from openjarvis.core.events import EventType
from tests.agents.scenario_harness import ScenarioHarness

# ---------------------------------------------------------------------------
# Scenario 1: Manual agent full lifecycle
# ---------------------------------------------------------------------------


def test_manual_agent_full_lifecycle(scenario_harness: ScenarioHarness) -> None:
    """Create a manual agent, run a tick, verify status/runs/memory."""
    h = scenario_harness
    h.engine._responses = [{"content": "Tick 1 completed."}]
    h.engine._call_count = 0

    agent = h.manager.create_agent(
        name="manual-agent",
        config={"schedule_type": "manual", "instruction": "Do something."},
    )
    aid = agent["id"]

    h.executor.execute_tick(aid)

    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert agent["status"] == "idle"
    assert agent["total_runs"] == 1
    assert "Tick 1 completed." in agent["summary_memory"]


# ---------------------------------------------------------------------------
# Scenario 2: Interval-scheduled agent
# ---------------------------------------------------------------------------


def test_interval_scheduled_agent(scenario_harness: ScenarioHarness) -> None:
    """Interval agent does not fire until time advances past interval."""
    h = scenario_harness
    h.engine._responses = [{"content": "Interval response."}]
    h.engine._call_count = 0

    base_time = 1_000_000.0

    agent = h.manager.create_agent(
        name="interval-agent",
        config={
            "schedule_type": "interval",
            "schedule_value": 60,
            "instruction": "Check status.",
        },
    )
    aid = agent["id"]

    # Register at base_time — next_fire = base_time + 60
    with patch("openjarvis.agents.scheduler.time") as mock_time:
        mock_time.time.return_value = base_time
        h.scheduler.register_agent(aid)

    info = h.scheduler._agents[aid]
    assert info["next_fire"] == pytest.approx(base_time + 60, abs=1)

    # At base_time + 30 the agent should NOT fire
    with patch("openjarvis.agents.scheduler.time") as mock_time:
        mock_time.time.return_value = base_time + 30
        h.scheduler._check_due_agents()

    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert agent["total_runs"] == 0

    # At base_time + 61 the agent SHOULD fire
    with patch("openjarvis.agents.scheduler.time") as mock_time:
        mock_time.time.return_value = base_time + 61
        h.scheduler._check_due_agents()

    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert agent["total_runs"] == 1
    assert "Interval response." in agent["summary_memory"]


# ---------------------------------------------------------------------------
# Scenario 3: Cron-scheduled agent
# ---------------------------------------------------------------------------


def test_cron_scheduled_agent(scenario_harness: ScenarioHarness) -> None:
    """Cron agent gets next_fire set correctly."""
    h = scenario_harness

    agent = h.manager.create_agent(
        name="cron-agent",
        config={
            "schedule_type": "cron",
            "schedule_value": "0 9 * * *",
            "instruction": "Daily check.",
        },
    )
    aid = agent["id"]

    h.scheduler.register_agent(aid)

    info = h.scheduler._agents[aid]
    assert info["schedule_type"] == "cron"
    # next_fire should be in the future
    import time

    assert info["next_fire"] > time.time()


# ---------------------------------------------------------------------------
# Scenario 4: Queued message delivery
# ---------------------------------------------------------------------------


def test_queued_message_delivery(scenario_harness: ScenarioHarness) -> None:
    """Queue 3 messages, run tick, verify all delivered and in prompt."""
    h = scenario_harness
    h.engine._responses = [{"content": "Processed all messages."}]
    h.engine._call_count = 0

    agent = h.manager.create_agent(
        name="msg-agent",
        config={"schedule_type": "manual", "instruction": "Handle messages."},
    )
    aid = agent["id"]

    h.manager.send_message(aid, "Message one", mode="queued")
    h.manager.send_message(aid, "Message two", mode="queued")
    h.manager.send_message(aid, "Message three", mode="queued")

    # Verify 3 pending before tick
    pending = h.manager.get_pending_messages(aid)
    assert len(pending) == 3

    h.executor.execute_tick(aid)

    # All should be delivered
    pending = h.manager.get_pending_messages(aid)
    assert len(pending) == 0

    # Engine should have been called with messages in the prompt
    assert h.engine.last_messages is not None
    prompt_text = " ".join(
        str(getattr(m, "content", m)) for m in h.engine.last_messages
    )
    assert "Message one" in prompt_text
    assert "Message two" in prompt_text
    assert "Message three" in prompt_text

    # Response stored
    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert "Processed all messages." in agent["summary_memory"]


# ---------------------------------------------------------------------------
# Scenario 5: Immediate message
# ---------------------------------------------------------------------------


def test_immediate_message(scenario_harness: ScenarioHarness) -> None:
    """Send an immediate message, run tick, assert response stored."""
    h = scenario_harness
    h.engine._responses = [{"content": "Immediate reply."}]
    h.engine._call_count = 0

    agent = h.manager.create_agent(
        name="imm-agent",
        config={"schedule_type": "manual", "instruction": "Reply to user."},
    )
    aid = agent["id"]

    h.manager.send_message(aid, "Urgent question", mode="immediate")

    h.executor.execute_tick(aid)

    # The response should be stored
    messages = h.manager.list_messages(aid)
    responses = [m for m in messages if m["direction"] == "agent_to_user"]
    assert len(responses) >= 1
    assert any("Immediate reply." in r["content"] for r in responses)


# ---------------------------------------------------------------------------
# Scenario 6: Budget enforcement
# ---------------------------------------------------------------------------


def test_budget_enforcement(scenario_harness: ScenarioHarness) -> None:
    """Agent with max_cost runs tick, total_runs incremented, stays idle
    because cost is below threshold."""
    h = scenario_harness
    # The default usage in FakeEngine reports 0 cost (no cost key in metadata),
    # so total_cost stays at 0 which is below max_cost=0.01.
    h.engine._responses = [{"content": "Budget check."}]
    h.engine._call_count = 0

    agent = h.manager.create_agent(
        name="budget-agent",
        config={
            "schedule_type": "manual",
            "max_cost": 0.01,
            "instruction": "Cheap task.",
        },
    )
    aid = agent["id"]

    h.executor.execute_tick(aid)

    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert agent["total_runs"] == 1
    # Cost is 0 (FakeEngine doesn't report cost), so stays idle
    assert agent["status"] == "idle"


# ---------------------------------------------------------------------------
# Scenario 7: Error + retry (success on 3rd attempt)
# ---------------------------------------------------------------------------


def test_error_retry_success(scenario_harness: ScenarioHarness) -> None:
    """FakeEngine raises RetryableError first 2 times, succeeds on 3rd."""
    h = scenario_harness
    h.engine._responses = [
        {"raise": RetryableError("transient-1")},
        {"raise": RetryableError("transient-2")},
        {"content": "Success after retries."},
    ]
    h.engine._call_count = 0

    agent = h.manager.create_agent(
        name="retry-agent",
        config={"schedule_type": "manual", "instruction": "Retry test."},
    )
    aid = agent["id"]

    # Patch retry_delay to avoid real sleeps
    with patch("openjarvis.agents.executor.time.sleep"):
        h.executor.execute_tick(aid)

    assert h.engine.call_count == 3
    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert agent["status"] == "idle"
    assert "Success after retries." in agent["summary_memory"]


# ---------------------------------------------------------------------------
# Scenario 7b: Error exhaustion
# ---------------------------------------------------------------------------


def test_error_exhaustion(scenario_harness: ScenarioHarness) -> None:
    """FakeEngine always raises RetryableError. Agent ends in error state."""
    h = scenario_harness
    h.engine._responses = [
        {"raise": RetryableError("fail-1")},
        {"raise": RetryableError("fail-2")},
        {"raise": RetryableError("fail-3")},
    ]
    h.engine._call_count = 0

    agent = h.manager.create_agent(
        name="exhaust-agent",
        config={"schedule_type": "manual", "instruction": "Always fail."},
    )
    aid = agent["id"]

    with patch("openjarvis.agents.executor.time.sleep"):
        h.executor.execute_tick(aid)

    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert agent["status"] == "error"


# ---------------------------------------------------------------------------
# Scenario 8: Stall detection + recovery
# ---------------------------------------------------------------------------


def test_stall_detection_and_recovery(scenario_harness: ScenarioHarness) -> None:
    """Set agent to running with stale last_activity, reconcile detects stall,
    then recover resets to idle."""
    h = scenario_harness
    import time as real_time

    agent = h.manager.create_agent(
        name="stall-agent",
        config={
            "schedule_type": "manual",
            "timeout_seconds": 300,
            "max_stall_retries": 5,
            "instruction": "Long task.",
        },
    )
    aid = agent["id"]

    # Simulate: agent is running with stale activity
    h.manager.start_tick(aid)
    ten_minutes_ago = real_time.time() - 600
    h.manager.update_agent(aid, last_activity_at=ten_minutes_ago)

    # Reconcile should detect the stall
    h.scheduler._reconcile()

    agent = h.manager.get_agent(aid)
    assert agent is not None
    # Stall detection should have released the concurrency guard (end_tick)
    # and incremented stall_retries
    assert agent["status"] == "idle"
    assert agent["stall_retries"] == 1

    # Verify stall event was published
    stall_events = [
        e for e in h.bus.history if e.event_type == EventType.AGENT_STALL_DETECTED
    ]
    assert len(stall_events) >= 1
    assert stall_events[0].data["agent_id"] == aid

    # Now recover the agent explicitly
    h.manager.recover_agent(aid)
    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert agent["status"] == "idle"


# ---------------------------------------------------------------------------
# Scenario 9: Pause / resume
# ---------------------------------------------------------------------------


def test_pause_resume(scenario_harness: ScenarioHarness) -> None:
    """Paused agent does not fire; resumed agent fires normally."""
    h = scenario_harness
    h.engine._responses = [{"content": "Resumed response."}]
    h.engine._call_count = 0

    base_time = 2_000_000.0

    agent = h.manager.create_agent(
        name="pause-agent",
        config={
            "schedule_type": "interval",
            "schedule_value": 60,
            "instruction": "Pause test.",
        },
    )
    aid = agent["id"]

    # Register at base_time
    with patch("openjarvis.agents.scheduler.time") as mock_time:
        mock_time.time.return_value = base_time
        h.scheduler.register_agent(aid)

    # Pause the agent
    h.manager.pause_agent(aid)

    # Advance past interval — should NOT fire because paused
    with patch("openjarvis.agents.scheduler.time") as mock_time:
        mock_time.time.return_value = base_time + 61
        h.scheduler._check_due_agents()

    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert agent["total_runs"] == 0

    # Resume
    h.manager.resume_agent(aid)

    # Now advance again — should fire
    with patch("openjarvis.agents.scheduler.time") as mock_time:
        mock_time.time.return_value = base_time + 61
        h.scheduler._check_due_agents()

    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert agent["total_runs"] == 1


# ---------------------------------------------------------------------------
# Scenario 10: Multi-agent concurrent scheduling
# ---------------------------------------------------------------------------


def test_multi_agent_scheduling(scenario_harness: ScenarioHarness) -> None:
    """Three agents with different intervals fire at the right times."""
    h = scenario_harness
    h.engine._responses = [{"content": "Agent response."}]
    h.engine._call_count = 0

    base_time = 3_000_000.0

    agents = []
    for i, interval in enumerate([30, 60, 120]):
        a = h.manager.create_agent(
            name=f"multi-{i}",
            config={
                "schedule_type": "interval",
                "schedule_value": interval,
                "instruction": f"Task {i}.",
            },
        )
        agents.append(a)
        with patch("openjarvis.agents.scheduler.time") as mock_time:
            mock_time.time.return_value = base_time
            h.scheduler.register_agent(a["id"])

    # At base_time + 35, only agent 0 (30s interval) should fire
    h.engine._call_count = 0
    with patch("openjarvis.agents.scheduler.time") as mock_time:
        mock_time.time.return_value = base_time + 35
        h.scheduler._check_due_agents()

    a0 = h.manager.get_agent(agents[0]["id"])
    a1 = h.manager.get_agent(agents[1]["id"])
    a2 = h.manager.get_agent(agents[2]["id"])
    assert a0 is not None and a0["total_runs"] == 1
    assert a1 is not None and a1["total_runs"] == 0
    assert a2 is not None and a2["total_runs"] == 0

    # At base_time + 65, agents 0 and 1 should have fired (but agent 0
    # next_fire was reset to base_time + 35 + 30 = base_time + 65, so it
    # fires again at exactly 65)
    h.engine._responses = [{"content": "Agent response again."}]
    h.engine._call_count = 0
    with patch("openjarvis.agents.scheduler.time") as mock_time:
        mock_time.time.return_value = base_time + 65
        h.scheduler._check_due_agents()

    a0 = h.manager.get_agent(agents[0]["id"])
    a1 = h.manager.get_agent(agents[1]["id"])
    a2 = h.manager.get_agent(agents[2]["id"])
    assert a0 is not None and a0["total_runs"] == 2
    assert a1 is not None and a1["total_runs"] == 1
    assert a2 is not None and a2["total_runs"] == 0

    # At base_time + 125, all three should have fired
    h.engine._responses = [{"content": "All fired."}]
    h.engine._call_count = 0
    with patch("openjarvis.agents.scheduler.time") as mock_time:
        mock_time.time.return_value = base_time + 125
        h.scheduler._check_due_agents()

    a0 = h.manager.get_agent(agents[0]["id"])
    a1 = h.manager.get_agent(agents[1]["id"])
    a2 = h.manager.get_agent(agents[2]["id"])
    assert a0 is not None and a0["total_runs"] >= 3
    assert a1 is not None and a1["total_runs"] >= 2
    assert a2 is not None and a2["total_runs"] == 1


# ---------------------------------------------------------------------------
# Scenario 11: Template instantiation
# ---------------------------------------------------------------------------


def test_template_instantiation(scenario_harness: ScenarioHarness) -> None:
    """Each built-in template creates an agent with correct config fields."""
    h = scenario_harness

    templates = h.manager.list_templates()

    for tpl in templates:
        tpl_id = tpl.get("id")
        if not tpl_id:
            continue

        agent = h.manager.create_from_template(tpl_id, name=f"from-{tpl_id}")
        config = agent["config"]

        # Every template has a schedule_type and schedule_value
        assert "schedule_type" in config
        assert "schedule_value" in config
        # Every template has a system_prompt
        assert "system_prompt" in config
        # Agent type should be set
        assert agent["agent_type"] == tpl.get("agent_type", "monitor_operative")


# ---------------------------------------------------------------------------
# Scenario 12: Memory persistence across ticks
# ---------------------------------------------------------------------------


def test_memory_persistence_across_ticks(scenario_harness: ScenarioHarness) -> None:
    """Tick 1 summary becomes part of tick 2 engine prompt (Previous context)."""
    h = scenario_harness
    h.engine._responses = [{"content": "Findings from tick one."}]
    h.engine._call_count = 0

    agent = h.manager.create_agent(
        name="memory-agent",
        config={
            "schedule_type": "manual",
            "instruction": "Investigate topic X.",
        },
    )
    aid = agent["id"]

    # --- Tick 1 ---
    h.executor.execute_tick(aid)

    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert "Findings from tick one." in agent["summary_memory"]

    # --- Tick 2 ---
    h.engine._responses = [{"content": "Tick two builds on prior context."}]
    h.engine._call_count = 0

    h.executor.execute_tick(aid)

    # The engine should have received the tick-1 summary in its prompt
    assert h.engine.last_messages is not None
    prompt_text = " ".join(
        str(getattr(m, "content", m)) for m in h.engine.last_messages
    )
    assert "Findings from tick one." in prompt_text

    # Tick 2 summary should now be stored
    agent = h.manager.get_agent(aid)
    assert agent is not None
    assert "Tick two builds on prior context." in agent["summary_memory"]
