"""Tests for orchestrator policy model."""

from __future__ import annotations

import pytest

from openjarvis.learning.intelligence.orchestrator.policy_model import (
    OrchestratorPolicyModel,
)
from openjarvis.learning.intelligence.orchestrator.types import (
    EpisodeState,
    OrchestratorAction,
    OrchestratorObservation,
)


class TestParseOutput:
    """Test _parse_output without loading a real model."""

    def _model(self) -> OrchestratorPolicyModel:
        return OrchestratorPolicyModel()

    def test_valid_thought_tool_input(self):
        m = self._model()
        text = "THOUGHT: I need to calculate 2+2\nTOOL: calculator\nINPUT: 2+2"
        po = m._parse_output(text, ["calculator", "think"])
        assert po.thought == "I need to calculate 2+2"
        assert po.tool_name == "calculator"
        assert po.tool_input == "2+2"
        assert po.is_final_answer is False

    def test_final_answer(self):
        m = self._model()
        text = "THOUGHT: I have the result\nFINAL_ANSWER: 42"
        po = m._parse_output(text, ["calculator"])
        assert po.is_final_answer is True
        assert po.tool_input == "42"

    def test_final_answer_with_space(self):
        m = self._model()
        text = "FINAL ANSWER: the result is 7"
        po = m._parse_output(text, ["calculator"])
        assert po.is_final_answer is True

    def test_missing_fields_fallback(self):
        m = self._model()
        text = "just some random output"
        po = m._parse_output(text, ["calculator", "think"])
        # Should fallback to first available tool
        assert po.tool_name == "calculator"
        assert po.thought == "No thought provided"

    def test_invalid_tool_name_fallback(self):
        m = self._model()
        text = "THOUGHT: reason\nTOOL: nonexistent_tool\nINPUT: hello"
        po = m._parse_output(text, ["calculator", "think"])
        assert po.tool_name == "calculator"  # fallback

    def test_case_insensitive_tool_match(self):
        m = self._model()
        text = "THOUGHT: reason\nTOOL: Calculator\nINPUT: 5+5"
        po = m._parse_output(text, ["calculator", "think"])
        assert po.tool_name == "calculator"

    def test_empty_tools_list(self):
        m = self._model()
        text = "THOUGHT: reason\nTOOL: calc\nINPUT: 1"
        po = m._parse_output(text, [])
        assert po.tool_name == "unknown"


class TestBuildPrompt:
    def test_includes_task(self):
        m = OrchestratorPolicyModel()
        state = EpisodeState(initial_prompt="What is 2+2?")
        prompt = m._build_prompt(state, ["calculator"])
        assert "What is 2+2?" in prompt

    def test_includes_tools(self):
        m = OrchestratorPolicyModel()
        state = EpisodeState(initial_prompt="q")
        prompt = m._build_prompt(state, ["calculator", "think"])
        assert "calculator" in prompt
        assert "think" in prompt

    def test_includes_history(self):
        m = OrchestratorPolicyModel()
        state = EpisodeState(initial_prompt="q")
        action = OrchestratorAction(
            thought="use calc", tool_name="calculator", tool_input="2+2"
        )
        obs = OrchestratorObservation(content="4")
        state.add_turn(action, obs)
        prompt = m._build_prompt(state, ["calculator"])
        assert "Turn 1:" in prompt
        assert "use calc" in prompt

    def test_format_instructions(self):
        m = OrchestratorPolicyModel()
        state = EpisodeState(initial_prompt="q")
        prompt = m._build_prompt(state, ["calculator"])
        assert "THOUGHT:" in prompt
        assert "TOOL:" in prompt
        assert "INPUT:" in prompt


class TestPredictActionRequiresModel:
    def test_raises_without_model(self):
        m = OrchestratorPolicyModel()
        state = EpisodeState(initial_prompt="q")
        with pytest.raises(RuntimeError, match="Cannot generate"):
            m.predict_action(state, ["calculator"])


class TestRepr:
    def test_repr(self):
        m = OrchestratorPolicyModel()
        r = repr(m)
        assert "OrchestratorPolicyModel" in r
        assert "None" in r
