"""Tests for heuristic policy registration."""

from __future__ import annotations

from openjarvis.core.registry import RouterPolicyRegistry
from openjarvis.learning.routing.heuristic_policy import ensure_registered
from openjarvis.learning.routing.router import HeuristicRouter


class TestHeuristicPolicy:
    def test_registered_as_heuristic(self) -> None:
        ensure_registered()
        assert RouterPolicyRegistry.contains("heuristic")

    def test_value_is_heuristic_router(self) -> None:
        ensure_registered()
        assert RouterPolicyRegistry.get("heuristic") is HeuristicRouter

    def test_can_instantiate(self) -> None:
        ensure_registered()
        cls = RouterPolicyRegistry.get("heuristic")
        router = cls(available_models=["model-a"])
        assert router.available_models == ["model-a"]
