"""Tests for speech configuration."""

from openjarvis.core.config import JarvisConfig, SpeechConfig


def test_speech_config_defaults():
    cfg = SpeechConfig()
    assert cfg.backend == "auto"
    assert cfg.model == "base"
    assert cfg.language == ""
    assert cfg.device == "auto"
    assert cfg.compute_type == "float16"
    assert cfg.hands_free is False
    assert cfg.turn_model == ""
    assert cfg.turn_pause_secs == 0.5


def test_speech_turn_taking_keys_load_from_toml(tmp_path):
    from openjarvis.core.config import load_config

    path = tmp_path / "config.toml"
    path.write_text(
        "[speech]\nhands_free = true\n"
        'turn_model = "C:/models/st.onnx"\nturn_pause_secs = 0.7\n',
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg.speech.hands_free is True
    assert cfg.speech.turn_model == "C:/models/st.onnx"
    assert cfg.speech.turn_pause_secs == 0.7


def test_jarvis_config_has_speech():
    cfg = JarvisConfig()
    assert hasattr(cfg, "speech")
    assert isinstance(cfg.speech, SpeechConfig)
    assert cfg.speech.backend == "auto"


def test_jarvis_system_has_speech_backend():
    """JarvisSystem has a speech_backend attribute."""
    from openjarvis.system import JarvisSystem

    assert "speech_backend" in JarvisSystem.__dataclass_fields__
