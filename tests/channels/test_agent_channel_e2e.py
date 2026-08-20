"""Agent-channel E2E tests — using WebChatChannel (in-memory, no external deps)."""

from __future__ import annotations

from tests.agents.scenario_harness import ScenarioHarness


def test_agent_sends_to_webchat(scenario_harness: ScenarioHarness):
    """Agent runs and completes tick with WebChatChannel available."""
    from openjarvis.channels.webchat import WebChatChannel

    h = scenario_harness
    webchat = WebChatChannel()
    webchat.connect()

    agent = h.manager.create_agent(
        "Channel Agent",
        config={
            "schedule_type": "manual",
            "instruction": "Send a report to the general channel.",
        },
    )

    h.executor.execute_tick(agent["id"])
    data = h.manager.get_agent(agent["id"])
    assert data["status"] == "idle"
    assert data["total_runs"] == 1
    webchat.disconnect()


def test_channel_failure_does_not_crash_agent(scenario_harness: ScenarioHarness):
    """Agent continues if channel send fails."""
    h = scenario_harness
    agent = h.manager.create_agent(
        "Resilient Agent",
        config={
            "schedule_type": "manual",
            "instruction": "Try to send a message.",
        },
    )

    h.executor.execute_tick(agent["id"])
    data = h.manager.get_agent(agent["id"])
    assert data["status"] == "idle"
    assert data["total_runs"] == 1


def test_agent_with_channel_binding(scenario_harness: ScenarioHarness):
    """Agent with a channel binding completes tick without error."""
    from openjarvis.channels.webchat import WebChatChannel

    h = scenario_harness
    webchat = WebChatChannel()
    webchat.connect()

    agent = h.manager.create_agent(
        "Bound Agent",
        config={
            "schedule_type": "manual",
            "instruction": "Monitor and report.",
        },
    )
    aid = agent["id"]

    # Bind a channel
    h.manager.bind_channel(aid, "webchat", config={"channel": "general"})
    bindings = h.manager.list_channel_bindings(aid)
    assert len(bindings) == 1

    h.executor.execute_tick(aid)
    data = h.manager.get_agent(aid)
    assert data["status"] == "idle"
    webchat.disconnect()
