"""Tests for structured error_detail in executor traces."""

from openjarvis.agents.errors import EscalateError, FatalError, RetryableError
from openjarvis.agents.executor import AgentExecutor
from openjarvis.core.events import EventBus


def test_build_error_detail_fatal(tmp_path):
    from openjarvis.agents.manager import AgentManager

    mgr = AgentManager(db_path=str(tmp_path / "agents.db"))
    exe = AgentExecutor(manager=mgr, event_bus=EventBus())
    error = FatalError("401 unauthorized")
    detail = exe._build_error_detail(error)
    assert detail["error_type"] == "fatal"
    assert "401 unauthorized" in detail["error_message"]
    assert "API key" in detail["suggested_action"]


def test_build_error_detail_retryable(tmp_path):
    from openjarvis.agents.manager import AgentManager

    mgr = AgentManager(db_path=str(tmp_path / "agents.db"))
    exe = AgentExecutor(manager=mgr, event_bus=EventBus())
    error = RetryableError("connection timed out")
    detail = exe._build_error_detail(error)
    assert detail["error_type"] == "retryable"
    assert "engine" in detail["suggested_action"].lower()


def test_build_error_detail_escalate(tmp_path):
    from openjarvis.agents.manager import AgentManager

    mgr = AgentManager(db_path=str(tmp_path / "agents.db"))
    exe = AgentExecutor(manager=mgr, event_bus=EventBus())
    error = EscalateError("agent needs help")
    detail = exe._build_error_detail(error)
    assert detail["error_type"] == "escalate"
