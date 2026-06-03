"""Tests for local voice listen-once API."""

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.core.config import JarvisConfig  # noqa: E402
from openjarvis.server.api_routes import voice_router  # noqa: E402
from openjarvis.speech._stubs import TranscriptionResult  # noqa: E402
from openjarvis.voice.adapters import (  # noqa: E402
    STTAdapter,
    STTResult,
    WhisperCppSTTAdapter,
    create_stt_adapter,
)
from openjarvis.voice.recorder import (  # noqa: E402
    HOMEBREW_REC_PATH,
    AudioRecorder,
    RecordingError,
)
from openjarvis.voice.tts import cleanup_tts_text, split_tts_chunks  # noqa: E402


class MockRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.called = False

    def record_once(self) -> Path:
        self.called = True
        self.path.write_bytes(b"fake wav")
        return self.path


class MockAdapter(STTAdapter):
    engine = "mock"

    def __init__(self, *, available: bool = True, text: str = "안녕하세요") -> None:
        self.available = available
        self.text = text
        self.transcribed_path: Path | None = None

    def check_available(self) -> bool:
        return self.available

    def transcribe_once(self, audio_path: Path) -> STTResult:
        self.transcribed_path = audio_path
        return STTResult(ok=True, text=self.text, engine=self.engine)

    def get_setup_message(self) -> str:
        return "로컬 STT 설정이 필요합니다"


def make_client(config: JarvisConfig, *, recorder=None, adapter=None) -> TestClient:
    app = FastAPI()
    app.state.config = config
    app.state.voice_recorder = recorder
    app.state.voice_stt_adapter = adapter
    app.include_router(voice_router)
    return TestClient(app)


def test_listen_once_success(tmp_path):
    cfg = JarvisConfig()
    cfg.voice.stt_enabled = True
    cfg.voice.stt_engine = "custom"
    recorder = MockRecorder(tmp_path / "clip.wav")
    adapter = MockAdapter(text="오늘 일정 알려줘")

    response = make_client(cfg, recorder=recorder, adapter=adapter).post(
        "/v1/voice/listen-once"
    )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "text": "오늘 일정 알려줘",
        "engine": "mock",
        "mode": "local_backend",
        "message": "",
    }
    assert recorder.called is True
    assert adapter.transcribed_path is not None
    assert not adapter.transcribed_path.exists()


def test_transcribe_upload_uses_speech_backend():
    cfg = JarvisConfig()

    class Backend:
        backend_id = "fake-speech"

        def transcribe(self, audio, *, format="wav", language=None):
            assert audio == b"fake audio"
            assert format == "webm"
            assert language == "ko"
            return TranscriptionResult(
                text="마이크 테스트",
                language="ko",
                confidence=0.9,
                duration_seconds=1.2,
            )

    app = FastAPI()
    app.state.config = cfg
    app.state.speech_backend = Backend()
    app.include_router(voice_router)

    response = TestClient(app).post(
        "/v1/voice/transcribe",
        files={"file": ("clip.webm", b"fake audio", "audio/webm")},
        data={"language": "ko"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["text"] == "마이크 테스트"
    assert data["engine"] == "fake-speech"
    assert data["mode"] == "uploaded_audio"
    assert data["confidence"] == 0.9


def test_transcribe_upload_uses_voice_adapter():
    cfg = JarvisConfig()
    cfg.voice.stt_enabled = True
    cfg.voice.stt_engine = "custom"
    adapter = MockAdapter(text="업로드 음성")

    client = make_client(cfg, adapter=adapter)

    response = client.post(
        "/v1/voice/transcribe",
        files={"file": ("clip.webm", b"fake audio", "audio/webm")},
        data={"language": "ko"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["text"] == "업로드 음성"
    assert data["engine"] == "mock"
    assert data["mode"] == "uploaded_audio"
    assert adapter.transcribed_path is not None
    assert not adapter.transcribed_path.exists()


def test_listen_once_missing_stt_engine(tmp_path):
    cfg = JarvisConfig()
    cfg.voice.stt_enabled = True
    cfg.voice.stt_engine = "custom"

    response = make_client(
        cfg,
        recorder=MockRecorder(tmp_path / "clip.wav"),
        adapter=MockAdapter(available=False),
    ).post("/v1/voice/listen-once")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["engine"] == "mock"
    assert "로컬 STT 설정" in data["message"]


def test_listen_once_disabled_stt():
    cfg = JarvisConfig()
    cfg.voice.stt_enabled = False

    response = make_client(cfg, adapter=MockAdapter()).post("/v1/voice/listen-once")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["engine"] == "mock"
    assert "비활성화" in data["message"]


def test_adapter_routing():
    cfg = JarvisConfig()
    cfg.voice.stt_enabled = True

    cfg.voice.stt_engine = "whisper_cpp"
    assert create_stt_adapter(cfg.voice).engine == "whisper_cpp"

    cfg.voice.stt_engine = "faster_whisper"
    assert create_stt_adapter(cfg.voice).engine == "faster_whisper"

    cfg.voice.stt_engine = "custom"
    assert create_stt_adapter(cfg.voice).engine == "custom"

    cfg.voice.stt_engine = "disabled"
    assert create_stt_adapter(cfg.voice).engine == "disabled"


def test_tts_text_cleanup_removes_markdown_urls_and_debug_metadata():
    cleaned = cleanup_tts_text(
        """
        - **오늘 요약** https://example.com
        ```python
        raise RuntimeError("boom")
        ```
        ollama tokens cost comparison
        일정은 오후 3시입니다.
        """,
        max_chars=200,
    )

    assert "https://" not in cleaned
    assert "python" not in cleaned
    assert "ollama" not in cleaned.lower()
    assert "tokens" not in cleaned.lower()
    assert "오늘 요약" in cleaned
    assert "일정은 오후 3시예요" in cleaned


def test_tts_text_cleanup_removes_tables_emoji_and_http_errors():
    table_cleaned = cleanup_tts_text(
        """
        | 항목 | 값 |
        | --- | --- |
        | 날씨 | 맑음 |
        좋아요 ☀️
        """,
        max_chars=200,
    )
    error_cleaned = cleanup_tts_text("HTTP 405 Method Not Allowed 오류입니다.")

    assert "|" not in table_cleaned
    assert "☀" not in table_cleaned
    assert "좋아요" in table_cleaned
    assert error_cleaned == ""


def test_tts_text_cleanup_removes_spoken_emoji_artifacts():
    cleaned = cleanup_tts_text(
        "좋아요 😊 ❤️ 👍🏽 ㅋㅋ 다음 작업을 진행할게요 :)",
        max_chars=200,
    )

    assert "좋아요" in cleaned
    assert "다음 작업을 진행할게요" in cleaned
    assert "😊" not in cleaned
    assert "❤" not in cleaned
    assert "👍" not in cleaned
    assert "ㅋㅋ" not in cleaned
    assert ":)" not in cleaned


def test_tts_text_cleanup_naturalizes_written_korean_for_speech():
    cleaned = cleanup_tts_text(
        "확인했습니다. 다음과 같습니다: macOS TTS API 설정이 필요합니다.",
        max_chars=200,
    )

    assert cleaned == (
        "확인했어요. 이렇게 정리했어요. 맥 오에스 티티에스 "
        "에이피아이 설정이 필요해요."
    )


def test_tts_weather_text_is_naturalized_for_korean_speech():
    cleaned = cleanup_tts_text(
        "현재 서울은 부분적으로 흐림, 기온 20.5°C(체감 23.3°C)입니다. "
        "오늘 예상 기온은 19°C~26.2°C, 최대 풍속은 4.8km/h, "
        "자외선 지수는 7.8입니다.",
        max_chars=400,
    )

    assert cleaned == (
        "서울은 지금 조금 흐려요. 기온은 약 20도예요. "
        "체감 온도는 23도 정도예요. 오늘은 19도에서 26도 사이로 예상돼요."
    )


def test_tts_long_text_is_split():
    chunks = split_tts_chunks("가" * 260, max_chars=80)

    assert len(chunks) >= 4
    assert all(len(chunk) <= 80 for chunk in chunks)


def test_macos_say_uses_safe_list_args_without_shell(monkeypatch):
    import openjarvis.voice.tts as tts

    calls = []

    class FakeSayPath:
        def exists(self):
            return True

        def __str__(self):
            return "/usr/bin/say"

    class Proc:
        def poll(self):
            return 0

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return Proc()

    monkeypatch.setattr(tts, "SAY_PATH", FakeSayPath())
    result = tts.speak_macos_say(
        "안녕하세요. 오늘 일정 알려드릴게요.",
        voice="Yuna",
        rate=175,
        max_chars=400,
        pause_ms=0,
        popen=fake_popen,
    )

    assert result.ok is True
    command, kwargs = calls[0]
    assert command[:5] == ["/usr/bin/say", "-v", "Yuna", "-r", "175"]
    assert "shell" not in kwargs


def test_macos_say_speaks_short_chunks_with_pause(monkeypatch):
    import threading

    import openjarvis.voice.tts as tts

    calls = []
    sleeps = []
    second_call = threading.Event()

    class FakeSayPath:
        def exists(self):
            return True

        def __str__(self):
            return "/usr/bin/say"

    class Proc:
        def poll(self):
            return 0

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        if len(calls) >= 2:
            second_call.set()
        return Proc()

    monkeypatch.setattr(tts, "SAY_PATH", FakeSayPath())
    monkeypatch.setattr(tts.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = tts.speak_macos_say(
        "첫 문장이에요. 두 번째 문장이에요.",
        voice="Yuna",
        rate=165,
        pause_ms=250,
        popen=fake_popen,
    )

    assert result.ok is True
    assert second_call.wait(1)
    assert result.chunks == ["첫 문장이에요.", "두 번째 문장이에요."]
    assert calls[0][0] == ["/usr/bin/say", "-v", "Yuna", "-r", "165", "첫 문장이에요."]
    assert calls[1][0] == [
        "/usr/bin/say",
        "-v",
        "Yuna",
        "-r",
        "165",
        "두 번째 문장이에요.",
    ]
    assert sleeps == [0.25]


def test_macos_say_empty_text_does_not_speak(monkeypatch):
    import openjarvis.voice.tts as tts

    class FakeSayPath:
        def exists(self):
            return True

    monkeypatch.setattr(tts, "SAY_PATH", FakeSayPath())
    calls = []
    result = tts.speak_macos_say("```code``` https://example.com", popen=calls.append)

    assert result.ok is False
    assert calls == []


def test_elevenlabs_missing_key_returns_setup_message():
    import openjarvis.voice.tts as tts

    result = tts.speak_elevenlabs_tts(
        "안녕하세요",
        voice_id="voice-id",
        env={},
    )

    assert result.ok is False
    assert result.engine == "elevenlabs"
    assert "클라우드 TTS 설정" in result.message


def test_elevenlabs_tts_uses_env_key_without_logging_secret(monkeypatch, caplog):
    import openjarvis.voice.tts as tts

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"mp3"

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return Response()

    def fake_play(audio, **kwargs):
        return tts.SpeakResult(ok=True, engine="elevenlabs", message="음성 응답 중...")

    monkeypatch.setattr(tts, "play_audio_bytes", fake_play)

    result = tts.speak_elevenlabs_tts(
        "안녕하세요 https://example.com",
        voice_id="voice-id",
        model="eleven_v3",
        env={"ELEVENLABS_API_KEY": "secret-eleven-key"},
        urlopen=fake_urlopen,
    )

    assert result.ok is True
    assert result.engine == "elevenlabs"
    assert captured["url"] == "https://api.elevenlabs.io/v1/text-to-speech/voice-id"
    assert captured["headers"]["Xi-api-key"] == "secret-eleven-key"
    assert "https://example.com" not in captured["body"]
    assert '"model_id": "eleven_v3"' in captured["body"]
    assert '"style": 0.45' in captured["body"]
    assert '"use_speaker_boost": true' in captured["body"]
    assert captured["timeout"] == 20
    assert "secret-eleven-key" not in caplog.text


def test_gemini_tts_missing_key_returns_setup_message():
    import openjarvis.voice.tts as tts

    result = tts.speak_gemini_tts("안녕하세요", env={})

    assert result.ok is False
    assert result.engine == "gemini_tts"
    assert "Gemini TTS API 키" in result.message


def test_gemini_tts_uses_env_key_and_wav_audio(monkeypatch):
    import base64
    import json

    import openjarvis.voice.tts as tts

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "data": base64.b64encode(
                                                b"\x00\x00"
                                            ).decode("ascii")
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return Response()

    def fake_play(audio, **kwargs):
        captured["audio_prefix"] = audio[:4]
        captured["suffix"] = kwargs["suffix"]
        return tts.SpeakResult(ok=True, engine="gemini_tts", message="음성 응답 중...")

    monkeypatch.setattr(tts, "play_audio_bytes", fake_play)

    result = tts.speak_gemini_tts(
        "확인했습니다.",
        voice="Yuna",
        env={"GEMINI_API_KEY": "secret-gemini-key"},
        urlopen=fake_urlopen,
    )

    assert result.ok is True
    assert result.engine == "gemini_tts"
    assert "gemini-2.5-flash-preview-tts:generateContent" in captured["url"]
    assert "secret-gemini-key" in captured["url"]
    assert captured["headers"]["Content-type"] == "application/json"
    assert captured["body"]["generationConfig"]["responseModalities"] == ["AUDIO"]
    voice_config = captured["body"]["generationConfig"]["speechConfig"]["voiceConfig"]
    assert voice_config["prebuiltVoiceConfig"]["voiceName"] == "Sulafat"
    assert captured["audio_prefix"] == b"RIFF"
    assert captured["suffix"] == ".wav"
    assert captured["timeout"] == 30


def test_gemini_tts_accepts_request_api_key(monkeypatch):
    import base64
    import json

    import openjarvis.voice.tts as tts

    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "data": base64.b64encode(
                                                b"\x00\x00"
                                            ).decode("ascii")
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return Response()

    monkeypatch.setattr(
        tts,
        "play_audio_bytes",
        lambda *args, **kwargs: tts.SpeakResult(ok=True, engine="gemini_tts"),
    )

    result = tts.speak_gemini_tts(
        "안녕하세요",
        api_key="request-gemini-key",
        env={},
        urlopen=fake_urlopen,
    )

    assert result.ok is True
    assert "request-gemini-key" in captured["url"]


def test_cloud_tts_missing_config_falls_back_to_macos_say(monkeypatch):
    import openjarvis.voice.tts as tts

    monkeypatch.setattr(tts.os, "environ", {})
    monkeypatch.setattr(
        tts,
        "speak_macos_say",
        lambda *args, **kwargs: tts.SpeakResult(
            ok=True,
            engine="macos_say",
            message="음성 응답 중...",
        ),
    )

    result = tts.speak_with_provider(
        "안녕하세요.",
        mode="elevenlabs",
        fallback_mode="macos_say",
    )

    assert result.ok is True
    assert result.engine == "macos_say"
    assert "클라우드 TTS 설정" in result.message


def test_gemini_tts_missing_config_falls_back_to_macos_say(monkeypatch):
    import openjarvis.voice.tts as tts

    monkeypatch.setattr(tts.os, "environ", {})
    monkeypatch.setattr(
        tts,
        "speak_macos_say",
        lambda *args, **kwargs: tts.SpeakResult(
            ok=True,
            engine="macos_say",
            message="음성 응답 중...",
        ),
    )

    result = tts.speak_with_provider(
        "안녕하세요.",
        mode="gemini_tts",
        fallback_mode="macos_say",
    )

    assert result.ok is True
    assert result.engine == "macos_say"
    assert "Gemini TTS API 키" in result.message


def test_piper_missing_binary_or_model_falls_back_to_macos_say(monkeypatch, tmp_path):
    import openjarvis.voice.tts as tts

    monkeypatch.setattr(
        tts,
        "speak_macos_say",
        lambda *args, **kwargs: tts.SpeakResult(
            ok=True,
            engine="macos_say",
            message="음성 응답 중...",
        ),
    )

    result = tts.speak_with_provider(
        "안녕하세요.",
        mode="piper",
        fallback_mode="macos_say",
        piper_path=str(tmp_path / "missing-piper"),
        piper_model=str(tmp_path / "missing.onnx"),
    )

    assert result.ok is True
    assert result.engine == "macos_say"
    assert "Piper TTS 설정" in result.message


def test_piper_uses_safe_list_args_without_shell(monkeypatch, tmp_path):
    import openjarvis.voice.tts as tts

    piper_path = tmp_path / "piper"
    model_path = tmp_path / "voice.onnx"
    piper_path.write_text("#!/bin/sh\n")
    model_path.write_bytes(b"model")
    calls = []

    class Completed:
        returncode = 0

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[-1]).write_bytes(b"wav")
        return Completed()

    def fake_play(audio, **kwargs):
        return tts.SpeakResult(ok=True, engine="piper", message="음성 응답 중...")

    monkeypatch.setattr(tts, "play_audio_bytes", fake_play)

    result = tts.speak_piper_tts(
        "안녕하세요 https://example.com",
        piper_path=str(piper_path),
        model_path=str(model_path),
        run=fake_run,
    )

    assert result.ok is True
    command, kwargs = calls[0]
    assert command[:4] == [str(piper_path), "--model", str(model_path), "--output_file"]
    assert "https://example.com" not in kwargs["input"]
    assert "shell" not in kwargs


def test_edge_tts_uses_safe_module_command(monkeypatch):
    import openjarvis.voice.tts as tts

    calls = []

    class Completed:
        returncode = 0

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        Path(command[-1]).write_bytes(b"mp3")
        return Completed()

    def fake_play(audio, **kwargs):
        return tts.SpeakResult(ok=True, engine="edge_tts", message="음성 응답 중...")

    monkeypatch.setattr(tts, "play_audio_bytes", fake_play)

    result = tts.speak_edge_tts(
        "안녕하세요 https://example.com",
        voice="ko-KR-InJoonNeural",
        rate=165,
        run=fake_run,
    )

    assert result.ok is True
    command, kwargs = calls[0]
    assert command[1:5] == ["-m", "edge_tts", "--voice", "ko-KR-InJoonNeural"]
    assert "--write-media" in command
    assert "https://example.com" not in command
    assert "shell" not in kwargs


def test_edge_tts_missing_config_falls_back_to_macos_say(monkeypatch):
    import openjarvis.voice.tts as tts

    monkeypatch.setattr(
        tts,
        "speak_edge_tts",
        lambda *args, **kwargs: tts.SpeakResult(
            ok=False,
            engine="edge_tts",
            message="edge failed",
        ),
    )
    monkeypatch.setattr(
        tts,
        "speak_macos_say",
        lambda *args, **kwargs: tts.SpeakResult(
            ok=True,
            engine="macos_say",
            message="음성 응답 중...",
        ),
    )

    result = tts.speak_with_provider(
        "안녕하세요.",
        mode="edge_tts",
        fallback_mode="macos_say",
    )

    assert result.ok is True
    assert result.engine == "macos_say"
    assert "edge failed" in result.message


def test_voice_speak_endpoint_failure_does_not_raise(monkeypatch):
    cfg = JarvisConfig()
    client = make_client(cfg)

    def fake_speak(*args, **kwargs):
        from openjarvis.voice.tts import SpeakResult

        return SpeakResult(ok=False, message="TTS 음성을 찾을 수 없습니다.")

    monkeypatch.setattr("openjarvis.voice.tts.speak_macos_say", fake_speak)

    response = client.post("/v1/voice/speak", json={"text": "안녕하세요"})

    assert response.status_code == 200
    assert response.json()["ok"] is False


def test_voice_speak_endpoint_cloud_missing_key_falls_back(monkeypatch):
    cfg = JarvisConfig()
    cfg.voice.tts_mode = "elevenlabs"
    cfg.voice.tts_fallback_mode = "macos_say"
    client = make_client(cfg)

    import openjarvis.voice.tts as tts

    monkeypatch.setattr(tts.os, "environ", {})
    monkeypatch.setattr(
        tts,
        "speak_macos_say",
        lambda *args, **kwargs: tts.SpeakResult(
            ok=True,
            engine="macos_say",
            message="음성 응답 중...",
        ),
    )

    response = client.post("/v1/voice/speak", json={"text": "안녕하세요"})

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["engine"] == "macos_say"
    assert "클라우드 TTS 설정" in data["message"]


def test_voice_speak_endpoint_accepts_request_tts_mode(monkeypatch):
    cfg = JarvisConfig()
    cfg.voice.tts_mode = "macos_say"
    cfg.voice.tts_fallback_mode = "macos_say"
    client = make_client(cfg)

    captured = {}

    def fake_speak_with_provider(*args, **kwargs):
        from openjarvis.voice.tts import SpeakResult

        captured.update(kwargs)
        return SpeakResult(ok=False, engine=kwargs["mode"], message="missing")

    monkeypatch.setattr(
        "openjarvis.voice.tts.speak_with_provider",
        fake_speak_with_provider,
    )

    response = client.post(
        "/v1/voice/speak",
        json={
            "text": "안녕하세요",
            "mode": "gemini_tts",
            "gemini_api_key": "request-gemini-key",
            "gemini_voice": "Achird",
            "edge_voice": "ko-KR-InJoonNeural",
        },
    )

    assert response.status_code == 200
    assert captured["mode"] == "gemini_tts"
    assert captured["elevenlabs_model"] == "eleven_v3"
    assert captured["gemini_model"] == "gemini-2.5-flash-preview-tts"
    assert captured["gemini_api_key"] == "request-gemini-key"
    assert captured["gemini_voice"] == "Achird"
    assert captured["edge_voice"] == "ko-KR-InJoonNeural"


def test_adapter_defaults_to_korean_language():
    cfg = JarvisConfig()
    cfg.voice.stt_enabled = True
    cfg.voice.stt_engine = "whisper_cpp"
    cfg.voice.whisper_cpp_path = "/opt/homebrew/bin/whisper-cli"
    cfg.voice.stt_model = "/tmp/ggml-base.bin"

    adapter = create_stt_adapter(cfg.voice)

    assert isinstance(adapter, WhisperCppSTTAdapter)
    assert adapter.language == "ko"


def test_adapter_accepts_legacy_voice_language():
    cfg = JarvisConfig()
    cfg.voice.stt_enabled = True
    cfg.voice.stt_engine = "whisper_cpp"
    cfg.voice.whisper_cpp_path = "/opt/homebrew/bin/whisper-cli"
    cfg.voice.stt_model = "/tmp/ggml-base.bin"
    cfg.voice.language = "auto"

    adapter = create_stt_adapter(cfg.voice)

    assert isinstance(adapter, WhisperCppSTTAdapter)
    assert adapter.language == "auto"


def test_whisper_cpp_command_includes_korean_language(tmp_path, monkeypatch):
    audio_path = tmp_path / "clip.wav"
    model_path = tmp_path / "ggml-base.bin"
    command_path = tmp_path / "whisper-cli"
    audio_path.write_bytes(b"wav")
    model_path.write_bytes(b"model")
    command_path.write_text("#!/bin/sh\n")
    calls = []

    class Result:
        returncode = 0
        stdout = "오늘 일정 알려줘"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    monkeypatch.setattr("openjarvis.voice.adapters.subprocess.run", fake_run)
    adapter = WhisperCppSTTAdapter(
        command_path=str(command_path),
        model_path=str(model_path),
        language="ko",
    )

    result = adapter.transcribe_once(audio_path)

    assert result.ok is True
    cmd, _kwargs = calls[0]
    assert cmd[-2:] == ["-l", "ko"]


def test_whisper_cpp_command_omits_language_for_auto(tmp_path, monkeypatch):
    audio_path = tmp_path / "clip.wav"
    model_path = tmp_path / "ggml-base.bin"
    command_path = tmp_path / "whisper-cli"
    audio_path.write_bytes(b"wav")
    model_path.write_bytes(b"model")
    command_path.write_text("#!/bin/sh\n")
    calls = []

    class Result:
        returncode = 0
        stdout = "오늘 일정 알려줘"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return Result()

    monkeypatch.setattr("openjarvis.voice.adapters.subprocess.run", fake_run)
    adapter = WhisperCppSTTAdapter(
        command_path=str(command_path),
        model_path=str(model_path),
        language="auto",
    )

    result = adapter.transcribe_once(audio_path)

    assert result.ok is True
    cmd, _kwargs = calls[0]
    assert "-l" not in cmd


def test_whisper_cpp_missing_command_returns_korean_setup_message(
    tmp_path,
    monkeypatch,
):
    model_path = tmp_path / "ggml-base.bin"
    model_path.write_bytes(b"model")
    monkeypatch.setattr("openjarvis.voice.adapters.shutil.which", lambda _name: None)

    adapter = WhisperCppSTTAdapter(
        command_path="",
        model_path=str(model_path),
        language="ko",
    )

    assert adapter.check_available() is False
    assert "whisper-cli를 찾을 수 없습니다" in adapter.get_setup_message()


def test_whisper_cpp_missing_model_returns_korean_setup_message():
    adapter = WhisperCppSTTAdapter(
        command_path="/opt/homebrew/bin/whisper-cli",
        model_path="/missing/ggml-base.bin",
        language="ko",
    )

    assert adapter.check_available() is False
    assert "모델 파일을 찾을 수 없습니다" in adapter.get_setup_message()


def test_recorder_prefers_configured_command(tmp_path):
    recorder_path = tmp_path / "rec"
    recorder_path.write_text("#!/bin/sh\n")

    recorder = AudioRecorder(recorder_command=str(recorder_path))

    assert recorder._resolve_recorder() == str(recorder_path)


def test_recorder_falls_back_to_homebrew_rec(monkeypatch):
    def fake_exists(self: Path) -> bool:
        return str(self) == HOMEBREW_REC_PATH

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr("openjarvis.voice.recorder.shutil.which", lambda _name: None)

    assert AudioRecorder()._resolve_recorder() == HOMEBREW_REC_PATH


def test_recorder_falls_back_to_path_rec(monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda _self: False)
    monkeypatch.setattr(
        "openjarvis.voice.recorder.shutil.which",
        lambda name: "/usr/local/bin/rec" if name == "rec" else None,
    )

    assert AudioRecorder()._resolve_recorder() == "/usr/local/bin/rec"


def test_recorder_missing_returns_korean_error(monkeypatch):
    monkeypatch.setattr(Path, "exists", lambda _self: False)
    monkeypatch.setattr("openjarvis.voice.recorder.shutil.which", lambda _name: None)

    with pytest.raises(RecordingError, match="rec를 찾을 수 없습니다"):
        AudioRecorder().record_once()


def test_recorder_invokes_rec_as_16000_mono_16_bit_wav(tmp_path, monkeypatch):
    recorder_path = tmp_path / "rec"
    recorder_path.write_text("#!/bin/sh\n")
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        Path(cmd[8]).write_bytes(b"wav")
        return Result()

    monkeypatch.setattr("openjarvis.voice.recorder.subprocess.run", fake_run)

    path = AudioRecorder(
        recording_seconds=4,
        sample_rate=16000,
        recorder_command=str(recorder_path),
    ).record_once()

    assert path.exists()
    path.unlink()
    cmd, kwargs = calls[0]
    assert cmd[:8] == [
        str(recorder_path),
        "-q",
        "-r",
        "16000",
        "-c",
        "1",
        "-b",
        "16",
    ]
    assert cmd[9:] == ["trim", "0", "4"]
    assert kwargs["timeout"] == 14
