"""Re-register agents cleared by the root autouse _clean_registries fixture."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _register_native_openhands() -> None:
    from openjarvis.agents.native_openhands import NativeOpenHandsAgent
    from openjarvis.core.registry import AgentRegistry

    if not AgentRegistry.contains("native_openhands"):
        AgentRegistry.register("native_openhands")(NativeOpenHandsAgent)
