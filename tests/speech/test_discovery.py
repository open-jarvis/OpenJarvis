"""Tests for speech backend auto-discovery."""

from unittest.mock import patch

from openjarvis.core.config import JarvisConfig


def test_get_speech_backend_explicit():
    """Explicit backend selection works."""
    from openjarvis.speech._discovery import get_speech_backend

    config = JarvisConfig()
    config.speech.backend = "faster-whisper"

    with patch("openjarvis.speech._discovery._create_backend") as mock_create:
        mock_backend = type(
            "MockBackend",
            (),
            {
                "backend_id": "faster-whisper",
                "health": lambda self: True,
            },
        )()
        mock_create.return_value = mock_backend

        result = get_speech_backend(config)
        assert result is not None
        assert result.backend_id == "faster-whisper"


def test_faster_whisper_receives_runtime_model_path():
    """The local backend keeps downloaded models inside OPENJARVIS_HOME."""
    from openjarvis.speech._discovery import _create_backend

    config = JarvisConfig()
    config.speech.model = "base"
    config.speech.device = "cpu"
    config.speech.compute_type = "int8"
    config.speech.stt_runtime_path = r"C:\runtime\speech\models"

    class MockBackend:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    backend_cls = MockBackend
    with (
        patch("openjarvis.core.registry.SpeechRegistry.contains", return_value=True),
        patch("openjarvis.core.registry.SpeechRegistry.get", return_value=backend_cls),
    ):
        result = _create_backend("faster-whisper", config)

    assert result is not None
    assert result.model_size == "base"
    assert result.device == "cpu"
    assert result.compute_type == "int8"
    assert result.download_root == r"C:\runtime\speech\models"


def test_get_speech_backend_returns_none_if_nothing_available():
    """Returns None when no backend can be created."""
    from openjarvis.speech._discovery import get_speech_backend

    config = JarvisConfig()
    config.speech.backend = "nonexistent"

    result = get_speech_backend(config)
    assert result is None


def test_auto_discovery_priority():
    """Auto mode keeps cloud providers out of its safe local order."""
    from openjarvis.speech._discovery import DISCOVERY_ORDER, LOCAL_DISCOVERY_ORDER

    assert DISCOVERY_ORDER[0] == "faster-whisper"
    assert "openai" in DISCOVERY_ORDER
    assert "deepgram" in DISCOVERY_ORDER
    assert LOCAL_DISCOVERY_ORDER == ["faster-whisper"]
    assert "openai" not in LOCAL_DISCOVERY_ORDER
    assert "deepgram" not in LOCAL_DISCOVERY_ORDER
