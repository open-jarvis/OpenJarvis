"""Verify JarvisAgentBackend.generate_full returns the spec §6.2 extended fields."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestJarvisAgentExtendedFields:
    def test_generate_full_includes_framework_and_commit(self) -> None:
        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        with patch("openjarvis.system.SystemBuilder") as MockSB:
            mock_system = MagicMock()
            mock_system.ask.return_value = {
                "content": "answer",
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "model": "qwen-9b",
            }
            mock_system.trace_collector = None

            builder_instance = MockSB.return_value
            builder_instance.engine.return_value = builder_instance
            builder_instance.model.return_value = builder_instance
            builder_instance.agent.return_value = builder_instance
            builder_instance.tools.return_value = builder_instance
            builder_instance.telemetry.return_value = builder_instance
            builder_instance.traces.return_value = builder_instance
            builder_instance.build.return_value = mock_system
            # The backend mutates ``builder._config`` directly; provide a
            # MagicMock that tolerates arbitrary attribute access.
            builder_instance._config = MagicMock()

            backend = JarvisAgentBackend(model="qwen-9b")
            result = backend.generate_full(
                "task",
                model="qwen-9b",
                system="",
                temperature=0.0,
                max_tokens=2048,
            )
            assert result["framework"] == "openjarvis"
            assert "framework_commit" in result
            assert "energy_joules" in result  # may be None
            assert "peak_power_w" in result
            assert "tool_calls" in result
            assert "turn_count" in result
            assert "error" in result
