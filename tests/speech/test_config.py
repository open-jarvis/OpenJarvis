"""Tests for speech configuration."""

from friday_ai.core.config import FridayConfig, SpeechConfig


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "base"
    assert cfg.language == ""
    assert cfg.device == "auto"
    assert cfg.compute_type == "float16"


def test_friday_config_has_speech():
    cfg = FridayConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_friday_system_has_speech_backend():
    """FridaySystem has a speech_backend attribute."""
    from friday_ai.system import FridaySystem

    assert "speech_backend" in FridaySystem.__dataclass_fields__
