"""Tests for the property analyzer LLM step."""

from __future__ import annotations

import pytest

from openjarvis.science_lab.property_analyzer import analyze_objective
from tests.agents.fake_engine import FakeEngine


class TestAnalyzeObjective:
    def test_parses_clean_json(self):
        engine = FakeEngine(
            [
                {
                    "content": (
                        '{"objective": "spider-web-like fluid", '
                        '"target_properties": [{"name": "elasticity", '
                        '"target_value": "high", "unit": "", '
                        '"rationale": "web-like"}], '
                        '"constraints": []}'
                    )
                }
            ]
        )
        result = analyze_objective(engine, "fake-model", "quero um fluido tipo teia")
        assert result.objective == "spider-web-like fluid"
        assert len(result.target_properties) == 1
        assert result.target_properties[0].name == "elasticity"

    def test_recovers_json_wrapped_in_prose(self):
        engine = FakeEngine(
            [
                {
                    "content": (
                        "Sure, here you go:\n"
                        '{"objective": "x", "target_properties": []}\n'
                        "Hope that helps!"
                    )
                }
            ]
        )
        result = analyze_objective(engine, "fake-model", "x")
        assert result.objective == "x"

    def test_malformed_json_raises(self):
        engine = FakeEngine([{"content": "not json at all, no braces"}])
        with pytest.raises(ValueError):
            analyze_objective(engine, "fake-model", "x")

    def test_missing_objective_falls_back_to_description(self):
        engine = FakeEngine([{"content": '{"target_properties": []}'}])
        result = analyze_objective(engine, "fake-model", "original description")
        assert result.objective == "original description"
