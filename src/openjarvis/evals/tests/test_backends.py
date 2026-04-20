"""Tests for backend construction with mocks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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

    @patch("openjarvis.system.SystemBuilder")
    def test_output_dir_isolates_sqlite_dbs(self, mock_builder_cls, tmp_path):
        """When output_dir is set, traces.db and agents.db must live inside
        it instead of the global ~/.openjarvis location. This is what stops
        parallel eval processes from corrupting each other's DBs."""
        from openjarvis.core.config import JarvisConfig

        config = JarvisConfig()
        original_traces_db = config.traces.db_path
        original_agents_db = config.agent_manager.db_path

        mock_builder = MagicMock()
        mock_builder._config = config
        mock_builder.engine.return_value = mock_builder
        mock_builder.agent.return_value = mock_builder
        mock_builder.tools.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()
        mock_builder_cls.return_value = mock_builder

        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        out = tmp_path / "qwen-9b" / "gaia"
        JarvisAgentBackend(agent_name="orchestrator", output_dir=out)

        assert config.traces.db_path == str(out / "traces.db")
        assert config.agent_manager.db_path == str(out / "agents.db")
        assert out.exists()
        assert config.traces.db_path != original_traces_db
        assert config.agent_manager.db_path != original_agents_db

    @patch("openjarvis.system.SystemBuilder")
    def test_no_output_dir_keeps_global_db_paths(self, mock_builder_cls):
        """Production callers (no output_dir) must keep ~/.openjarvis paths."""
        from openjarvis.core.config import JarvisConfig

        config = JarvisConfig()
        original_traces_db = config.traces.db_path
        original_agents_db = config.agent_manager.db_path

        mock_builder = MagicMock()
        mock_builder._config = config
        mock_builder.engine.return_value = mock_builder
        mock_builder.agent.return_value = mock_builder
        mock_builder.tools.return_value = mock_builder
        mock_builder.telemetry.return_value = mock_builder
        mock_builder.traces.return_value = mock_builder
        mock_builder.build.return_value = MagicMock()
        mock_builder_cls.return_value = mock_builder

        from openjarvis.evals.backends.jarvis_agent import JarvisAgentBackend

        JarvisAgentBackend(agent_name="orchestrator")

        assert config.traces.db_path == original_traces_db
        assert config.agent_manager.db_path == original_agents_db
