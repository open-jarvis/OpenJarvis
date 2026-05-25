"""Local microphone recording helpers for listen-once STT."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

HOMEBREW_REC_PATH = "/opt/homebrew/bin/rec"


class RecordingError(RuntimeError):
    """Raised when the local microphone cannot be recorded."""


@dataclass(slots=True)
class AudioRecorder:
    """Record a short local WAV clip with sox/rec."""

    recording_seconds: int = 4
    sample_rate: int = 16000
    recorder_command: str = ""

    def _resolve_recorder(self) -> str:
        if self.recorder_command:
            command = Path(self.recorder_command).expanduser()
            return str(command) if command.exists() else ""
        if Path(HOMEBREW_REC_PATH).exists():
            return HOMEBREW_REC_PATH
        return shutil.which("rec") or ""

    def record_once(self) -> Path:
        recorder = self._resolve_recorder()
        if not recorder:
            raise RecordingError(
                "로컬 녹음 명령 rec를 찾을 수 없습니다. "
                "sox를 설치하거나 voice.recorder_command에 rec 경로를 설정해주세요."
            )

        seconds = max(1, min(int(self.recording_seconds), 30))
        sample_rate = max(8000, int(self.sample_rate))
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_path = Path(tmp.name)
        tmp.close()
        try:
            proc = subprocess.run(
                [
                    recorder,
                    "-q",
                    "-r",
                    str(sample_rate),
                    "-c",
                    "1",
                    "-b",
                    "16",
                    str(tmp_path),
                    "trim",
                    "0",
                    str(seconds),
                ],
                capture_output=True,
                text=True,
                timeout=seconds + 10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            tmp_path.unlink(missing_ok=True)
            raise RecordingError(f"마이크 녹음에 실패했습니다: {exc}") from exc
        if proc.returncode != 0:
            tmp_path.unlink(missing_ok=True)
            detail = (proc.stderr or proc.stdout).strip()
            raise RecordingError(detail or "마이크 권한 또는 입력 장치를 확인해주세요.")
        return tmp_path
