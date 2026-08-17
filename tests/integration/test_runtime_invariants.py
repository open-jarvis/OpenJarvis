"""One canonical system; agent lifecycles may differ, resources may not."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from openjarvis.core.config import load_config
from openjarvis.system import SystemBuilder
from openjarvis.system.agent_construction import construct_registered_agent

PRESET = Path("configs/openjarvis/examples/browser-agent-playwright-mcp.toml")

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def system():
    config = load_config(PRESET)
    # The preset ships training off, and there is no fluent toggle for it; the
    # invariant under test is that `build()` wires the orchestrator when the
    # config asks, not that a browser preset asks.
    config.learning.training_enabled = True
    # `tests/conftest.py::_clean_registries` empties `EngineRegistry` for every
    # test, so engine discovery finds nothing regardless of what is running on
    # this box. Inject through the public seam; no model is ever called here.
    engine = MagicMock()
    engine.health.return_value = True
    engine.list_models.return_value = [config.intelligence.default_model]
    # Same story for `MemoryRegistry`: `_clean_registries` empties it, and
    # `@MemoryRegistry.register("sqlite")` only fires the first time
    # `openjarvis.tools.storage` is imported. Whether that import already
    # happened depends on which tests ran before this module, so
    # `_resolve_memory` finds an empty registry and degrades to None — the file
    # passes alone and fails inside the suite. Put the real backend back.
    from openjarvis.core.registry import MemoryRegistry
    from openjarvis.tools.storage.sqlite import SQLiteMemory

    # Guarded: when this module runs alone the decorator did fire, and
    # re-registering the same key raises.
    if not MemoryRegistry.contains(config.memory.default_backend):
        MemoryRegistry.register_value(config.memory.default_backend, SQLiteMemory)
    built = (
        SystemBuilder(config)
        .engine_instance(engine, key="ollama")
        .scheduler(True)
        .workflow(True)
        .sessions(True)
        .operators(True)
        .build()
    )
    yield built
    built.close()


def test_every_abstraction_is_wired(system):
    assert system.engine is not None and system.model
    assert system.scheduler is not None
    assert system.workflow_engine is not None
    assert system.operator_manager is not None
    assert system.session_store is not None
    assert system.trace_store is not None
    assert system._learning_orchestrator is not None
    assert system.skill_manager is not None


def test_memory_backend_is_wired(system):
    from openjarvis._rust_bridge import RUST_AVAILABLE

    if not RUST_AVAILABLE:
        pytest.skip(
            "openjarvis_rust is not built in this venv, so every memory backend "
            "raises MemoryBackendUnavailable and the builder degrades to None"
        )
    assert system.memory_backend is not None


def test_realtime_and_request_agents_share_resources(system):
    """Different agent objects are fine; different runtimes are not."""
    # `_clean_registries` empties `AgentRegistry` and the `@register`
    # decorators only fire on first import, so put the preset's real agent
    # class back rather than testing against a stub.
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.core.registry import AgentRegistry

    assert system.agent_name == "orchestrator"
    AgentRegistry.register_value(system.agent_name, OrchestratorAgent)

    realtime = construct_registered_agent(
        agent_name=system.agent_name,
        engine=system.engine,
        model=system.model,
        tools=system.tools,
        bus=system.bus,
    )
    per_request = construct_registered_agent(
        agent_name=system.agent_name,
        engine=system.engine,
        model=system.model,
        tools=system.tools,
        bus=system.bus,
    )

    assert realtime is not per_request
    assert realtime._engine is per_request._engine is system.engine
    assert realtime._tools == per_request._tools == system.tools
    for tool in realtime._tools:
        assert any(other is tool for other in per_request._tools)


def test_exactly_one_playwright_subprocess(system):
    """One system, one browser — counted among this process's own children.

    A global `pgrep -fc @playwright/mcp` cannot express this: any other tenant
    of the machine (an editor's MCP plugin, a second server) inflates it, and
    they all share the preset's argv. The stdio transport spawns the server as
    a direct child of whoever built the system, so that is where to count.
    """
    children = subprocess.run(
        ["pgrep", "-P", str(os.getpid())], capture_output=True, text=True
    ).stdout.split()
    playwright = [
        pid
        for pid in children
        if b"@playwright/mcp" in _cmdline(pid)
    ]
    assert len(playwright) == 1, [_cmdline(pid) for pid in children]


def _cmdline(pid: str) -> bytes:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:  # the child exited between pgrep and the read
        return b""
