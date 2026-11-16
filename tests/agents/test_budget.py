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
    """Agent exceeding max_total_tokens gets budget_exceeded."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("token-heavy", config={"max_total_tokens": 1000})
    mgr.start_tick(agent["id"])

    result = AgentResult(content="done", metadata={"cost": 0.01, "tokens_used": 1500})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "budget_exceeded"
    mgr.close()


def test_per_response_max_tokens_is_not_a_lifetime_budget(tmp_path):
    """``max_tokens`` caps one response; it must not disable the agent.

    Agent templates and the agent chat route use ``config["max_tokens"]`` as
    the per-response generation limit (like ``temperature``). Reading the
    same key as a lifetime token budget flipped such agents to
    ``budget_exceeded`` once their cumulative usage passed that number, and
    the scheduler then skipped them for good.
    """
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_agent("chatty", config={"max_tokens": 4096})
    mgr.start_tick(agent["id"])

    result = AgentResult(content="done", metadata={"cost": 0.0, "tokens_used": 9000})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    updated = mgr.get_agent(agent["id"])
    assert updated["status"] == "idle"
    assert not [
        e for e in bus.history if e.event_type == EventType.AGENT_BUDGET_EXCEEDED
    ]
    mgr.close()


def test_bundled_template_agent_survives_a_tick(tmp_path):
    """An agent created from a bundled template keeps running after one tick.

    ``personal_deep_research`` ships with ``max_tokens = 4096``; a single
    research run uses more tokens than that.
    """
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus()
    executor = AgentExecutor(mgr, bus)

    agent = mgr.create_from_template("personal_deep_research", "researcher")
    assert agent["config"]["max_tokens"] == 4096
    mgr.start_tick(agent["id"])

    result = AgentResult(content="report", metadata={"tokens_used": 20000})
    executor._finalize_tick(agent["id"], result, error=None, duration=1.0)

    assert mgr.get_agent(agent["id"])["status"] == "idle"
    mgr.close()


def test_lifetime_budget_accumulates_across_ticks_with_response_limit(tmp_path):
    """A response limit and a lifetime limit remain independent."""
    mgr = AgentManager(str(tmp_path / "test.db"))
    bus = EventBus(record_history=True)
    executor = AgentExecutor(mgr, bus)
    agent = mgr.create_agent(
        "bounded", config={"max_tokens": 50, "max_total_tokens": 1000}
    )

    for tokens, expected_status in (
        (400, "idle"),
        (600, "idle"),
        (1, "budget_exceeded"),
    ):
        mgr.start_tick(agent["id"])
        result = AgentResult(content="done", metadata={"tokens_used": tokens})
        executor._finalize_tick(agent["id"], result, error=None, duration=1.0)
        assert mgr.get_agent(agent["id"])["status"] == expected_status

    events = [e for e in bus.history if e.event_type == EventType.AGENT_BUDGET_EXCEEDED]
    assert len(events) == 1
    assert events[0].data["total_tokens"] == 1001
    assert events[0].data["max_tokens"] == 1000
    mgr.close()
