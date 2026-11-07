"""Shared fixtures for agent tests."""

from __future__ import annotations

import pytest

from friday_ai.agents.executor import AgentExecutor
from friday_ai.agents.manager import AgentManager
from friday_ai.agents.scheduler import AgentScheduler
from friday_ai.core.events import EventBus
from tests.agents.fake_engine import FakeEngine
from tests.agents.scenario_harness import FakeSystem, ScenarioHarness


@pytest.fixture
def scenario_harness(tmp_path):
    """Wire up real components for agent lifecycle testing."""
    from friday_ai.agents.monitor_operative import MonitorOperativeAgent
    from friday_ai.core.registry import AgentRegistry

    # Re-register agent types (conftest auto-clears registries)
    if not AgentRegistry.contains("monitor_operative"):
        AgentRegistry.register("monitor_operative")(MonitorOperativeAgent)

    db_path = str(tmp_path / "agents.db")
    bus = EventBus(record_history=True)
    manager = AgentManager(db_path=db_path)

    engine = FakeEngine([{"content": "Default response."}])
    system = FakeSystem(engine=engine)

    executor = AgentExecutor(manager=manager, event_bus=bus)
    executor.set_system(system)

    scheduler = AgentScheduler(
        manager=manager,
        executor=executor,
        event_bus=bus,
    )

    return ScenarioHarness(
        manager=manager,
        executor=executor,
        scheduler=scheduler,
        bus=bus,
        engine=engine,
        system=system,
        db_path=db_path,
    )
