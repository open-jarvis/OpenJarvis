"""Standalone channel/research launchers inherit configured security."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from click.testing import CliRunner

from friday_ai.core.config import FridayConfig
from friday_ai.security import SecurityContext


def _security(raw_engine, wrapped_engine, policy, limiter):
    return MagicMock(
        return_value=SecurityContext(
            engine=wrapped_engine,
            capability_policy=policy,
            rate_limiter=limiter,
        )
    )


def test_deep_research_setup_chat_wires_security(monkeypatch):
    from friday_ai.cli.deep_research_setup_cmd import _launch_chat

    raw_engine = MagicMock(name="raw-engine")
    wrapped_engine = MagicMock(name="wrapped-engine")
    wrapped_engine.health.return_value = True
    wrapped_engine.list_models.return_value = ["qwen3.5:4b"]
    policy = object()
    limiter = object()
    setup = _security(raw_engine, wrapped_engine, policy, limiter)
    captured = {}

    class _Agent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, text):
            return SimpleNamespace(content="done")

    monkeypatch.setattr("friday_ai.core.config.load_config", lambda: FridayConfig())
    monkeypatch.setattr("friday_ai.engine.ollama.OllamaEngine", lambda: raw_engine)
    monkeypatch.setattr("friday_ai.security.setup_security", setup)
    monkeypatch.setattr("friday_ai.agents.deep_research.DeepResearchAgent", _Agent)
    console = MagicMock()
    console.input.return_value = "/quit"

    _launch_chat(MagicMock(), console)

    assert captured["engine"] is wrapped_engine
    assert captured["capability_policy"] is policy
    assert captured["rate_limiter"] is limiter
    assert captured["agent_id"] == "cli:deep-research"
    assert captured["bus"] is setup.call_args.args[2]


def test_imessage_foreground_wires_security(monkeypatch):
    from friday_ai.cli.channels_cmd import imessage_start

    raw_engine = MagicMock(name="raw-engine")
    wrapped_engine = MagicMock(name="wrapped-engine")
    policy = object()
    limiter = object()
    setup = _security(raw_engine, wrapped_engine, policy, limiter)
    captured = {}
    run_daemon = MagicMock()

    class _Agent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, text):
            return SimpleNamespace(content="done")

    monkeypatch.setattr("friday_ai.channels.imessage_daemon.is_running", lambda: False)
    monkeypatch.setattr("friday_ai.channels.imessage_daemon.run_daemon", run_daemon)
    monkeypatch.setattr("friday_ai.core.config.load_config", lambda: FridayConfig())
    monkeypatch.setattr("friday_ai.engine.ollama.OllamaEngine", lambda: raw_engine)
    monkeypatch.setattr("friday_ai.security.setup_security", setup)
    monkeypatch.setattr("friday_ai.agents.deep_research.DeepResearchAgent", _Agent)

    result = CliRunner().invoke(
        imessage_start,
        ["person@example.com", "--foreground"],
    )

    assert result.exit_code == 0
    assert captured["engine"] is wrapped_engine
    assert captured["capability_policy"] is policy
    assert captured["rate_limiter"] is limiter
    assert captured["agent_id"] == "channel:imessage"
    assert captured["bus"] is setup.call_args.args[2]
    run_daemon.assert_called_once()


def test_slack_daemon_wires_security(monkeypatch, tmp_path):
    from friday_ai.channels import slack_daemon

    handlers = {}

    class _App:
        def __init__(self, **kwargs):
            pass

        def event(self, name):
            def _decorate(function):
                handlers[name] = function
                return function

            return _decorate

    class _Handler:
        def __init__(self, app, token):
            pass

        def start(self):
            return None

        def close(self):
            return None

    bolt = types.ModuleType("slack_bolt")
    bolt.App = _App
    adapter = types.ModuleType("slack_bolt.adapter")
    socket_mode = types.ModuleType("slack_bolt.adapter.socket_mode")
    socket_mode.SocketModeHandler = _Handler
    monkeypatch.setitem(sys.modules, "slack_bolt", bolt)
    monkeypatch.setitem(sys.modules, "slack_bolt.adapter", adapter)
    monkeypatch.setitem(sys.modules, "slack_bolt.adapter.socket_mode", socket_mode)

    raw_engine = MagicMock(name="raw-engine")
    wrapped_engine = MagicMock(name="wrapped-engine")
    policy = object()
    limiter = object()
    setup = _security(raw_engine, wrapped_engine, policy, limiter)
    captured = {}

    class _Agent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, text):
            return SimpleNamespace(content="done")

    monkeypatch.setattr(slack_daemon, "_PID_FILE", str(tmp_path / "slack.pid"))
    monkeypatch.setattr(slack_daemon.signal, "signal", MagicMock())
    monkeypatch.setattr("friday_ai.core.config.load_config", lambda: FridayConfig())
    monkeypatch.setattr("friday_ai.engine.ollama.OllamaEngine", lambda: raw_engine)
    monkeypatch.setattr("friday_ai.security.setup_security", setup)
    monkeypatch.setattr("friday_ai.agents.deep_research.DeepResearchAgent", _Agent)
    monkeypatch.setattr(
        "friday_ai.server.agent_manager_routes._build_deep_research_tools",
        lambda **kwargs: [],
    )

    slack_daemon.run_slack_daemon("bot", "app", "test-model")

    assert captured["engine"] is wrapped_engine
    assert captured["capability_policy"] is policy
    assert captured["rate_limiter"] is limiter
    assert captured["agent_id"] == "channel:slack"
    assert captured["bus"] is setup.call_args.args[2]
    assert "message" in handlers
