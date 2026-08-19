"""Tests for hypothesis generation and ranking."""

from __future__ import annotations

import pytest

from openjarvis.science_lab.hypothesis_engine import (
    generate_hypotheses,
    rank_hypotheses,
)
from openjarvis.science_lab.models import Hypothesis, PropertyAnalysis, TargetProperty
from tests.agents.fake_engine import FakeEngine


class TestGenerateHypotheses:
    def test_returns_k_hypotheses(self):
        engine = FakeEngine(
            [
                {
                    "content": (
                        '{"hypotheses": ['
                        '{"id": "H1", "mechanism": "polymer entanglement", '
                        '"key_properties": {"elasticity": "high"}, '
                        '"pros": ["a"], "cons": ["b"]}, '
                        '{"id": "H2", "mechanism": "protein fiber network", '
                        '"key_properties": {}, "pros": [], "cons": []}]}'
                    )
                }
            ]
        )
        analysis = PropertyAnalysis(
            objective="spider fluid",
            target_properties=[TargetProperty(name="elasticity")],
        )
        hypotheses = generate_hypotheses(engine, "fake-model", analysis, k=3)
        assert len(hypotheses) == 2
        assert hypotheses[0].mechanism == "polymer entanglement"

    def test_truncates_to_k(self):
        content = (
            '{"hypotheses": ['
            + ", ".join(f'{{"id": "H{i}", "mechanism": "m{i}"}}' for i in range(5))
            + "]}"
        )
        engine = FakeEngine([{"content": content}])
        analysis = PropertyAnalysis(objective="x", target_properties=[])
        hypotheses = generate_hypotheses(engine, "fake-model", analysis, k=2)
        assert len(hypotheses) == 2

    def test_assigns_missing_ids(self):
        engine = FakeEngine(
            [{"content": '{"hypotheses": [{"mechanism": "m1"}, {"mechanism": "m2"}]}'}]
        )
        analysis = PropertyAnalysis(objective="x", target_properties=[])
        hypotheses = generate_hypotheses(engine, "fake-model", analysis, k=3)
        assert hypotheses[0].id == "H1"
        assert hypotheses[1].id == "H2"

    def test_malformed_json_raises(self):
        engine = FakeEngine([{"content": "no json here"}])
        analysis = PropertyAnalysis(objective="x", target_properties=[])
        with pytest.raises(ValueError):
            generate_hypotheses(engine, "fake-model", analysis, k=3)


class TestRankHypotheses:
    def test_picks_index_from_bare_digit_line(self):
        engine = FakeEngine([{"content": "Reasoning...\n1\n"}])
        hyps = [
            Hypothesis(id="H1", mechanism="m1"),
            Hypothesis(id="H2", mechanism="m2"),
        ]
        idx, reasoning = rank_hypotheses(engine, "fake-model", hyps)
        assert idx == 1

    def test_falls_back_to_zero_on_malformed_response(self):
        engine = FakeEngine([{"content": "I cannot decide."}])
        hyps = [
            Hypothesis(id="H1", mechanism="m1"),
            Hypothesis(id="H2", mechanism="m2"),
        ]
        idx, _ = rank_hypotheses(engine, "fake-model", hyps)
        assert idx == 0

    def test_falls_back_to_zero_on_out_of_range_index(self):
        engine = FakeEngine([{"content": "99"}])
        hyps = [Hypothesis(id="H1", mechanism="m1")]
        idx, _ = rank_hypotheses(engine, "fake-model", hyps)
        assert idx == 0

    def test_empty_hypotheses_returns_zero_without_calling_engine(self):
        engine = FakeEngine([{"content": "should not be used"}])
        idx, reasoning = rank_hypotheses(engine, "fake-model", [])
        assert idx == 0
        assert engine.call_count == 0
