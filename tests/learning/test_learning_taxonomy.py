"""Tests for the learning policy ABC taxonomy."""

from __future__ import annotations

import pytest

from friday_ai.learning._stubs import (
    AgentLearningPolicy,
    IntelligenceLearningPolicy,
    LearningPolicy,
)


class TestLearningPolicyABC:
    def test_cannot_instantiate_base(self):
        with pytest.raises(TypeError):
            LearningPolicy()

    def test_cannot_instantiate_intelligence(self):
        with pytest.raises(TypeError):
            IntelligenceLearningPolicy()

    def test_cannot_instantiate_agent(self):
        with pytest.raises(TypeError):
            AgentLearningPolicy()

    def test_target_intelligence(self):
        assert IntelligenceLearningPolicy.target == "intelligence"

    def test_target_agent(self):
        assert AgentLearningPolicy.target == "agent"

    def test_hierarchy(self):
        assert issubclass(IntelligenceLearningPolicy, LearningPolicy)
        assert issubclass(AgentLearningPolicy, LearningPolicy)
