"""Verify JarvisDirectBackend.generate_full returns the spec §6.2 extended fields."""

from __future__ import annotations

from unittest.mock import MagicMock


class TestJarvisDirectExtendedFields:
    def test_generate_full_includes_framework_and_commit(self) -> None:
        from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend

        # Build the backend without invoking __init__ (which would spin up an
        # engine); set required attrs directly. JarvisDirectBackend.generate_full
        # calls ``self._system.engine.generate(messages, ...)`` so we mock the
        # whole ``_system`` chain.
        backend = JarvisDirectBackend.__new__(JarvisDirectBackend)
        backend._telemetry = False
        backend._gpu_metrics = False
        backend._system = MagicMock()
        backend._system.engine.generate.return_value = {
            "content": "answer",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
            "model": "qwen-9b",
        }

        result = backend.generate_full(
            "task",
            model="qwen-9b",
            system="",
            temperature=0.0,
            max_tokens=2048,
        )
        assert result["framework"] == "openjarvis"
        assert "framework_commit" in result
        assert result["tool_calls"] == 0  # direct = no tool calls
        assert result["turn_count"] == 1  # direct = single turn
        assert "energy_joules" in result
        assert "peak_power_w" in result
        assert "error" in result
