from openjarvis.speech.providers import (
    DisabledSpeechToTextProvider,
    DisabledTextToSpeechProvider,
    SpeechToTextProvider,
    TextToSpeechProvider,
)


def test_disabled_providers_are_explicit_and_unavailable() -> None:
    stt = DisabledSpeechToTextProvider()
    tts = DisabledTextToSpeechProvider()

    assert isinstance(stt, SpeechToTextProvider)
    assert isinstance(tts, TextToSpeechProvider)
    assert stt.backend_id == tts.backend_id == "disabled"
    assert stt.health() is False
    assert tts.health() is False
