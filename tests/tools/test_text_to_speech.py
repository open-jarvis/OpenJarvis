"""Tests for the text_to_speech tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

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

    with patch("openjarvis.tools.text_to_speech.TTSRegistry") as mock_registry:
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
    saved = Path(result.content)
    assert saved.parent == tmp_path
    assert saved.suffix == ".mp3"
    assert saved.exists()
    assert saved.read_bytes() == b"fake-audio-data"


def test_tts_tool_empty_text():
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    result = tool.execute(text="")
    assert result.success is False


def _mock_backend(voice_id="af_heart", fmt="wav"):
    """A registry whose backend echoes the voice_id it was actually called with."""
    from openjarvis.speech.tts import TTSResult

    backend = MagicMock()

    def _synthesize(text, **kwargs):
        return TTSResult(
            audio=b"fake-audio-data",
            format=fmt,
            voice_id=kwargs.get("voice_id", voice_id),
            duration_seconds=1.0,
        )

    backend.synthesize.side_effect = _synthesize
    backend_cls = MagicMock(return_value=backend)

    registry = MagicMock()
    registry.contains.return_value = True
    registry.get.return_value = backend_cls
    return registry, backend


def test_tts_omits_unset_voice_id_and_speed(tmp_path):
    """Unset optional params must not be forwarded, so the backend's own
    defaults win. Forwarding voice_id="" / speed=1.0 is the #971 bug: it makes
    kokoro (which defaults voice_id to "af_heart") 404 on an empty voice."""
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    registry, backend = _mock_backend()

    # Neutralize the config fallback so this test exercises the pure param path
    # regardless of any speech config on the host.
    with (
        patch("openjarvis.tools.text_to_speech.TTSRegistry", registry),
        patch(
            "openjarvis.core.config.load_config",
            side_effect=RuntimeError("no config"),
        ),
    ):
        result = tool.execute(text="hello", backend="kokoro", output_dir=str(tmp_path))

    assert result.success is True
    call_kwargs = backend.synthesize.call_args.kwargs
    assert "voice_id" not in call_kwargs
    assert "speed" not in call_kwargs


def test_tts_forwards_explicit_voice_id_and_speed(tmp_path):
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    registry, backend = _mock_backend()

    with patch("openjarvis.tools.text_to_speech.TTSRegistry", registry):
        tool.execute(
            text="hello",
            backend="kokoro",
            voice_id="bf_emma",
            speed=1.3,
            output_dir=str(tmp_path),
        )

    call_kwargs = backend.synthesize.call_args.kwargs
    assert call_kwargs["voice_id"] == "bf_emma"
    assert call_kwargs["speed"] == 1.3


def test_tts_forwards_zero_speed(tmp_path):
    """0 is a legitimate value, not "unset", and must be forwarded."""
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    registry, backend = _mock_backend()

    with patch("openjarvis.tools.text_to_speech.TTSRegistry", registry):
        tool.execute(text="hello", backend="kokoro", speed=0, output_dir=str(tmp_path))

    assert backend.synthesize.call_args.kwargs["speed"] == 0.0


def test_tts_unique_filenames_no_overwrite(tmp_path):
    """Two calls with identical text and voice into one dir must not collide."""
    from openjarvis.tools.text_to_speech import TextToSpeechTool

    tool = TextToSpeechTool()
    registry, _ = _mock_backend()

    with patch("openjarvis.tools.text_to_speech.TTSRegistry", registry):
        first = tool.execute(
            text="same line", backend="kokoro", output_dir=str(tmp_path)
        )
        second = tool.execute(
            text="same line", backend="kokoro", output_dir=str(tmp_path)
        )

    assert first.content != second.content
    assert Path(first.content).exists()
    assert Path(second.content).exists()
