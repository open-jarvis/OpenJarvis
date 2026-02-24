"""Tests for backward compatibility of renamed agents."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.agents.native_react import NativeReActAgent
from openjarvis.core.registry import AgentRegistry


class TestReActBackwardCompat:
    def test_old_import_path(self):
        """Old import ``from openjarvis.agents.react import ReActAgent`` works."""
        from openjarvis.agents.react import ReActAgent

        # ReActAgent is actually NativeReActAgent
        assert ReActAgent is NativeReActAgent

    def test_registry_alias(self):
        """``AgentRegistry.get("react")`` returns NativeReActAgent."""
        # Ensure registration
        AgentRegistry.register_value("native_react", NativeReActAgent)
        if not AgentRegistry.contains("react"):
            AgentRegistry.register_value("react", NativeReActAgent)

        react_cls = AgentRegistry.get("react")
        native_cls = AgentRegistry.get("native_react")
        assert react_cls is native_cls

    def test_old_class_instantiates(self):
        """ReActAgent (alias) can be instantiated and has correct agent_id."""
        from openjarvis.agents.react import ReActAgent

        engine = MagicMock()
        engine.engine_id = "mock"
        agent = ReActAgent(engine, "test-model")
        assert agent.agent_id == "native_react"

    def test_react_system_prompt_importable(self):
        """REACT_SYSTEM_PROMPT can be imported from old path."""
        from openjarvis.agents.react import REACT_SYSTEM_PROMPT

        assert "ReAct" in REACT_SYSTEM_PROMPT
