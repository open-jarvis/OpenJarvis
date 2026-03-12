"""Integration tests for LearningOrchestrator agent_id scoping."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.learning.learning_orchestrator import LearningOrchestrator


def test_learning_orchestrator_run_with_agent_id(tmp_path):
    """run(agent_id=...) filters traces to that agent."""
    mock_store = MagicMock()
    mock_store.list_traces.return_value = []

    orchestrator = LearningOrchestrator(
        trace_store=mock_store,
        config_dir=str(tmp_path),
    )

    result = orchestrator.run(agent_id="agent-123")
    assert result["status"] == "skipped"
    # Verify list_traces was called with agent="agent-123"
    calls = mock_store.list_traces.call_args_list
    assert any(call.kwargs.get("agent") == "agent-123" for call in calls)


def test_learning_orchestrator_run_without_agent_id(tmp_path):
    """run() without agent_id uses all traces (backwards compat)."""
    mock_store = MagicMock()
    mock_store.list_traces.return_value = []

    orchestrator = LearningOrchestrator(
        trace_store=mock_store,
        config_dir=str(tmp_path),
    )

    result = orchestrator.run()
    assert result["status"] == "skipped"


def test_scheduler_tracks_tick_count_for_learning(tmp_path):
    """Scheduler increments per-agent tick count and triggers learning."""
    from openjarvis.agents.executor import AgentExecutor
    from openjarvis.agents.manager import AgentManager
    from openjarvis.agents.scheduler import AgentScheduler
    from openjarvis.core.events import EventBus, EventType

    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)
    scheduler = AgentScheduler(mgr, executor, event_bus=bus)

    agent = mgr.create_agent("tick-counter", config={
        "learning_enabled": True,
        "learning_schedule": "every_3_ticks",
        "schedule_type": "manual",
    })

    # Simulate 3 ticks completing
    for _ in range(3):
        scheduler._on_tick_completed(agent["id"])

    # Should have triggered learning
    learning_events = [
        e for e in bus.history
        if e.event_type == EventType.AGENT_LEARNING_STARTED
    ]
    assert len(learning_events) == 1
    assert learning_events[0].data["agent_id"] == agent["id"]

    # Counter should be reset
    assert scheduler._tick_counts.get(agent["id"], 0) == 0
    mgr.close()


def test_scheduler_no_learning_when_disabled(tmp_path):
    """Scheduler does not trigger learning when learning_enabled is False."""
    from openjarvis.agents.executor import AgentExecutor
    from openjarvis.agents.manager import AgentManager
    from openjarvis.agents.scheduler import AgentScheduler
    from openjarvis.core.events import EventBus, EventType

    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)
    scheduler = AgentScheduler(mgr, executor, event_bus=bus)

    agent = mgr.create_agent("no-learning", config={
        "learning_enabled": False,
        "learning_schedule": "every_3_ticks",
    })

    for _ in range(5):
        scheduler._on_tick_completed(agent["id"])

    learning_events = [
        e for e in bus.history
        if e.event_type == EventType.AGENT_LEARNING_STARTED
    ]
    assert len(learning_events) == 0
    mgr.close()
