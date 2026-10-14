"""Tests for the Foundry Local engine backend."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import EngineConnectionError
from openjarvis.engine.foundry_local import (
    FOUNDRY_LOCAL_FALLBACK_HOST,
    FoundryLocalEngine,
    check_tool_calling,
    classify_execution_provider,
    discover_foundry_host,
    probe_execution_provider,
)


@pytest.fixture()
def engine() -> FoundryLocalEngine:
    EngineRegistry.register_value("foundry_local", FoundryLocalEngine)
    return FoundryLocalEngine(host="http://testhost:5273")


class TestFoundryLocalEngineBasics:
    def test_engine_id(self) -> None:
        assert FoundryLocalEngine.engine_id == "foundry_local"

    def test_api_prefix(self) -> None:
        assert FoundryLocalEngine._api_prefix == "/v1"

    def test_fallback_host(self) -> None:
        assert FOUNDRY_LOCAL_FALLBACK_HOST == "http://localhost:5273"

    def test_registry_registration(self) -> None:
        EngineRegistry.register_value("foundry_local", FoundryLocalEngine)
        assert EngineRegistry.get("foundry_local") is FoundryLocalEngine

    def test_env_var_overrides_default_host(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("FOUNDRY_LOCAL_HOST", "http://env-foundry:59959/v1")
        monkeypatch.delenv("FOUNDRY_LOCAL_ENDPOINT", raising=False)
        host = discover_foundry_host()
        assert host == "http://env-foundry:59959"

    def test_fallback_when_cli_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("FOUNDRY_LOCAL_HOST", raising=False)
        monkeypatch.delenv("FOUNDRY_LOCAL_ENDPOINT", raising=False)
        monkeypatch.setattr(
            "openjarvis.engine.foundry_local.shutil.which", lambda _: None
        )
        assert discover_foundry_host() == FOUNDRY_LOCAL_FALLBACK_HOST


class TestDiscoverFoundryHost:
    def test_parses_status_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FOUNDRY_LOCAL_HOST", raising=False)
        monkeypatch.delenv("FOUNDRY_LOCAL_ENDPOINT", raising=False)

        class _Result:
            stdout = "Service is running on http://127.0.0.1:59959/openai/status\n"
            stderr = ""

        monkeypatch.setattr(
            "openjarvis.engine.foundry_local.shutil.which", lambda _: "/usr/bin/foundry"
        )
        monkeypatch.setattr(
            "openjarvis.engine.foundry_local.subprocess.run",
            lambda *args, **kwargs: _Result(),
        )
        assert discover_foundry_host() == "http://127.0.0.1:59959"

    def test_parses_json_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FOUNDRY_LOCAL_HOST", raising=False)
        monkeypatch.delenv("FOUNDRY_LOCAL_ENDPOINT", raising=False)

        class _Result:
            stdout = '{"endpoint": "http://127.0.0.1:61234/v1"}'
            stderr = ""

        monkeypatch.setattr(
            "openjarvis.engine.foundry_local.shutil.which", lambda _: "/usr/bin/foundry"
        )
        monkeypatch.setattr(
            "openjarvis.engine.foundry_local.subprocess.run",
            lambda *args, **kwargs: _Result(),
        )
        assert discover_foundry_host() == "http://127.0.0.1:61234"

    def test_prefers_server_status_over_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("FOUNDRY_LOCAL_HOST", raising=False)
        monkeypatch.delenv("FOUNDRY_LOCAL_ENDPOINT", raising=False)
        calls: list[list[str]] = []

        class _Result:
            def __init__(self, stdout: str = "") -> None:
                self.stdout = stdout
                self.stderr = ""

        def _run(args: list[str], **kwargs: object) -> _Result:
            calls.append(list(args))
            if args[1:3] == ["server", "status"]:
                return _Result("http://127.0.0.1:59959/v1")
            return _Result()

        monkeypatch.setattr(
            "openjarvis.engine.foundry_local.shutil.which", lambda _: "/usr/bin/foundry"
        )
        monkeypatch.setattr("openjarvis.engine.foundry_local.subprocess.run", _run)
        assert discover_foundry_host() == "http://127.0.0.1:59959"
        assert calls[0][1:3] == ["server", "status"]
        assert not any(call[1:3] == ["service", "status"] for call in calls)


class TestExecutionProvider:
    def test_cuda_is_not_fallback(self) -> None:
        name, fallback = classify_execution_provider("CUDAExecutionProvider")
        assert "CUDA" in name
        assert fallback is False

    def test_tensorrt_is_not_fallback(self) -> None:
        _, fallback = classify_execution_provider("NvTensorRTRTXExecutionProvider")
        assert fallback is False

    def test_cpu_is_fallback(self) -> None:
        name, fallback = classify_execution_provider("CPUExecutionProvider")
        assert "CPU" in name
        assert fallback is True

    def test_probe_reads_status_json(self) -> None:
        with respx.mock:
            respx.get("http://testhost:5273/openai/status").mock(
                return_value=httpx.Response(
                    200,
                    json={"executionProvider": "CUDAExecutionProvider"},
                )
            )
            info = probe_execution_provider("http://testhost:5273")
        assert info["execution_provider"] == "CUDAExecutionProvider"
        assert info["cpu_fallback"] is False


class TestFoundryGenerate:
    def test_generate_uses_v1_prefix(self, engine: FoundryLocalEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:5273/v1/chat/completions").mock(
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
                        "model": "Phi-4-mini-instruct",
                    },
                )
            )
            result = engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model="Phi-4-mini-instruct",
            )
        assert result["content"] == "Hello!"

    def test_tools_400_does_not_retry(self, engine: FoundryLocalEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:5273/v1/chat/completions").mock(
                return_value=httpx.Response(400, text="tools not supported")
            )
            with pytest.raises(EngineConnectionError, match="rejected tool calling"):
                engine.generate(
                    [Message(role=Role.USER, content="Hi")],
                    model="Phi-4-mini-instruct",
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "ping",
                                "parameters": {"type": "object", "properties": {}},
                            },
                        }
                    ],
                )


class TestToolCallingProbe:
    def test_supported_when_tool_calls_returned(
        self, engine: FoundryLocalEngine
    ) -> None:
        with respx.mock:
            respx.post("http://testhost:5273/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": "",
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "function": {
                                                "name": "ping",
                                                "arguments": "{}",
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                )
            )
            result = check_tool_calling(engine, "Phi-4-mini-instruct")
        assert result["supported"] is True

    def test_probe_forces_tool_choice_required_not_auto(
        self, engine: FoundryLocalEngine
    ) -> None:
        """ "auto" lets a model decline a contrived no-op probe tool and
        read as incapable, even when it can emit tool_calls just fine (seen
        live with Phi-4-mini-instruct, which answered a real tool-shaped
        question wrong rather than calling a real calculator tool under
        "auto"). "required" tests capability, not default judgment."""
        with respx.mock:
            route = respx.post("http://testhost:5273/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200, json={"choices": [{"message": {"tool_calls": []}}]}
                )
            )
            check_tool_calling(engine, "Phi-4-mini-instruct")
        sent = json.loads(route.calls.last.request.content)
        assert sent["tool_choice"] == "required"

    def test_unsupported_on_http_400(self, engine: FoundryLocalEngine) -> None:
        with respx.mock:
            respx.post("http://testhost:5273/v1/chat/completions").mock(
                return_value=httpx.Response(400, text="no tools")
            )
            result = check_tool_calling(engine, "Phi-4-mini-instruct")
        assert result["supported"] is False
        assert "HTTP 400" in result["reason"]

    def test_probe_requests_enough_budget_for_reasoning_models(
        self, engine: FoundryLocalEngine
    ) -> None:
        """Reasoning models (Qwen3, DeepSeek-R1) spend tokens on
        reasoning_content before emitting tool_calls. A too-small max_tokens
        truncates them first and misreports tool calling as unsupported."""
        with respx.mock:
            route = respx.post("http://testhost:5273/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200, json={"choices": [{"message": {"tool_calls": []}}]}
                )
            )
            check_tool_calling(engine, "qwen3-0.6b-generic-cpu")
        assert route.calls.last.request.read()
        sent = json.loads(route.calls.last.request.content)
        assert sent["max_tokens"] >= 512

    def test_unsupported_reason_distinguishes_truncation(
        self, engine: FoundryLocalEngine
    ) -> None:
        with respx.mock:
            respx.post("http://testhost:5273/v1/chat/completions").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "finish_reason": "length",
                                "message": {"content": "", "reasoning_content": "…"},
                            }
                        ]
                    },
                )
            )
            result = check_tool_calling(engine, "qwen3-0.6b-generic-cpu")
        assert result["supported"] is False
        assert "truncated" in result["reason"]


class TestFoundryHealth:
    def test_health_true(self, engine: FoundryLocalEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:5273/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            assert engine.health() is True

    def test_list_models(self, engine: FoundryLocalEngine) -> None:
        with respx.mock:
            respx.get("http://testhost:5273/v1/models").mock(
                return_value=httpx.Response(
                    200,
                    json={"data": [{"id": "Phi-4-mini-instruct"}]},
                )
            )
            assert engine.list_models() == ["Phi-4-mini-instruct"]
