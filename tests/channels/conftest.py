"""Shared fixtures for channel integration tests."""

from __future__ import annotations

import os
from contextlib import contextmanager

import pytest

from friday_ai.core.events import EventBus
from tests.agents.fake_engine import FakeEngine
from tests.agents.scenario_harness import FakeSystem, ScenarioHarness


@pytest.fixture
def scenario_harness(tmp_path):
    """Wire up real components for agent lifecycle testing (channels copy)."""
    from friday_ai.agents.executor import AgentExecutor
    from friday_ai.agents.manager import AgentManager
    from friday_ai.agents.monitor_operative import MonitorOperativeAgent
    from friday_ai.agents.scheduler import AgentScheduler
    from friday_ai.core.registry import AgentRegistry

    if not AgentRegistry.contains("monitor_operative"):
        AgentRegistry.register("monitor_operative")(MonitorOperativeAgent)

    db_path = str(tmp_path / "agents.db")
    bus = EventBus(record_history=True)
    manager = AgentManager(db_path=db_path)
    engine = FakeEngine([{"content": "Default response."}])
    system = FakeSystem(engine=engine)
    executor = AgentExecutor(manager=manager, event_bus=bus)
    executor.set_system(system)
    scheduler = AgentScheduler(manager=manager, executor=executor, event_bus=bus)

    return ScenarioHarness(
        manager=manager,
        executor=executor,
        scheduler=scheduler,
        bus=bus,
        engine=engine,
        system=system,
        db_path=db_path,
    )


@pytest.fixture
def fake_event_bus() -> EventBus:
    """EventBus with history recording for asserting event emissions."""
    return EventBus(record_history=True)


@contextmanager
def credential_env(channel_name: str, **creds: str):
    """Context manager that sets env vars for a channel, cleans up after."""
    prefix = channel_name.upper()
    old_values = {}
    for key, value in creds.items():
        env_key = f"{prefix}_{key.upper()}"
        old_values[env_key] = os.environ.get(env_key)
        os.environ[env_key] = value
    try:
        yield
    finally:
        for env_key, old in old_values.items():
            if old is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = old
