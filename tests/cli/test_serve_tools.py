"""Regression tests for tool selection during ``jarvis serve`` startup."""

from __future__ import annotations

import pytest

from openjarvis.cli.serve import _resolve_allowed_tools, _resolve_server_cors_origins
from openjarvis.core.config import JarvisConfig


@pytest.mark.parametrize(
    "configured",
    [
        "code_interpreter,file_read",
        ["code_interpreter", "file_read"],
    ],
)
def test_tools_enabled_is_used_by_serve(configured):
    config = JarvisConfig()
    config.tools.enabled = configured

    allowed, explicit = _resolve_allowed_tools(config)

    assert allowed == {"code_interpreter", "file_read"}
    assert explicit is True


def test_tools_enabled_takes_precedence_over_legacy_agent_tools():
    config = JarvisConfig()
    config.tools.enabled = "file_read"
    config.agent.tools = "calculator"

    allowed, explicit = _resolve_allowed_tools(config)

    assert allowed == {"file_read"}
    assert explicit is True


def test_agent_tools_remains_a_backward_compatible_fallback():
    config = JarvisConfig()
    config.agent.tools = "file_read"

    allowed, explicit = _resolve_allowed_tools(config)

    assert allowed == {"file_read"}
    assert explicit is True


def test_serve_defaults_tools_when_no_selection_is_configured():
    allowed, explicit = _resolve_allowed_tools(JarvisConfig())

    assert allowed == {"think", "calculator", "web_search"}
    assert explicit is False


def test_cors_environment_overrides_configured_defaults(monkeypatch):
    monkeypatch.setenv(
        "OPENJARVIS_CORS_ORIGINS",
        " https://frontend.example, https://admin.example ",
    )

    origins = _resolve_server_cors_origins(["http://localhost:5173"])

    assert origins == ["https://frontend.example", "https://admin.example"]


def test_cors_config_is_used_without_environment(monkeypatch):
    monkeypatch.delenv("OPENJARVIS_CORS_ORIGINS", raising=False)

    origins = _resolve_server_cors_origins(["http://localhost:5173"])

    assert origins == ["http://localhost:5173"]


def _repopulate_cli_registries() -> None:
    """Re-run module registration cleared between tests by conftest."""
    import importlib
    import sys

    import openjarvis.agents  # noqa: F401
    import openjarvis.tools  # noqa: F401
    import openjarvis.tools.storage  # noqa: F401
    from openjarvis.core.registry import AgentRegistry, MemoryRegistry, ToolRegistry

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


def test_build_serve_tools_wires_memory_llm_and_channel_deps():
    from unittest.mock import MagicMock

    from openjarvis.cli.serve import _build_serve_tools
    from openjarvis.tools.storage._stubs import MemoryBackend, RetrievalResult

    class _InMemoryBackend(MemoryBackend):
        backend_id = "in-memory-test"

        def __init__(self) -> None:
            self._docs: dict[str, str] = {}

        def store(self, content: str, *, source: str = "", metadata=None) -> str:
            doc_id = f"doc-{len(self._docs) + 1}"
            self._docs[doc_id] = content
            return doc_id

        def retrieve(self, query: str, *, top_k: int = 5, **kwargs):
            return [
                RetrievalResult(content=text, score=1.0, source=doc_id)
                for doc_id, text in self._docs.items()
                if query.lower() in text.lower()
            ][:top_k]

        def delete(self, doc_id: str) -> bool:
            return self._docs.pop(doc_id, None) is not None

        def clear(self) -> None:
            self._docs.clear()

    _repopulate_cli_registries()

    config = JarvisConfig()
    config.agent.tools = (
        "memory_store,memory_retrieve,memory_search,memory_index,"
        "retrieval,llm,channel_send"
    )
    engine = MagicMock(name="engine")
    channel = MagicMock(name="channel")
    backend = _InMemoryBackend()

    tools = _build_serve_tools(
        config,
        engine=engine,
        model_name="test-model",
        memory_backend=backend,
        channel_backend=channel,
    )
    by_name = {t.spec.name: t for t in tools}

    for name in (
        "memory_store",
        "memory_retrieve",
        "memory_search",
        "memory_index",
        "retrieval",
    ):
        assert by_name[name]._backend is backend

    assert by_name["llm"]._engine is engine
    assert by_name["llm"]._model == "test-model"
    assert by_name["channel_send"]._channel is channel

    stored = by_name["memory_store"].execute(content="remember my car is a blue Beetle")
    assert stored.success, stored.content

    found = by_name["memory_search"].execute(query="blue Beetle")
    assert found.success, found.content
    assert "blue Beetle" in found.content

    retrieved = by_name["retrieval"].execute(query="blue Beetle")
    assert retrieved.success, retrieved.content
    assert "blue Beetle" in retrieved.content


def test_serve_injects_memory_and_channel_backends_into_resolved_tools(
    tmp_path, monkeypatch
):
    import importlib
    from unittest.mock import MagicMock, patch

    from click.testing import CliRunner

    pytest.importorskip("fastapi")
    pytest.importorskip("uvicorn")

    from openjarvis.cli import cli
    from openjarvis.core.registry import MemoryRegistry
    from openjarvis.system import JarvisSystem

    serve_mod = importlib.import_module("openjarvis.cli.serve")
    _repopulate_cli_registries()

    config = JarvisConfig()
    config.agent.tools = "memory_store,memory_search,retrieval,channel_send"
    config.server.agent = "orchestrator"
    config.agent_manager.enabled = True
    config.agent_manager.db_path = str(tmp_path / "agents.db")
    config.sessions.enabled = True
    config.sessions.db_path = str(tmp_path / "sessions.db")
    config.memory.db_path = str(tmp_path / "memory.db")
    config.telemetry.enabled = False
    config.traces.enabled = False
    config.skills.enabled = False
    config.channel.enabled = True
    config.channel.default_channel = "test-channel"
    config.channel.default_agent = "orchestrator"
    config.intelligence.default_model = "test-model"

    engine = MagicMock()
    engine.list_models.return_value = ["test-model"]
    engine.health.return_value = True
    engine.name = "mock"

    memory_backend = MagicMock(name="memory_backend")
    channel_backend = MagicMock(channel_id="test-channel")
    monkeypatch.setattr(MemoryRegistry, "contains", MagicMock(return_value=True))
    monkeypatch.setattr(
        MemoryRegistry, "create", MagicMock(return_value=memory_backend)
    )
    monkeypatch.setattr(serve_mod, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(serve_mod, "inject_credentials", lambda: None)
    monkeypatch.setattr(serve_mod, "get_engine", lambda *a, **k: ("mock", engine))
    monkeypatch.setattr(serve_mod, "discover_engines", lambda *a, **k: {})
    monkeypatch.setattr(serve_mod, "discover_models", lambda *a, **k: {})
    monkeypatch.setattr(
        "openjarvis.system.builder.SystemBuilder._resolve_channel",
        lambda *args, **kwargs: channel_backend,
    )

    sec = MagicMock()
    sec.engine = engine
    sec.capability_policy = None
    sec.rate_limiter = None
    sec.audit_logger = None
    monkeypatch.setattr("openjarvis.security.setup_security", lambda *a, **k: sec)

    captured: dict = {}

    def _capture_wire(self, channel):
        captured["channel_system"] = self

    monkeypatch.setattr(JarvisSystem, "wire_channel", _capture_wire)
    create_app = MagicMock(return_value=MagicMock())

    with (
        patch("openjarvis.server.app.create_app", create_app),
        patch("openjarvis.server.daemon.run_server", lambda *a, **k: None),
    ):
        result = CliRunner().invoke(cli, ["serve"], catch_exceptions=False)

    assert result.exit_code == 0, result.output

    served_agent = create_app.call_args.kwargs["agent"]
    assert served_agent is not None
    served_tools = {t.spec.name: t for t in served_agent._tools}
    for name in ("memory_store", "memory_search", "retrieval"):
        assert served_tools[name]._backend is memory_backend
    assert served_tools["channel_send"]._channel is channel_backend

    channel_system = captured["channel_system"]
    assert channel_system.memory_backend is memory_backend
    channel_tools = {t.spec.name: t for t in channel_system.tools}
    for name in ("memory_store", "memory_search", "retrieval"):
        assert channel_tools[name]._backend is memory_backend
    assert channel_tools["channel_send"]._channel is channel_backend
