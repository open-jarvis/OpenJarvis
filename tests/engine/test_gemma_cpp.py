"""Tests for the gemma.cpp engine backend."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.config import EngineConfig, GemmaCppEngineConfig
from openjarvis.core.types import Message, Role


class TestGemmaCppEngineConfig:
    def test_default_values(self) -> None:
        cfg = GemmaCppEngineConfig()
        assert cfg.model_path == ""
        assert cfg.tokenizer_path == ""
        assert cfg.model_type == ""
        assert cfg.num_threads == 0

    def test_engine_config_has_gemma_cpp_field(self) -> None:
        ec = EngineConfig()
        assert hasattr(ec, "gemma_cpp")
        assert isinstance(ec.gemma_cpp, GemmaCppEngineConfig)


class TestMessagesToPrompt:
    def _make_engine(self):
        """Create engine with no paths (won't load model, just test formatting)."""
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        return GemmaCppEngine()

    def test_single_user_message(self) -> None:
        engine = self._make_engine()
        msgs = [Message(role=Role.USER, content="Hello")]
        result = engine._messages_to_prompt(msgs)
        assert result == (
            "<start_of_turn>user\nHello<end_of_turn>\n<start_of_turn>model\n"
        )

    def test_system_folded_into_user(self) -> None:
        engine = self._make_engine()
        msgs = [
            Message(role=Role.SYSTEM, content="You are helpful."),
            Message(role=Role.USER, content="Hello"),
        ]
        result = engine._messages_to_prompt(msgs)
        assert result == (
            "<start_of_turn>user\n"
            "You are helpful.\n\nHello<end_of_turn>\n"
            "<start_of_turn>model\n"
        )

    def test_multi_turn_conversation(self) -> None:
        engine = self._make_engine()
        msgs = [
            Message(role=Role.USER, content="Hi"),
            Message(role=Role.ASSISTANT, content="Hello!"),
            Message(role=Role.USER, content="How are you?"),
        ]
        result = engine._messages_to_prompt(msgs)
        assert result == (
            "<start_of_turn>user\nHi<end_of_turn>\n"
            "<start_of_turn>model\nHello!<end_of_turn>\n"
            "<start_of_turn>user\nHow are you?<end_of_turn>\n"
            "<start_of_turn>model\n"
        )

    def test_trailing_system_message_discarded(self) -> None:
        engine = self._make_engine()
        msgs = [
            Message(role=Role.SYSTEM, content="Ignored system"),
        ]
        result = engine._messages_to_prompt(msgs)
        assert result == "<start_of_turn>model\n"

    def test_multiple_system_messages_concatenated(self) -> None:

        engine = self._make_engine()
        msgs = [
            Message(role=Role.SYSTEM, content="Rule 1"),
            Message(role=Role.SYSTEM, content="Rule 2"),
            Message(role=Role.USER, content="Go"),
        ]
        result = engine._messages_to_prompt(msgs)
        assert result == (
            "<start_of_turn>user\n"
            "Rule 1\n\nRule 2\n\nGo<end_of_turn>\n"
            "<start_of_turn>model\n"
        )


class TestGemmaCppLifecycle:
    def _make_engine(self, **kwargs):
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        defaults = {
            "model_path": "/fake/model.sbs",
            "tokenizer_path": "/fake/tokenizer.spm",
            "model_type": "2b-it",
        }
        defaults.update(kwargs)
        return GemmaCppEngine(**defaults)

    @patch("openjarvis.engine.gemma_cpp._import_pygemma")
    def test_prepare_loads_model(self, mock_import) -> None:
        mock_gemma_cls = MagicMock()
        mock_import.return_value = mock_gemma_cls
        engine = self._make_engine()
        engine.prepare("2b-it")
        mock_gemma_cls.assert_called_once()
        mock_gemma_cls.return_value.load_model.assert_called_once_with(
            "/fake/tokenizer.spm", "/fake/model.sbs", "2b-it"
        )

    @patch("openjarvis.engine.gemma_cpp._import_pygemma")
    def test_prepare_idempotent(self, mock_import) -> None:
        mock_gemma_cls = MagicMock()
        mock_import.return_value = mock_gemma_cls
        engine = self._make_engine()
        engine.prepare("2b-it")
        engine.prepare("2b-it")
        # Only loaded once
        assert mock_gemma_cls.call_count == 1

    @patch("openjarvis.engine.gemma_cpp._import_pygemma")
    def test_close_unloads_model(self, mock_import) -> None:
        mock_gemma_cls = MagicMock()
        mock_import.return_value = mock_gemma_cls
        engine = self._make_engine()
        engine.prepare("2b-it")
        assert engine._gemma is not None
        engine.close()
        assert engine._gemma is None

    @patch("openjarvis.engine.gemma_cpp._import_pygemma")
    def test_generate_returns_dict(self, mock_import) -> None:
        mock_gemma_cls = MagicMock()
        mock_gemma_instance = MagicMock()
        mock_gemma_instance.completion.return_value = "The answer is 4."
        mock_gemma_cls.return_value = mock_gemma_instance
        mock_import.return_value = mock_gemma_cls

        engine = self._make_engine()
        result = engine.generate(
            [Message(role=Role.USER, content="What is 2+2?")],
            model="2b-it",
        )
        assert result["content"] == "The answer is 4."
        assert "usage" in result
        assert result["usage"]["prompt_tokens"] > 0
        assert result["usage"]["completion_tokens"] > 0
        assert result["usage"]["total_tokens"] > 0
        assert result["model"] == "2b-it"
        assert result["finish_reason"] == "stop"

    @patch("openjarvis.engine.gemma_cpp._import_pygemma")
    def test_generate_warns_on_model_mismatch(self, mock_import) -> None:
        mock_gemma_cls = MagicMock()
        mock_gemma_instance = MagicMock()
        mock_gemma_instance.completion.return_value = "ok"
        mock_gemma_cls.return_value = mock_gemma_instance
        mock_import.return_value = mock_gemma_cls

        engine = self._make_engine(model_type="2b-it")
        from openjarvis.engine import gemma_cpp as gc_mod

        with patch.object(gc_mod.logger, "warning") as mock_warn:
            engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model="9b-it",
            )
            mock_warn.assert_called_once()

    @patch("openjarvis.engine.gemma_cpp._import_pygemma")
    def test_generate_wraps_runtime_error(self, mock_import) -> None:
        mock_gemma_cls = MagicMock()
        mock_gemma_instance = MagicMock()
        mock_gemma_instance.completion.side_effect = Exception("segfault")
        mock_gemma_cls.return_value = mock_gemma_instance
        mock_import.return_value = mock_gemma_cls

        engine = self._make_engine()
        with pytest.raises(RuntimeError, match="gemma.cpp inference failed"):
            engine.generate(
                [Message(role=Role.USER, content="Hi")],
                model="2b-it",
            )


class TestGemmaCppStream:
    @patch("openjarvis.engine.gemma_cpp._import_pygemma")
    @pytest.mark.asyncio
    async def test_stream_yields_content(self, mock_import) -> None:
        mock_gemma_cls = MagicMock()
        mock_gemma_instance = MagicMock()
        mock_gemma_instance.completion.return_value = "streamed output"
        mock_gemma_cls.return_value = mock_gemma_instance
        mock_import.return_value = mock_gemma_cls

        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        engine = GemmaCppEngine(
            model_path="/fake/model.sbs",
            tokenizer_path="/fake/tokenizer.spm",
            model_type="2b-it",
        )
        chunks = []
        async for chunk in engine.stream(
            [Message(role=Role.USER, content="Hi")],
            model="2b-it",
        ):
            chunks.append(chunk)
        assert len(chunks) == 1
        assert chunks[0] == "streamed output"


class TestGemmaCppHealth:
    def test_health_true_when_configured_and_files_exist(self, tmp_path) -> None:
        model_file = tmp_path / "model.sbs"
        tokenizer_file = tmp_path / "tokenizer.spm"
        model_file.write_text("fake")
        tokenizer_file.write_text("fake")
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        engine = GemmaCppEngine(
            model_path=str(model_file),
            tokenizer_path=str(tokenizer_file),
            model_type="2b-it",
        )
        with patch("openjarvis.engine.gemma_cpp._import_pygemma"):
            assert engine.health() is True

    def test_health_false_when_files_missing(self) -> None:
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        engine = GemmaCppEngine(
            model_path="/nonexistent/model.sbs",
            tokenizer_path="/nonexistent/tokenizer.spm",
            model_type="2b-it",
        )
        assert engine.health() is False

    def test_health_false_when_unconfigured(self) -> None:
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        engine = GemmaCppEngine()
        assert engine.health() is False

    def test_health_false_when_pygemma_missing(self, tmp_path) -> None:
        model_file = tmp_path / "model.sbs"
        tokenizer_file = tmp_path / "tokenizer.spm"
        model_file.write_text("fake")
        tokenizer_file.write_text("fake")
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        engine = GemmaCppEngine(
            model_path=str(model_file),
            tokenizer_path=str(tokenizer_file),
            model_type="2b-it",
        )
        with patch(
            "openjarvis.engine.gemma_cpp._import_pygemma",
            side_effect=ImportError("no pygemma"),
        ):
            assert engine.health() is False


class TestGemmaCppListModels:
    def test_list_models_configured(self, tmp_path) -> None:
        model_file = tmp_path / "model.sbs"
        tokenizer_file = tmp_path / "tokenizer.spm"
        model_file.write_text("fake")
        tokenizer_file.write_text("fake")
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        engine = GemmaCppEngine(
            model_path=str(model_file),
            tokenizer_path=str(tokenizer_file),
            model_type="2b-it",
        )
        assert engine.list_models() == ["2b-it"]

    def test_list_models_unconfigured(self) -> None:
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        engine = GemmaCppEngine()
        assert engine.list_models() == []

    def test_list_models_files_missing(self) -> None:
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        engine = GemmaCppEngine(
            model_path="/nonexistent/model.sbs",
            tokenizer_path="/nonexistent/tokenizer.spm",
            model_type="2b-it",
        )
        assert engine.list_models() == []


class TestGemmaCppConfigResolution:
    def test_explicit_args_take_priority(self) -> None:
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        with patch.dict(os.environ, {"GEMMA_CPP_MODEL_PATH": "/env/model"}):
            engine = GemmaCppEngine(model_path="/explicit/model")
        assert engine._model_path == "/explicit/model"

    def test_env_vars_fallback(self) -> None:
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        env = {
            "GEMMA_CPP_MODEL_PATH": "/env/model.sbs",
            "GEMMA_CPP_TOKENIZER_PATH": "/env/tokenizer.spm",
            "GEMMA_CPP_MODEL_TYPE": "9b-it",
            "GEMMA_CPP_NUM_THREADS": "8",
        }
        with patch.dict(os.environ, env):
            engine = GemmaCppEngine()
        assert engine._model_path == "/env/model.sbs"
        assert engine._tokenizer_path == "/env/tokenizer.spm"
        assert engine._model_type == "9b-it"
        assert engine._num_threads == 8

    def test_defaults_when_nothing_set(self) -> None:
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        with patch.dict(os.environ, {}, clear=True):
            engine = GemmaCppEngine()
        assert engine._model_path == ""
        assert engine._tokenizer_path == ""
        assert engine._model_type == ""
        assert engine._num_threads == 0


class TestGemmaCppDiscovery:
    def test_host_map_contains_gemma_cpp(self) -> None:
        from openjarvis.engine._discovery import _HOST_MAP

        assert "gemma_cpp" in _HOST_MAP
        assert _HOST_MAP["gemma_cpp"] is None

    def test_make_engine_passes_config(self) -> None:
        from openjarvis.core.config import GemmaCppEngineConfig, JarvisConfig
        from openjarvis.core.registry import EngineRegistry
        from openjarvis.engine._discovery import _make_engine
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        EngineRegistry.register_value("gemma_cpp", GemmaCppEngine)
        config = JarvisConfig()
        config.engine.gemma_cpp = GemmaCppEngineConfig(
            model_path="/cfg/model.sbs",
            tokenizer_path="/cfg/tokenizer.spm",
            model_type="9b-it",
            num_threads=4,
        )
        engine = _make_engine("gemma_cpp", config)
        assert engine._model_path == "/cfg/model.sbs"
        assert engine._tokenizer_path == "/cfg/tokenizer.spm"
        assert engine._model_type == "9b-it"
        assert engine._num_threads == 4

    def test_registry_contains_gemma_cpp(self) -> None:
        from openjarvis.core.registry import EngineRegistry
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        EngineRegistry.register_value("gemma_cpp", GemmaCppEngine)
        assert EngineRegistry.contains("gemma_cpp")


@pytest.mark.live
class TestGemmaCppLive:
    """Integration tests — require pygemma and downloaded Gemma weights.

    Set GEMMA_CPP_MODEL_PATH, GEMMA_CPP_TOKENIZER_PATH, and
    GEMMA_CPP_MODEL_TYPE env vars before running.
    """

    def _make_engine(self):
        from openjarvis.engine.gemma_cpp import GemmaCppEngine

        return GemmaCppEngine()

    def test_real_inference_produces_output(self) -> None:
        engine = self._make_engine()
        result = engine.generate(
            [Message(role=Role.USER, content="What is 2+2?")],
            model=os.environ.get("GEMMA_CPP_MODEL_TYPE", "2b-it"),
        )
        assert result["content"]
        assert len(result["content"]) > 0

    def test_prepare_and_close_lifecycle(self) -> None:
        engine = self._make_engine()
        model_type = os.environ.get("GEMMA_CPP_MODEL_TYPE", "2b-it")
        engine.prepare(model_type)
        assert engine._gemma is not None
        engine.close()
        assert engine._gemma is None

    @pytest.mark.asyncio
    async def test_stream_yields_content(self) -> None:
        engine = self._make_engine()
        chunks = []
        async for chunk in engine.stream(
            [Message(role=Role.USER, content="Say hello")],
            model=os.environ.get("GEMMA_CPP_MODEL_TYPE", "2b-it"),
        ):
            chunks.append(chunk)
        assert len(chunks) > 0
        assert all(len(c) > 0 for c in chunks)

    def test_token_counts_are_positive(self) -> None:
        engine = self._make_engine()
        result = engine.generate(
            [Message(role=Role.USER, content="Tell me a joke")],
            model=os.environ.get("GEMMA_CPP_MODEL_TYPE", "2b-it"),
        )
        assert result["usage"]["prompt_tokens"] > 0
        assert result["usage"]["completion_tokens"] > 0
        assert result["usage"]["total_tokens"] > 0
