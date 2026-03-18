"""Tests for the audio_transcribe tool."""

from __future__ import annotations

import builtins
import sys
from unittest.mock import MagicMock

from openjarvis.tools.audio_tool import AudioTranscribeTool


class TestAudioTranscribeTool:
    def test_spec(self):
        tool = AudioTranscribeTool()
        assert tool.spec.name == "audio_transcribe"
        assert tool.spec.category == "media"
        assert "file_path" in tool.spec.parameters["properties"]
        assert "file_path" in tool.spec.parameters["required"]
        assert tool.spec.required_capabilities == ["file:read"]

    def test_tool_id(self):
        tool = AudioTranscribeTool()
        assert tool.tool_id == "audio_transcribe"

    def test_no_file_path(self):
        tool = AudioTranscribeTool()
        result = tool.execute(file_path="")
        assert result.success is False
        assert "No file_path" in result.content

    def test_no_file_path_param(self):
        tool = AudioTranscribeTool()
        result = tool.execute()
        assert result.success is False
        assert "No file_path" in result.content

    def test_file_not_found(self):
        tool = AudioTranscribeTool()
        result = tool.execute(file_path="/nonexistent/audio.mp3")
        assert result.success is False
        assert "File not found" in result.content

    def test_unsupported_format(self, tmp_path):
        f = tmp_path / "audio.xyz"
        f.write_text("not audio", encoding="utf-8")
        tool = AudioTranscribeTool()
        result = tool.execute(file_path=str(f))
        assert result.success is False
        assert "Unsupported audio format" in result.content

    def test_file_too_large(self, tmp_path):
        f = tmp_path / "large.mp3"
        # Create a file that appears to exceed 25 MB
        # Write a small file first, then mock stat to report large size
        f.write_bytes(b"\x00" * 1024)

        tool = AudioTranscribeTool()
        # Mock the stat to return a size > 25 MB
        import unittest.mock

        large_stat = MagicMock()
        large_stat.st_size = 26 * 1024 * 1024  # 26 MB

        with unittest.mock.patch("pathlib.Path.stat", return_value=large_stat):
            result = tool.execute(file_path=str(f))
        assert result.success is False
        assert "File too large" in result.content

    def test_local_provider_not_implemented(self, tmp_path):
        f = tmp_path / "audio.wav"
        f.write_bytes(b"\x00" * 100)
        tool = AudioTranscribeTool()
        result = tool.execute(file_path=str(f), provider="local")
        assert result.success is False
        assert "not yet implemented" in result.content

    def test_unsupported_provider(self, tmp_path):
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\x00" * 100)
        tool = AudioTranscribeTool()
        result = tool.execute(file_path=str(f), provider="google")
        assert result.success is False
        assert "Unsupported provider" in result.content

    def test_openai_not_installed(self, tmp_path, monkeypatch):
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\x00" * 100)

        monkeypatch.delitem(sys.modules, "openai", raising=False)
        original_import = builtins.__import__

        def _mock_import(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("No module named 'openai'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _mock_import)

        tool = AudioTranscribeTool()
        result = tool.execute(file_path=str(f))
        assert result.success is False
        assert "openai package not installed" in result.content

    def test_no_api_key(self, tmp_path, monkeypatch):
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\x00" * 100)

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        mock_openai = MagicMock()
        monkeypatch.setitem(sys.modules, "openai", mock_openai)

        tool = AudioTranscribeTool()
        result = tool.execute(file_path=str(f))
        assert result.success is False
        assert "No API key" in result.content

    def test_successful_transcription(self, tmp_path, monkeypatch):
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\x00" * 100)

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        mock_transcription = MagicMock()
        mock_transcription.text = "Hello, this is a transcription."
        mock_transcription.duration = 5.5

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = mock_transcription

        mock_openai = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        monkeypatch.setitem(sys.modules, "openai", mock_openai)

        tool = AudioTranscribeTool()
        result = tool.execute(file_path=str(f))
        assert result.success is True
        assert result.content == "Hello, this is a transcription."
        assert result.metadata["provider"] == "openai"
        assert result.metadata["duration_ms"] == 5500

    def test_successful_transcription_with_language(self, tmp_path, monkeypatch):
        f = tmp_path / "audio.wav"
        f.write_bytes(b"\x00" * 100)

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        mock_transcription = MagicMock()
        mock_transcription.text = "Hola mundo."
        # No duration attribute
        del mock_transcription.duration

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.return_value = mock_transcription

        mock_openai = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        monkeypatch.setitem(sys.modules, "openai", mock_openai)

        tool = AudioTranscribeTool()
        result = tool.execute(file_path=str(f), language="es")
        assert result.success is True
        assert result.content == "Hola mundo."
        assert result.metadata["language"] == "es"

    def test_api_error(self, tmp_path, monkeypatch):
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\x00" * 100)

        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        mock_client = MagicMock()
        mock_client.audio.transcriptions.create.side_effect = RuntimeError("API error")

        mock_openai = MagicMock()
        mock_openai.OpenAI.return_value = mock_client
        monkeypatch.setitem(sys.modules, "openai", mock_openai)

        tool = AudioTranscribeTool()
        result = tool.execute(file_path=str(f))
        assert result.success is False
        assert "Transcription error" in result.content

    def test_supported_formats_accepted(self, tmp_path):
        """All supported formats pass the format check (fail later due to no API)."""
        tool = AudioTranscribeTool()
        for ext in [".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm"]:
            f = tmp_path / f"audio{ext}"
            f.write_bytes(b"\x00" * 100)
            result = tool.execute(file_path=str(f))
            # Should not fail on format — will fail on API/import instead
            assert "Unsupported audio format" not in result.content

    def test_to_openai_function(self):
        tool = AudioTranscribeTool()
        fn = tool.to_openai_function()
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "audio_transcribe"
