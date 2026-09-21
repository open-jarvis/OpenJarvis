"""Regression tests for agent registry population.

These guard against a real bug found in production debugging: the root
_clean_registries autouse fixture clears AgentRegistry before every
test, but Python only executes openjarvis.agents.__init__ (and its
@AgentRegistry.register() decorators) once per process, since module
imports are cached. Later tests that need an agent registered must
explicitly re-register it -- see the same pattern in
tests/agents/conftest.py (monitor_operative) and
tests/skills/conftest.py (native_openhands).
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reregister_core_agents() -> None:
    """Re-register the agents these tests depend on after the autouse clear."""
    from openjarvis.agents.native_openhands import NativeOpenHandsAgent
    from openjarvis.agents.native_react import NativeReActAgent
    from openjarvis.agents.simple import SimpleAgent
    from openjarvis.core.registry import AgentRegistry

    for key, cls in (
        ("native_openhands", NativeOpenHandsAgent),
        ("native_react", NativeReActAgent),
        ("simple", SimpleAgent),
    ):
        if not AgentRegistry.contains(key):
            AgentRegistry.register(key)(cls)


class TestDefaultAgentRegistration:
    """The configured default agent must actually be registered.

    This is the exact assertion that would have caught the
    'Unknown agent: native_openhands' bug immediately instead of it
    surfacing as a confusing runtime error deep in system.ask().
    """

    def test_default_agent_is_registered(self):
        from openjarvis.core.config import load_config
        from openjarvis.core.registry import AgentRegistry

        config = load_config()
        default_agent = config.agent.default_agent

        assert default_agent, "config.agent.default_agent must not be empty"
        assert AgentRegistry.contains(default_agent), (
            f"config.agent.default_agent is '{default_agent}' but no such "
            f"agent is registered. Registered agents: "
            f"{sorted(AgentRegistry.keys())}"
        )

    def test_doctor_agent_check_reports_no_failures(self):
        """jarvis doctor's agent check should never report a 'fail' status
        for a correctly configured installation."""
        from openjarvis.cli.doctor_cmd import _check_agents

        results = _check_agents()
        failures = [r for r in results if r.status == "fail"]
        assert not failures, f"doctor reported agent failures: {failures}"
