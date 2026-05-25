"""Tests for local voice listen-once API."""

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.core.config import JarvisConfig  # noqa: E402
from openjarvis.server.api_routes import voice_router  # noqa: E402
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
    audio_path.write_bytes(b"wav")
    model_path.write_bytes(b"model")
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
        command_path="/opt/homebrew/bin/whisper-cli",
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
    audio_path.write_bytes(b"wav")
    model_path.write_bytes(b"model")
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
        command_path="/opt/homebrew/bin/whisper-cli",
        model_path=str(model_path),
        language="auto",
    )

    result = adapter.transcribe_once(audio_path)

    assert result.ok is True
    cmd, _kwargs = calls[0]
    assert "-l" not in cmd


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
