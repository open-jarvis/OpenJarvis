"""Tests for AgentScheduler tick scheduling."""

from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def manager():
    from openjarvis.agents.manager import AgentManager

    with tempfile.TemporaryDirectory() as tmpdir:
        mgr = AgentManager(db_path=str(Path(tmpdir) / "agents.db"))
        yield mgr
        mgr.close()


class TestSchedulerBasic:
    def test_create_scheduler(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)
        assert scheduler is not None

    def test_register_agent_with_interval(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "interval", "schedule_value": 60},
        )
        scheduler.register_agent(agent["id"])
        assert agent["id"] in scheduler.registered_agents

    def test_register_agent_with_cron(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "cron", "schedule_value": "0 9 * * *"},
        )
        scheduler.register_agent(agent["id"])
        assert agent["id"] in scheduler.registered_agents

    def test_deregister_agent(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "interval", "schedule_value": 60},
        )
        scheduler.register_agent(agent["id"])
        scheduler.deregister_agent(agent["id"])
        assert agent["id"] not in scheduler.registered_agents

    def test_manual_schedule_not_auto_registered(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "manual"},
        )
        scheduler.register_agent(agent["id"])
        # Manual agents are registered but never auto-fired
        assert agent["id"] in scheduler.registered_agents

    def test_start_stop(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(manager=manager, executor=executor)
        scheduler.start()
        assert scheduler.is_running
        scheduler.stop()
        assert not scheduler.is_running

    def test_tick_fires_executor(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(
            manager=manager, executor=executor, tick_interval=0.1
        )

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "interval", "schedule_value": 0},
        )
        scheduler.register_agent(agent["id"])
        scheduler.start()
        time.sleep(0.5)
        scheduler.stop()

        assert executor.execute_tick.call_count >= 1
        executor.execute_tick.assert_called_with(agent["id"])

    def test_two_phase_stop_retains_and_drains_active_worker(self, manager):
        """Shutdown quiesces later ticks and can wait again after cancellation."""

        from openjarvis.agents.scheduler import AgentScheduler

        started = threading.Event()
        release = threading.Event()
        calls: list[str] = []

        class _BlockingExecutor:
            def execute_tick(self, agent_id):
                calls.append(agent_id)
                started.set()
                release.wait(timeout=2)

        scheduler = AgentScheduler(
            manager=manager,
            executor=_BlockingExecutor(),
            tick_interval=0.01,
        )
        agents = [
            manager.create_agent(
                name=f"test-{index}",
                agent_type="monitor_operative",
                config={"schedule_type": "interval", "schedule_value": 0},
            )
            for index in range(2)
        ]
        for agent in agents:
            scheduler.register_agent(agent["id"])

        scheduler.start()
        assert started.wait(timeout=1)
        scheduler.request_stop()
        assert scheduler.wait_stopped(timeout=0.01) is False
        assert scheduler._thread is not None

        release.set()
        assert scheduler.wait_stopped(timeout=1) is True
        assert scheduler._thread is None
        assert calls == [agents[0]["id"]]

    def test_skips_paused_agents(self, manager):
        from openjarvis.agents.scheduler import AgentScheduler

        executor = MagicMock()
        scheduler = AgentScheduler(
            manager=manager, executor=executor, tick_interval=0.1
        )

        agent = manager.create_agent(
            name="test",
            agent_type="monitor_operative",
            config={"schedule_type": "interval", "schedule_value": 0},
        )
        manager.pause_agent(agent["id"])
        scheduler.register_agent(agent["id"])
        scheduler.start()
        time.sleep(0.3)
        scheduler.stop()

        executor.execute_tick.assert_not_called()
