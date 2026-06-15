"""Regression tests for #263 — ``jarvis serve`` must build the system once.

serve.py used to construct all heavy components inline and then call
``SystemBuilder(config).build()`` a second time inside the scheduler block,
re-discovering the engine, re-instrumenting it, re-resolving tools, re-opening
the channel and re-creating the agent manager — ~30-40s of redundant work.

These tests pin the fix:

1. ``SystemBuilder.build`` is never called during ``jarvis serve`` startup
   (the duplicate build is gone).
2. The ``AgentExecutor`` still receives a system exposing the attributes it
   actually reads: ``tool_executor``, ``session_store``, ``memory_backend``,
   plus ``engine`` / ``model`` / ``config``.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

# ``openjarvis.cli.serve`` as an attribute resolves to the click *command*
# (re-exported on the package); grab the real module to monkeypatch its globals.
serve_mod = importlib.import_module("openjarvis.cli.serve")


def _fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.list_models.return_value = ["test-model"]
    engine.health.return_value = True
    engine.name = "mock"
    return engine


def _repopulate_registries() -> None:
    """Re-run the @register decorators wiped by the autouse conftest fixture.

    The tool/memory modules are import-cached, so a plain ``import`` inside
    serve.py is a no-op after the registries are cleared per-test. Reload the
    individual submodules so ToolRegistry/MemoryRegistry are populated exactly
    as they would be on a fresh process — otherwise serve would resolve an
    empty tool list and no memory backend, masking the very wiring under test.
    """
    import importlib
    import sys

    import openjarvis.agents  # noqa: F401
    import openjarvis.tools  # noqa: F401
    import openjarvis.tools.storage  # noqa: F401
    from openjarvis.core.registry import (
        AgentRegistry,
        MemoryRegistry,
        ToolRegistry,
    )

    if not AgentRegistry.keys():
        for mod_name in list(sys.modules):
            if mod_name.startswith("openjarvis.agents.") and not mod_name.endswith(
                "_stubs"
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass

    if not ToolRegistry.keys():
        for mod_name in list(sys.modules):
            if (
                mod_name.startswith("openjarvis.tools.")
                and not mod_name.endswith("_stubs")
                and not mod_name.endswith("agent_tools")
            ):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass

    if not MemoryRegistry.keys():
        for mod_name in list(sys.modules):
            if mod_name.startswith(
                "openjarvis.tools.storage."
            ) and not mod_name.endswith("_stubs"):
                try:
                    importlib.reload(sys.modules[mod_name])
                except Exception:
                    pass


def _run_serve(tmp_path, monkeypatch, *, build_spy, set_system_spy):
    """Invoke ``jarvis serve`` with all heavy/blocking pieces stubbed out.

    Returns the CliRunner result. The server is never actually started
    (``uvicorn.run`` is a no-op) and no real engine is contacted.
    """
    from openjarvis.core.config import JarvisConfig

    _repopulate_registries()

    config = JarvisConfig()
    # Keep the scheduler block alive (it owns the executor wiring under test)
    # while pointing every store at the temp dir.
    config.agent_manager.enabled = True
    config.agent_manager.db_path = str(tmp_path / "agents.db")
    config.sessions.enabled = True
    config.sessions.db_path = str(tmp_path / "sessions.db")
    config.memory.db_path = str(tmp_path / "memory.db")
    config.telemetry.enabled = False
    config.traces.enabled = False
    config.channel.enabled = False
    config.skills.enabled = False
    config.server.host = "127.0.0.1"
    config.server.port = 8123
    # Resolve a model without contacting a real engine / discovery.
    config.intelligence.default_model = "test-model"

    engine = _fake_engine()

    monkeypatch.setattr(serve_mod, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(serve_mod, "get_engine", lambda *a, **k: ("mock", engine))
    monkeypatch.setattr(serve_mod, "discover_engines", lambda *a, **k: {})
    monkeypatch.setattr(serve_mod, "discover_models", lambda *a, **k: {})

    # setup_security returns its own context; pass the engine straight through
    # so we don't need real guardrails wired up.
    sec = MagicMock()
    sec.engine = engine
    sec.capability_policy = None
    sec.audit_logger = None
    monkeypatch.setattr("openjarvis.security.setup_security", lambda *a, **k: sec)

    with (
        patch(
            "openjarvis.system.builder.SystemBuilder.build",
            build_spy,
        ),
        patch(
            "openjarvis.agents.executor.AgentExecutor.set_system",
            set_system_spy,
        ),
        patch("uvicorn.run", lambda *a, **k: None),
    ):
        return CliRunner().invoke(cli, ["serve"], catch_exceptions=False)


def test_serve_does_not_call_systembuilder_build(tmp_path, monkeypatch):
    """The redundant second full build is gone (#263)."""
    build_spy = MagicMock(
        side_effect=AssertionError(
            "SystemBuilder.build() must not run during `jarvis serve` startup "
            "— it is the duplicate build #263 removed."
        )
    )
    set_system_spy = MagicMock()

    result = _run_serve(
        tmp_path,
        monkeypatch,
        build_spy=build_spy,
        set_system_spy=set_system_spy,
    )

    assert result.exit_code == 0, result.output
    build_spy.assert_not_called()


def test_executor_receives_required_system_attrs(tmp_path, monkeypatch):
    """The executor still gets a system exposing the attributes it reads.

    AgentExecutor reads engine/model/config/memory_backend/tool_executor/
    session_store off ``self._system``; the de-dup must not strip any of them.
    """
    build_spy = MagicMock()
    captured: dict = {}

    def _capture_set_system(self, system):  # noqa: ANN001
        captured["system"] = system
        # Preserve real behaviour so the executor is usable afterwards.
        self._system = system

    result = _run_serve(
        tmp_path,
        monkeypatch,
        build_spy=build_spy,
        set_system_spy=_capture_set_system,
    )

    assert result.exit_code == 0, result.output
    # Built once, from the inline components — not via SystemBuilder.build().
    build_spy.assert_not_called()

    system = captured.get("system")
    assert system is not None, "executor.set_system was never called"

    # Correctness constraint from the verifier: these must survive the de-dup.
    assert system.tool_executor is not None
    assert system.session_store is not None
    assert system.memory_backend is not None

    # And the basics the executor resolves engine/model from.
    assert system.engine is not None
    assert system.model == "test-model"
    assert system.config is not None
