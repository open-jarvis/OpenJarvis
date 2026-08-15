"""Regression: ``jarvis serve`` must wire the ``SystemPromptBuilder`` into the
agent it constructs, so SOUL.md / MEMORY.md / USER.md reach the model over HTTP.

``cli/ask.py`` (and ``cli/chat_cmd.py`` and the managed-agent executor) have
wired the builder since the persona system landed. The serve path never did, so
an agent served over HTTP silently answered as a generic assistant — explicitly
denying the persona — while the same agent via the CLI kept it. Found deploying
a personal assistant: SOUL.md was correct on disk the whole time; no error, no
warning.

This test boots ``serve`` just far enough to capture the agent handed to
``create_app`` and asserts the builder (and thus the persona content) is
present. It fails on the unpatched serve path: ``agent._prompt_builder`` is
``None``, so the persona files never reach the model.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from openjarvis.cli import cli

pytest.importorskip("fastapi")
pytest.importorskip("uvicorn")

# ``openjarvis.cli.serve`` as a package attribute resolves to the click
# *command* (re-exported); grab the real module to monkeypatch its globals.
serve_mod = importlib.import_module("openjarvis.cli.serve")


def _fake_engine() -> MagicMock:
    engine = MagicMock()
    engine.list_models.return_value = ["test-model"]
    engine.health.return_value = True
    engine.name = "mock"
    engine.engine_id = "mock"
    return engine


@pytest.mark.parametrize(
    "agent_name",
    ["simple", "orchestrator", "monitor_operative", "operative"],
)
def test_serve_wires_persona_builder_into_served_agent(
    tmp_path, monkeypatch, agent_name
):
    """The agent built on the serve path must carry a SystemPromptBuilder whose
    assembled prompt includes SOUL.md content (regression for the HTTP persona
    loss)."""
    from openjarvis.agents.monitor_operative import MonitorOperativeAgent
    from openjarvis.agents.operative import OperativeAgent
    from openjarvis.agents.orchestrator import OrchestratorAgent
    from openjarvis.agents.simple import SimpleAgent
    from openjarvis.core.config import JarvisConfig
    from openjarvis.core.registry import AgentRegistry

    # Persona file with a unique sentinel we can grep for in the built prompt.
    soul = tmp_path / "SOUL.md"
    soul.write_text("SERVE_PERSONA_SENTINEL", encoding="utf-8")

    # conftest clears registries per-test; re-register the agent we exercise.
    agent_classes = {
        "simple": SimpleAgent,
        "orchestrator": OrchestratorAgent,
        "monitor_operative": MonitorOperativeAgent,
        "operative": OperativeAgent,
    }
    if not AgentRegistry.contains(agent_name):
        AgentRegistry.register_value(agent_name, agent_classes[agent_name])

    config = JarvisConfig()
    config.server.host = "127.0.0.1"
    config.server.port = 8123
    config.intelligence.default_model = "test-model"
    config.memory_files.soul_path = str(soul)
    # Keep the heavy optional subsystems off so we reach create_app cleanly.
    config.telemetry.enabled = False
    config.agent_manager.enabled = False
    config.sessions.enabled = False
    config.channel.enabled = False
    config.skills.enabled = False
    config.agent.context_from_memory = False

    engine = _fake_engine()
    monkeypatch.setattr(serve_mod, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(serve_mod, "get_engine", lambda *a, **k: ("mock", engine))
    monkeypatch.setattr(serve_mod, "discover_engines", lambda *a, **k: {})
    monkeypatch.setattr(serve_mod, "discover_models", lambda *a, **k: {})

    # setup_security returns its own context; pass the engine straight through.
    sec = MagicMock()
    sec.engine = engine
    sec.capability_policy = None
    sec.audit_logger = None
    monkeypatch.setattr("openjarvis.security.setup_security", lambda *a, **k: sec)

    captured: dict = {}

    def _capture_create_app(*args, **kwargs):
        captured["agent"] = kwargs.get("agent")
        return MagicMock(name="app")

    with (
        patch("openjarvis.server.app.create_app", side_effect=_capture_create_app),
        patch("uvicorn.run", lambda *a, **k: None),
    ):
        result = CliRunner().invoke(
            cli, ["serve", "--agent", agent_name], catch_exceptions=False
        )

    assert result.exit_code == 0, result.output
    agent = captured.get("agent")
    assert agent is not None, (
        "serve did not construct an agent or never reached create_app; "
        f"output:\n{result.output}"
    )
    # The regression: without the fix ``agent._prompt_builder`` is None and the
    # persona files never reach the model over HTTP.
    assert agent._prompt_builder is not None, (
        f"serve constructed {agent_name} without a prompt_builder — SOUL.md / "
        "MEMORY.md / USER.md would be silently dropped on the HTTP path."
    )
    assert "SERVE_PERSONA_SENTINEL" in agent._prompt_builder.build(), (
        "prompt_builder is wired on serve, but its built prompt omits SOUL.md"
    )
