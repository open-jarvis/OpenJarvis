"""Tests for continuation handling (Phase 14.2)."""

from __future__ import annotations

from typing import Any, Dict, List

from openjarvis.agents._stubs import AgentResult, BaseAgent


class MockEngine:
    """Mock engine that simulates finish_reason='length'."""

    def __init__(self, responses: List[Dict[str, Any]]):
        self._responses = list(responses)
        self._call_count = 0

    def generate(self, messages, **kwargs):
        if self._call_count < len(self._responses):
            resp = self._responses[self._call_count]
        else:
            resp = {"content": "done", "finish_reason": "stop"}
        self._call_count += 1
        return resp

    def list_models(self):
        return ["test-model"]

    def health(self):
        return True


class ContinuationAgent(BaseAgent):
    """Agent that exercises _check_continuation."""

    agent_id = "test_continuation"

    def run(self, input, context=None, **kwargs):
        messages = self._build_messages(input, context)
        result = self._generate(messages)
        content = self._check_continuation(result, messages)
        return AgentResult(content=content, turns=1)


class TestContinuation:
    def test_no_continuation_needed(self):
        engine = MockEngine(
            [
                {"content": "Hello world", "finish_reason": "stop"},
            ]
        )
        agent = ContinuationAgent(engine, "test-model")
        result = agent.run("Hi")
        assert result.content == "Hello world"

    def test_single_continuation(self):
        engine = MockEngine(
            [
                {"content": "Part 1...", "finish_reason": "length"},
                {"content": " Part 2.", "finish_reason": "stop"},
            ]
        )
        agent = ContinuationAgent(engine, "test-model")
        result = agent.run("Hi")
        assert result.content == "Part 1... Part 2."

    def test_multiple_continuations(self):
        engine = MockEngine(
            [
                {"content": "A", "finish_reason": "length"},
                {"content": "B", "finish_reason": "length"},
                {"content": "C", "finish_reason": "stop"},
            ]
        )
        agent = ContinuationAgent(engine, "test-model")
        result = agent.run("Hi")
        assert result.content == "ABC"

    def test_max_continuations_respected(self):
        engine = MockEngine(
            [
                {"content": "A", "finish_reason": "length"},
                {"content": "B", "finish_reason": "length"},
                {"content": "C", "finish_reason": "length"},  # 3rd continuation
                {"content": "D", "finish_reason": "stop"},
            ]
        )
        agent = ContinuationAgent(engine, "test-model")
        # Default max_continuations=2, so should stop after 2 continuations
        messages = agent._build_messages("Hi")
        result_dict = agent._generate(messages)
        content = agent._check_continuation(result_dict, messages, max_continuations=2)
        assert content == "ABC"  # A + B + C, but not D

    def test_empty_finish_reason(self):
        engine = MockEngine(
            [
                {"content": "Done", "finish_reason": ""},
            ]
        )
        agent = ContinuationAgent(engine, "test-model")
        result = agent.run("Hi")
        assert result.content == "Done"
