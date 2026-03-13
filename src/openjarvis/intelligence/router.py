"""Backward-compat shim — canonical location is learning.router."""

from openjarvis.learning.routing.router import (  # noqa: F401
    DefaultQueryAnalyzer,
    HeuristicRouter,
    build_routing_context,
)

__all__ = ["DefaultQueryAnalyzer", "HeuristicRouter", "build_routing_context"]
