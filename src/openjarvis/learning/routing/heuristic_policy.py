"""Wire the existing HeuristicRouter into the RouterPolicyRegistry."""

from __future__ import annotations

from openjarvis.core.registry import RouterPolicyRegistry
from openjarvis.learning.routing.router import HeuristicRouter


def ensure_registered() -> None:
    """Register HeuristicRouter if not already present."""
    if not RouterPolicyRegistry.contains("heuristic"):
        RouterPolicyRegistry.register_value("heuristic", HeuristicRouter)


ensure_registered()
