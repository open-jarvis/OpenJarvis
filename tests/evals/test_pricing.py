"""Tests for eval pricing module."""

from __future__ import annotations

import pytest

from friday_ai.evals.core.pricing import PRICING, compute_turn_cost, estimate_cost


class TestPricing:
    def test_pricing_dict_nonempty(self):
        assert isinstance(PRICING, dict)
        assert len(PRICING) > 0

    def test_compute_turn_cost_known_model(self):
        # Pick a model that's in PRICING (cloud models)
        if not PRICING:
            pytest.skip("No models in PRICING dict")
        model = next(iter(PRICING))
        cost = compute_turn_cost(model, 1000, 500)
        assert isinstance(cost, (int, float))
        assert cost >= 0

    def test_compute_turn_cost_unknown_model(self):
        cost = compute_turn_cost("totally-unknown-local-model", 1000, 500)
        assert cost == 0.0

    def test_compute_turn_cost_zero_tokens(self):
        if not PRICING:
            pytest.skip("No models in PRICING dict")
        model = next(iter(PRICING))
        cost = compute_turn_cost(model, 0, 0)
        assert cost == 0.0

    def test_estimate_cost_alias(self):
        # estimate_cost is the same as engine/cloud.py estimate_cost
        cost = estimate_cost("unknown-model", 100, 50)
        assert cost == 0.0
