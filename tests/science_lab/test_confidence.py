"""Tests for confidence scoring and bar rendering."""

from __future__ import annotations

import pytest

from openjarvis.science_lab.confidence import render_confidence_bar, score_confidence
from openjarvis.science_lab.models import (
    BASIS_CALCULATED,
    Hypothesis,
    PropertyAnalysis,
    SimulationResult,
    TargetProperty,
)


class TestScoreConfidence:
    def test_bare_minimum_gives_base_score(self):
        analysis = PropertyAnalysis(objective="x", target_properties=[])
        result = score_confidence(analysis, [], [])
        assert 0.0 <= result.value <= 1.0
        assert result.basis

    def test_more_corroborating_simulations_raise_confidence(self):
        analysis = PropertyAnalysis(
            objective="x",
            target_properties=[TargetProperty(name="a"), TargetProperty(name="b")],
        )
        sims_few = [
            SimulationResult(
                quantity="density", value=1.0, unit="g/cm^3", basis=BASIS_CALCULATED
            )
        ]
        sims_many = sims_few + [
            SimulationResult(
                quantity="viscosity", value=1.0, unit="cP", basis=BASIS_CALCULATED
            ),
            SimulationResult(
                quantity="concentration", value=1.0, unit="%", basis=BASIS_CALCULATED
            ),
        ]
        low = score_confidence(analysis, [], sims_few)
        high = score_confidence(analysis, [], sims_many)
        assert high.value >= low.value

    def test_never_exceeds_one(self):
        analysis = PropertyAnalysis(
            objective="x",
            target_properties=[TargetProperty(name=str(i)) for i in range(10)],
        )
        sims = [
            SimulationResult(
                quantity=f"q{i}", value=1.0, unit="", basis=BASIS_CALCULATED
            )
            for i in range(20)
        ]
        result = score_confidence(analysis, [Hypothesis(id="h1", mechanism="m")], sims)
        assert result.value <= 1.0

    def test_never_below_zero(self):
        analysis = PropertyAnalysis(objective="x", target_properties=[])
        hyps = [Hypothesis(id=f"h{i}", mechanism="m") for i in range(10)]
        result = score_confidence(analysis, hyps, [])
        assert result.value >= 0.0


class TestRenderConfidenceBar:
    def test_full(self):
        assert render_confidence_bar(1.0, width=10) == "██████████ 100%"

    def test_empty(self):
        assert render_confidence_bar(0.0, width=10) == "░░░░░░░░░░ 0%"

    def test_eighty_percent(self):
        assert render_confidence_bar(0.8, width=10) == "████████░░ 80%"

    def test_out_of_range_raises(self):
        with pytest.raises(ValueError):
            render_confidence_bar(1.5)
        with pytest.raises(ValueError):
            render_confidence_bar(-0.1)
