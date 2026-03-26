from openjarvis.agents._stubs import AgentResult
from openjarvis.agents.executor import AgentExecutor
from openjarvis.agents.manager import AgentManager
from openjarvis.core.events import EventBus, EventType


def test_budget_exceeded_sets_status(tmp_path):
    """Agent exceeding max_cost gets status budget_exceeded."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("expensive", config={"max_cost": 1.0})
    mgr.start_tick(agent["id"])

    result = AgentResult(content="done", metadata={"cost": 1.50, "tokens_used": 100})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "budget_exceeded"

    budget_events = [
        e for e in bus.history if e.event_type == EventType.AGENT_BUDGET_EXCEEDED
    ]
    assert len(budget_events) == 1
    mgr.close()


def test_budget_not_exceeded_stays_idle(tmp_path):
    """Agent under budget stays idle."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("cheap", config={"max_cost": 10.0})
    mgr.start_tick(agent["id"])

    result = AgentResult(content="done", metadata={"cost": 0.50, "tokens_used": 50})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "idle"
    mgr.close()


def test_budget_unlimited_skips_check(tmp_path):
    """max_cost=0 means unlimited — no budget enforcement."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("unlimited", config={"max_cost": 0})
    mgr.start_tick(agent["id"])

    result = AgentResult(
        content="done",
        metadata={"cost": 999.99, "tokens_used": 1000000},
    )
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "idle"
    mgr.close()


def test_token_budget_exceeded(tmp_path):
    """Agent exceeding max_tokens gets budget_exceeded."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("token-heavy", config={"max_tokens": 1000})
    mgr.start_tick(agent["id"])

    result = AgentResult(content="done", metadata={"cost": 0.01, "tokens_used": 1500})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "budget_exceeded"
    mgr.close()
