"""Tests for backend construction with mocks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx


def _mock_builder() -> MagicMock:
    """A SystemBuilder mock whose fluent methods chain like the real one."""
    builder = MagicMock()
    for method in (
        "engine",
        "engine_instance",
        "model",
        "agent",
        "tools",
        "telemetry",
        "traces",
    ):
        getattr(builder, method).return_value = builder
    builder.build.return_value = MagicMock()
    return builder


class TestJarvisDirectBackend:
    @patch("openjarvis.system.SystemBuilder")
    def test_construction_default(self, mock_builder_cls):
        mock_builder = MagicMock()
        mock_builder.engine.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder
        mock_system = MagicMock()
        mock_builder.build.return_value = mock_system
        mock_builder_cls.return_value = mock_builder

        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        backend = JarvisDirectBackend()
        assert backend.backend_id == "jarvis-direct"
        mock_builder.telemetry.assert_called_with(False)
        mock_builder.traces.assert_called_with(False)
        mock_builder.build.assert_called_once()

    @patch("openjarvis.system.SystemBuilder")
    def test_construction_with_engine_key(self, mock_builder_cls):
        mock_builder = MagicMock()
        mock_builder.engine.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()
        mock_builder_cls.return_value = mock_builder

        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        JarvisDirectBackend(engine_key="cloud")
        mock_builder.engine.assert_called_with("cloud")

    @patch("openjarvis.system.SystemBuilder")
    def test_generate_full(self, mock_builder_cls):
        mock_builder = MagicMock()
        mock_builder.engine.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder
        mock_system = MagicMock()
        mock_system.engine.generate.return_value = {
            "content": "42",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            "model": "test-model",
            "cost_usd": 0.001,
        }
        mock_builder.build.return_value = mock_system
        mock_builder_cls.return_value = mock_builder

        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        backend = JarvisDirectBackend()
        result = backend.generate_full("What is 2+2?", model="test-model")

        assert result["content"] == "42"
        assert result["cost_usd"] == 0.001
        assert "latency_seconds" in result

    @patch("openjarvis.system.SystemBuilder")
    def test_generate(self, mock_builder_cls):
        mock_builder = MagicMock()
        mock_builder.engine.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder
        mock_system = MagicMock()
        mock_system.engine.generate.return_value = {
            "content": "Paris",
            "usage": {},
        }
        mock_builder.build.return_value = mock_system
        mock_builder_cls.return_value = mock_builder

        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        backend = JarvisDirectBackend()
        text = backend.generate("Capital of France?", model="m")
        assert text == "Paris"


class TestJarvisAgentBackend:
    @patch("openjarvis.system.SystemBuilder")
    def test_construction(self, mock_builder_cls):
        mock_builder = MagicMock()
        mock_builder.engine.return_value = mock_builder
        mock_builder.agent.return_value = mock_builder
        mock_builder.tools.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()
        mock_builder_cls.return_value = mock_builder

        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        backend = JarvisAgentBackend(
            engine_key="cloud",
            agent_name="orchestrator",
            tools=["calculator", "think"],
        )
        assert backend.backend_id == "jarvis-agent"
        mock_builder.engine.assert_called_with("cloud")
        mock_builder.agent.assert_called_with("orchestrator")
        mock_builder.tools.assert_called_with(["calculator", "think"])

    @patch("openjarvis.system.SystemBuilder")
    def test_generate_full(self, mock_builder_cls):
        mock_builder = MagicMock()
        mock_builder.engine.return_value = mock_builder
        mock_builder.agent.return_value = mock_builder
        mock_builder.tools.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder
        mock_system = MagicMock()
        mock_system.ask.return_value = {
            "content": "The answer is 4.",
            "usage": {"prompt_tokens": 50, "completion_tokens": 20},
            "model": "gpt-4o",
            "turns": 2,
            "tool_results": [
                {"tool_name": "calculator", "content": "4", "success": True},
            ],
        }
        mock_builder.build.return_value = mock_system
        mock_builder_cls.return_value = mock_builder

        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        backend = JarvisAgentBackend(agent_name="orchestrator")
        result = backend.generate_full("What is 2+2?", model="gpt-4o")

        assert result["content"] == "The answer is 4."
        assert result["turns"] == 2
        assert len(result["tool_results"]) == 1


class TestJarvisDirectBackendBaseUrl:
    """--base-url targeting for the jarvis-direct backend."""

    @patch("openjarvis.system.SystemBuilder")
    def test_base_url_injects_pinned_openai_compat_engine(self, mock_builder_cls):
        from openjarvis.engine.openai_compat_engines import OpenAICompatEngine
        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        mock_builder = _mock_builder()
        mock_builder_cls.return_value = mock_builder

        with respx.mock:
            respx.get("http://127.0.0.1:18999/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            JarvisDirectBackend(base_url="http://127.0.0.1:18999/v1", api_key="sk-x")

        mock_builder.engine_instance.assert_called_once()
        injected = mock_builder.engine_instance.call_args[0][0]
        assert isinstance(injected, OpenAICompatEngine)
        # Trailing /v1 is normalized away so request paths don't double up.
        assert injected._host == "http://127.0.0.1:18999"
        assert injected._api_key == "sk-x"
        # The discovery path must not be engaged at all.
        mock_builder.engine.assert_not_called()

    @patch("openjarvis.system.SystemBuilder")
    def test_unreachable_base_url_fails_fast_naming_url(self, mock_builder_cls):
        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        mock_builder = _mock_builder()
        mock_builder_cls.return_value = mock_builder

        with respx.mock:
            respx.get("http://127.0.0.1:18998/v1/models").mock(
                side_effect=httpx.ConnectError("connection refused")
            )
            with pytest.raises(RuntimeError, match=r"http://127\.0\.0\.1:18998"):
                JarvisDirectBackend(base_url="http://127.0.0.1:18998")

        # No silent engine substitution: the system is never built.
        mock_builder.engine_instance.assert_not_called()
        mock_builder.build.assert_not_called()

    @patch("openjarvis.system.SystemBuilder")
    def test_no_base_url_keeps_engine_key_path(self, mock_builder_cls):
        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        mock_builder = _mock_builder()
        mock_builder_cls.return_value = mock_builder

        JarvisDirectBackend(engine_key="vllm")
        mock_builder.engine.assert_called_with("vllm")
        mock_builder.engine_instance.assert_not_called()

    @patch("openjarvis.system.SystemBuilder")
    def test_base_url_wins_over_engine_key(self, mock_builder_cls):
        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        mock_builder = _mock_builder()
        mock_builder_cls.return_value = mock_builder

        with respx.mock:
            respx.get("http://127.0.0.1:18999/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            JarvisDirectBackend(engine_key="vllm", base_url="http://127.0.0.1:18999")

        mock_builder.engine.assert_not_called()
        mock_builder.engine_instance.assert_called_once()
        # The engine key is kept as the label for the injected engine.
        assert mock_builder.engine_instance.call_args.kwargs["key"] == "vllm"


class TestJarvisAgentBackendBaseUrl:
    """--base-url targeting for the jarvis-agent backend."""

    @patch("openjarvis.system.SystemBuilder")
    def test_base_url_injects_pinned_openai_compat_engine(self, mock_builder_cls):
        from openjarvis.engine.openai_compat_engines import OpenAICompatEngine
        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        mock_builder = _mock_builder()
        mock_builder_cls.return_value = mock_builder

        with respx.mock:
            respx.get("http://127.0.0.1:18999/v1/models").mock(
                return_value=httpx.Response(200, json={"data": []})
            )
            JarvisAgentBackend(base_url="http://127.0.0.1:18999/v1", api_key="sk-x")

        mock_builder.engine_instance.assert_called_once()
        injected = mock_builder.engine_instance.call_args[0][0]
        assert isinstance(injected, OpenAICompatEngine)
        assert injected._host == "http://127.0.0.1:18999"
        assert injected._api_key == "sk-x"
        mock_builder.engine.assert_not_called()

    @patch("openjarvis.system.SystemBuilder")
    def test_unreachable_base_url_fails_fast_naming_url(self, mock_builder_cls):
        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        mock_builder = _mock_builder()
        mock_builder_cls.return_value = mock_builder

        with respx.mock:
            respx.get("http://127.0.0.1:18998/v1/models").mock(
                side_effect=httpx.ConnectError("connection refused")
            )
            with pytest.raises(RuntimeError, match=r"http://127\.0\.0\.1:18998"):
                JarvisAgentBackend(base_url="http://127.0.0.1:18998")

        mock_builder.engine_instance.assert_not_called()
        mock_builder.build.assert_not_called()

    @patch("openjarvis.system.SystemBuilder")
    def test_no_base_url_keeps_engine_key_path(self, mock_builder_cls):
        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        mock_builder = _mock_builder()
        mock_builder_cls.return_value = mock_builder

        JarvisAgentBackend(engine_key="vllm")
        mock_builder.engine.assert_called_with("vllm")
        mock_builder.engine_instance.assert_not_called()
