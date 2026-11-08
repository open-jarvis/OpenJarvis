"""Tests for intent-based agent routing in FridaySystem."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestDetectAgentIntent:
    """Test _detect_agent_intent pattern matching."""

    @pytest.fixture()
    def system(self):
        """Create a minimal FridaySystem instance for testing _detect_agent_intent."""
        from friday_ai.system import FridaySystem

        mock_engine = MagicMock()
        mock_engine.engine_name = "mock"
        sys = FridaySystem.__new__(FridaySystem)
        sys.engine = mock_engine
        sys.model = "test-model"
        sys.agent_name = "simple"
        sys.tools = []
        sys.bus = MagicMock()
        yield sys

    def test_good_morning_triggers_digest(self, system):
        with patch("friday_ai.core.registry.AgentRegistry") as reg:
            reg.contains.return_value = True
            assert system._detect_agent_intent("Good morning!") == "morning_digest"

    def test_good_morning_friday_triggers_digest(self, system):
        with patch("friday_ai.core.registry.AgentRegistry") as reg:
            reg.contains.return_value = True
            result = system._detect_agent_intent("Good morning Friday")
            assert result == "morning_digest"

    def test_morning_digest_triggers(self, system):
        with patch("friday_ai.core.registry.AgentRegistry") as reg:
            reg.contains.return_value = True
            query = "Show me my morning digest"
            assert system._detect_agent_intent(query) == "morning_digest"

    def test_daily_briefing_triggers(self, system):
        with patch("friday_ai.core.registry.AgentRegistry") as reg:
            reg.contains.return_value = True
            query = "Give me my daily briefing"
            assert system._detect_agent_intent(query) == "morning_digest"

    def test_morning_briefing_triggers(self, system):
        with patch("friday_ai.core.registry.AgentRegistry") as reg:
            reg.contains.return_value = True
            query = "morning briefing please"
            assert system._detect_agent_intent(query) == "morning_digest"

    def test_regular_question_no_trigger(self, system):
        assert system._detect_agent_intent("What is the weather?") is None

    def test_good_afternoon_no_trigger(self, system):
        assert system._detect_agent_intent("Good afternoon") is None

    def test_no_agent_registered_returns_none(self, system):
        with patch("friday_ai.core.registry.AgentRegistry") as reg:
            reg.contains.return_value = False
            assert system._detect_agent_intent("Good morning!") is None
