"""Listen-once orchestration for local backend STT."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from openjarvis.voice.adapters import STTAdapter, create_stt_adapter
from openjarvis.voice.recorder import AudioRecorder, RecordingError

if TYPE_CHECKING:
    from openjarvis.core.config import VoiceConfig


@dataclass(slots=True)
class ListenOnceResult:
    ok: bool
    text: str = ""
    engine: str = "disabled"
    mode: str = "local_backend"
    message: str = ""


def listen_once(
    config: "VoiceConfig",
    *,
    recorder: AudioRecorder | None = None,
    adapter: STTAdapter | None = None,
) -> ListenOnceResult:
    """Record one local clip and transcribe it with the configured adapter."""

    stt_adapter = adapter or create_stt_adapter(config)
    if not config.stt_enabled:
        return ListenOnceResult(
            ok=False,
            engine=stt_adapter.engine,
            message=(
                "로컬 STT가 비활성화되어 있습니다. "
                "설정에서 voice.stt_enabled를 켜주세요."
            ),
        )
    if not stt_adapter.check_available():
        return ListenOnceResult(
            ok=False,
            engine=stt_adapter.engine,
            message=stt_adapter.get_setup_message(),
        )

    audio_path: Path | None = None
    try:
        audio_path = (
            recorder
            or AudioRecorder(
                recording_seconds=config.recording_seconds,
                sample_rate=config.sample_rate,
                recorder_command=config.recorder_command,
            )
        ).record_once()
        result = stt_adapter.transcribe_once(audio_path)
    except RecordingError as exc:
        return ListenOnceResult(
            ok=False,
            engine=stt_adapter.engine,
            message=f"마이크 권한 또는 STT 엔진을 확인해주세요. {exc}",
        )
    finally:
        if audio_path is not None:
            audio_path.unlink(missing_ok=True)

    return ListenOnceResult(
        ok=result.ok,
        text=result.text,
        engine=result.engine,
        message=result.message,
    )
