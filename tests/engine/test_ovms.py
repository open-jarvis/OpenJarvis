"""Tests for the OVMS (OpenVINO Model Server) engine backend.

Validates that the ``/v1`` prefix is used correctly for models listing
and chat completions.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.openai_compat_engines import OVMSEngine


@pytest.fixture()
def engine() -> OVMSEngine:
    EngineRegistry.register_value("ovms", OVMSEngine)
    return OVMSEngine(host="http://testhost:8001")


class TestOVMSEngineBasics:
    def test_engine_id(self) -> None:
        assert OVMSEngine.engine_id == "ovms"

    def test_default_host(self) -> None:
        assert OVMSEngine._default_host == "http://localhost:8001"

    def test_api_prefix(self) -> None:
        assert OVMSEngine._api_prefix == "/v1"

    def test_registry_registration(self) -> None:
        EngineRegistry.register_value("ovms", OVMSEngine)
        assert EngineRegistry.get("ovms") is OVMSEngine

    def test_env_var_overrides_default_host(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OVMS_HOST", "http://env-ovms:9001")
        engine = OVMSEngine()
        try:
            assert engine._host == "http://env-ovms:9001"
        finally:
            engine.close()


class TestOVMSGenerate:
    def test_generate_uses_v1_prefix(self, engine: OVMSEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:8001/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {"content": "Hello!"},
                                "finish_reason": "stop",
                            }
                        ],
                        "usage": {
                            "prompt_tokens": 5,
                            "completion_tokens": 2,
                            "total_tokens": 7,
                        },
                        "model": "qwen25-7b-int4-ov",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")], model="qwen25-7b-int4-ov"
            )
        assert result["content"] == "Hello!"
        assert result["usage"]["total_tokens"] == 7

    def test_generate_connection_error(self, engine: OVMSEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:8001/v1/chat/completions").mock(
                side_effect=httpx.ConnectError("refused")
            )
            with pytest.raises(EngineConnectionError):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")],
                    model="qwen25-7b-int4-ov",
                )


class TestOVMSHealth:
    def test_health_true(self, engine: OVMSEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8001/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            assert engine.health() is True

    def test_health_false(self, engine: OVMSEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8001/v1/models").mock(
                side_effect=httpx.ConnectError("refused")
            )
            assert engine.health() is False


class TestOVMSListModels:
    def test_list_models_uses_v1_prefix(self, engine: OVMSEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8001/v1/models").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "data": [
                            {"id": "qwen25-7b-int4-ov"},
                            {"id": "Qwen3.6-35B-A3B-int4-ov"},
                        ]
                    },
                )
            )
            models = engine.list_models()
        assert "qwen25-7b-int4-ov" in models
        assert "Qwen3.6-35B-A3B-int4-ov" in models

    def test_list_models_empty(self, engine: OVMSEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8001/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            models = engine.list_models()
        assert models == []

    def test_list_models_connection_error(self, engine: OVMSEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:8001/v1/models").mock(
                side_effect=httpx.ConnectError("refused")
            )
            models = engine.list_models()
        assert models == []
