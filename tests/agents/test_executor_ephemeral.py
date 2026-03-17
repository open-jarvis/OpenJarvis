from __future__ import annotations

from unittest.mock import MagicMock, patch

REGISTRY_PATH = "openjarvis.core.registry.AgentRegistry.get"


def test_run_ephemeral_creates_and_runs_agent():
    from openjarvis.agents.executor import AgentExecutor

    manager = MagicMock()
    executor = AgentExecutor(manager=manager, event_bus=MagicMock())

    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_instance.run.return_value = MagicMock(content="Flushed.")
    mock_agent_cls.return_value = mock_agent_instance

    with patch(REGISTRY_PATH, return_value=mock_agent_cls):
        executor.run_ephemeral(
            agent_type="simple",
            system_prompt="Save important context.",
            input_text="Review and flush.",
        )
    assert mock_agent_instance.run.called


def test_run_ephemeral_passes_input():
    from openjarvis.agents.executor import AgentExecutor

    manager = MagicMock()
    executor = AgentExecutor(manager=manager, event_bus=MagicMock())

    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_instance.run.return_value = MagicMock(content="Done.")
    mock_agent_cls.return_value = mock_agent_instance

    with patch(REGISTRY_PATH, return_value=mock_agent_cls):
        executor.run_ephemeral(
            agent_type="simple",
            system_prompt="Test prompt.",
            input_text="Hello world",
        )
    mock_agent_instance.run.assert_called_once_with("Hello world")
