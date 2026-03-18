"""Tests for orchestrator learning types."""

from __future__ import annotations

import pytest

from openjarvis.learning.intelligence.orchestrator.types import (
    Episode,
    EpisodeState,
    OrchestratorAction,
    OrchestratorObservation,
    PolicyOutput,
    extract_answer,
    grade_answer,
    normalize_number,
)


class TestOrchestratorAction:
    def test_create(self):
        a = OrchestratorAction(
            thought="use calc", tool_name="calculator", tool_input="2+2"
        )
        assert a.thought == "use calc"
        assert a.tool_name == "calculator"
        assert a.tool_input == "2+2"
        assert a.is_final_answer is False

    def test_final_answer(self):
        a = OrchestratorAction(
            thought="done",
            tool_name="",
            tool_input="42",
            is_final_answer=True,
        )
        assert a.is_final_answer is True


class TestOrchestratorObservation:
    def test_create(self):
        o = OrchestratorObservation(
            content="4",
            latency_seconds=0.1,
            cost_usd=0.01,
            energy_joules=5.0,
            power_watts=100.0,
            tokens=10,
        )
        assert o.content == "4"
        assert o.latency_seconds == 0.1
        assert o.tokens == 10

    def test_defaults(self):
        o = OrchestratorObservation(content="ok")
        assert o.latency_seconds == 0.0
        assert o.cost_usd == 0.0
        assert o.energy_joules == 0.0
        assert o.power_watts == 0.0
        assert o.tokens == 0


class TestEpisode:
    def _make_episode(self) -> Episode:
        ep = Episode(
            task_id="t1",
            initial_prompt="What is 2+2?",
            ground_truth="4",
        )
        action = OrchestratorAction(
            thought="calc", tool_name="calculator", tool_input="2+2"
        )
        obs = OrchestratorObservation(
            content="4",
            latency_seconds=0.5,
            cost_usd=0.01,
            energy_joules=10.0,
            power_watts=50.0,
            tokens=5,
        )
        ep.add_step(action, obs)
        return ep

    def test_add_step_updates_aggregates(self):
        ep = self._make_episode()
        assert ep.num_turns() == 1
        assert ep.total_latency_seconds == 0.5
        assert ep.total_cost_usd == 0.01
        assert ep.total_energy_joules == 10.0
        assert ep.max_power_watts == 50.0
        assert ep.total_tokens == 5

    def test_add_step_max_power(self):
        ep = self._make_episode()
        action2 = OrchestratorAction(
            thought="again", tool_name="calc", tool_input="3+3"
        )
        obs2 = OrchestratorObservation(
            content="6", power_watts=200.0, energy_joules=5.0
        )
        ep.add_step(action2, obs2)
        assert ep.max_power_watts == 200.0
        assert ep.total_energy_joules == 15.0

    def test_final_answer_set_on_is_final(self):
        ep = Episode(task_id="t", initial_prompt="q", ground_truth="4")
        action = OrchestratorAction(
            thought="done",
            tool_name="calc",
            tool_input="4",
            is_final_answer=True,
        )
        obs = OrchestratorObservation(content="4")
        ep.add_step(action, obs)
        assert ep.final_answer == "4"

    def test_compute_ipj_correct(self):
        ep = self._make_episode()
        ep.correct = True
        assert ep.compute_ipj() == pytest.approx(1.0 / 10.0)

    def test_compute_ipj_incorrect(self):
        ep = self._make_episode()
        ep.correct = False
        assert ep.compute_ipj() == 0.0

    def test_compute_ipj_zero_energy(self):
        ep = Episode(task_id="t", initial_prompt="q", correct=True)
        assert ep.compute_ipj() == 0.0

    def test_to_dict(self):
        ep = self._make_episode()
        ep.correct = True
        d = ep.to_dict()
        assert d["task_id"] == "t1"
        assert d["num_turns"] == 1
        assert d["correct"] is True
        assert d["ipj"] > 0
        assert len(d["steps"]) == 1
        assert d["steps"][0]["tool"] == "calculator"


class TestEpisodeState:
    def test_create(self):
        state = EpisodeState(initial_prompt="Hello")
        assert state.num_turns() == 0
        assert state.final_answer is None

    def test_add_turn(self):
        state = EpisodeState(initial_prompt="q")
        action = OrchestratorAction(thought="t", tool_name="calc", tool_input="1+1")
        obs = OrchestratorObservation(content="2")
        state.add_turn(action, obs)
        assert state.num_turns() == 1

    def test_final_answer(self):
        state = EpisodeState(initial_prompt="q")
        action = OrchestratorAction(
            thought="t",
            tool_name="calc",
            tool_input="1+1",
            is_final_answer=True,
        )
        obs = OrchestratorObservation(content="2")
        state.add_turn(action, obs)
        assert state.final_answer == "2"

    def test_to_episode(self):
        state = EpisodeState(initial_prompt="q")
        action = OrchestratorAction(
            thought="t",
            tool_name="calc",
            tool_input="1+1",
            is_final_answer=True,
        )
        obs = OrchestratorObservation(
            content="2", latency_seconds=1.0, energy_joules=5.0
        )
        state.add_turn(action, obs)
        ep = state.to_episode(task_id="t1", ground_truth="2", correct=True)
        assert ep.task_id == "t1"
        assert ep.correct is True
        assert ep.num_turns() == 1
        assert ep.total_energy_joules == 5.0


class TestGradeAnswer:
    def test_exact_match(self):
        assert grade_answer("4", "4") is True

    def test_case_insensitive(self):
        assert grade_answer("Paris", "paris") is True

    def test_numeric_match(self):
        assert grade_answer("4.0", "4") is True

    def test_numeric_tolerance(self):
        assert grade_answer("3.999999", "4") is True

    def test_extracted_answer(self):
        assert grade_answer("The answer is 4", "4") is True

    def test_wrong_answer(self):
        assert grade_answer("5", "4") is False

    def test_empty(self):
        assert grade_answer("", "4") is False


class TestExtractAnswer:
    def test_simple(self):
        assert extract_answer("4") == "4"

    def test_verbose(self):
        assert extract_answer("The answer is 42") == "42"

    def test_result_prefix(self):
        assert extract_answer("Result: 100") == "100"


class TestNormalizeNumber:
    def test_integer(self):
        assert normalize_number("42") == 42.0

    def test_float(self):
        assert normalize_number("3.14") == pytest.approx(3.14)

    def test_commas(self):
        assert normalize_number("1,000") == 1000.0

    def test_invalid(self):
        assert normalize_number("abc") is None


class TestPolicyOutput:
    def test_create(self):
        po = PolicyOutput(
            thought="t",
            tool_name="calc",
            tool_input="2+2",
        )
        assert po.is_final_answer is False
        assert po.confidence == 1.0
