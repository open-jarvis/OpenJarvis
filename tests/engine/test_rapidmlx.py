"""Rapid-MLX API, configuration, and shared-port discovery tests."""

from __future__ import annotations

import httpx
import pytest
import respx

from openjarvis.cli.init_cmd import _detect_running_engines
from openjarvis.core.config import JarvisConfig, load_config
from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine._discovery import _make_engine, discover_engines, get_engine
from openjarvis.engine.openai_compat_engines import RapidMLXEngine, VLLMEngine
from openjarvis.intelligence.model_catalog import resolve_model_id_for_engine

MODEL = "mlx-community/Qwen3.5-4B-MLX-4bit"


@pytest.fixture()
def engine():
    EngineRegistry.register_value("rapidmlx", RapidMLXEngine)
    instance = RapidMLXEngine(host="http://testhost:8000")
    yield instance
    instance.close()


def test_basics_and_env(monkeypatch):
    assert RapidMLXEngine.engine_id == "rapidmlx"
    assert RapidMLXEngine._default_host == "http://localhost:8000"
    assert RapidMLXEngine._api_prefix == "/v1"
    monkeypatch.setenv("RAPIDMLX_HOST", "http://env-rapidmlx:17777")
    instance = RapidMLXEngine()
    assert instance._host == "http://env-rapidmlx:17777"
    instance.close()


def test_config_and_registry(engine, tmp_path):
    assert EngineRegistry.get("rapidmlx") is RapidMLXEngine
    path = tmp_path / "config.toml"
    path.write_text('[engine.rapidmlx]\nhost = "http://custom:8001"\n')
    config = load_config(path)
    assert config.engine.rapidmlx_host == "http://custom:8001"
    config.engine.rapidmlx_host = "http://testhost:8000"
    instance = _make_engine("rapidmlx", config)
    assert instance._host == config.engine.rapidmlx.host
    instance.close()
    assert resolve_model_id_for_engine("qwen3.5:2b", "rapidmlx").startswith(
        "mlx-community/"
    )


def test_generate(engine):
    with respx.mock:
        respx.post("http://testhost:8000/v1/chat/completions").respond(
            200, json={"choices": [{"message": {"content": "Hello!"}}]}
        )
        assert (
            engine.generate([Message(role=Role.USER, content="Hi")], model=MODEL)[
                "content"
            ]
            == "Hello!"
        )


def test_connection_error(engine):
    with respx.mock:
        respx.post("http://testhost:8000/v1/chat/completions").mock(
            side_effect=httpx.ConnectError("refused")
        )
        with pytest.raises(EngineConnectionError):
            engine.generate([Message(role=Role.USER, content="Hi")], model=MODEL)
        respx.get("http://testhost:8000/v1/models").mock(
            side_effect=httpx.ConnectError("refused")
        )
        assert not engine.health()


@pytest.mark.parametrize("owner", ["rapid-mlx", "vllm", None])
def test_shared_port_discovery(engine, owner):
    EngineRegistry.register_value("vllm", VLLMEngine)
    config = JarvisConfig()
    config.engine.rapidmlx.host = "http://localhost:8000"
    with respx.mock(assert_all_called=False) as router:
        router.get("http://testhost:8000/v1/models").respond(
            200, json={"data": [{"id": MODEL, "owned_by": owner}]}
        )
        router.get("http://localhost:8000/v1/models").respond(
            200, json={"data": [{"id": MODEL, "owned_by": owner}]}
        )
        router.route().respond(503)
        assert engine.health() is (owner == "rapid-mlx")
        assert engine.list_models() == [MODEL]
        running = _detect_running_engines()
        assert running[0] == ("rapidmlx" if owner == "rapid-mlx" else "vllm")
        assert ("rapidmlx" in running) is (owner == "rapid-mlx")
        discovered = discover_engines(config)
        assert [key for key, _ in discovered] == (
            ["rapidmlx", "vllm"] if owner == "rapid-mlx" else ["vllm"]
        )
        assert get_engine(config)[0] == ("rapidmlx" if owner == "rapid-mlx" else "vllm")
        config.engine.default = "rapidmlx"
        assert discover_engines(config)[0][0] == (
            "rapidmlx" if owner == "rapid-mlx" else "vllm"
        )
        for _, instance in discovered:
            instance.close()


@pytest.mark.parametrize(
    ("status", "body", "healthy"),
    [
        (200, '{"data": [{"owned_by": "rapid-mlx"}]}', True),
        (200, '{"data": [null, "bad", {"owned_by": "rapid-mlx"}]}', True),
        (200, '{"data": [{"owned_by": "vllm"}]}', False),
        (200, '{"data": [{"owned_by": "uzu"}]}', False),
        (503, '{"data": [{"owned_by": "rapid-mlx"}]}', False),
        (404, '{"data": [{"owned_by": "rapid-mlx"}]}', False),
        (200, "not JSON", False),
        (200, "[]", False),
        (200, "null", False),
        (200, "{}", False),
        (200, '{"data": null}', False),
        (200, '{"data": [null, "bad", {}]}', False),
    ],
)
def test_health_and_init_probe(engine, status, body, healthy):
    with respx.mock as router:
        router.get("http://testhost:8000/v1/models").respond(status, text=body)
        router.get("http://localhost:8000/v1/models").respond(status, text=body)
        router.route().respond(503)
        assert engine.health() is healthy
        assert ("rapidmlx" in _detect_running_engines()) is healthy
