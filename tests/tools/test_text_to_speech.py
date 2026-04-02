"""Tests for the text_to_speech tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openjarvis.core.registry import ToolRegistry
from openjarvis.speech.tts import TTSResult


def test_tts_tool_registered():
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    ToolRegistry.register_value("text_to_speech", TextToSpeechTool)
    assert ToolRegistry.contains("text_to_speech")


def test_tts_tool_execute(tmp_path):
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    mock_result = TTSResult(
        audio=b"fake-audio-data",
        format="mp3",
        voice_id="jarvis",
        duration_seconds=2.5,
    )

    with patch(
        "openjarvis.tools.text_to_speech.TTSRegistry"
    ) as mock_registry:
        mock_backend_cls = MagicMock()
        mock_backend_cls.return_value.synthesize.return_value = mock_result
        mock_registry.contains.return_value = True
        mock_registry.get.return_value = mock_backend_cls

        result = tool.execute(
            text="Good morning sir.",
            voice_id="jarvis",
            backend="cartesia",
            output_dir=str(tmp_path),
        )

    assert result.success is True
    assert "digest.mp3" in result.content
    assert (tmp_path / "digest.mp3").exists()
    assert (tmp_path / "digest.mp3").read_bytes() == b"fake-audio-data"


def test_tts_tool_empty_text():
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    result = tool.execute(text="")
    assert result.success is False
