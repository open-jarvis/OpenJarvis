"""Pluggable local STT adapters for app-mode voice input."""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openjarvis.core.config import VoiceConfig

logger = logging.getLogger(__name__)


SUPPORTED_STT_ENGINES = {
    "web_speech",
    "local_backend",
    "whisper_cpp",
    "faster_whisper",
    "custom",
    "disabled",
}

KOREAN_SETUP_MESSAGE = (
    "로컬 STT 설정이 필요합니다. ~/.openjarvis/config.toml의 [voice]에서 "
    "stt_enabled = true 와 stt_engine을 설정해주세요. 예: whisper_cpp 또는 "
    "faster_whisper."
)


@dataclass(slots=True)
class STTResult:
    """Result from a listen-once STT adapter."""

    ok: bool
    text: str = ""
    engine: str = "disabled"
    message: str = ""


class STTAdapter(ABC):
    """Interface for local listen-once STT adapters."""

    engine: str = "disabled"

    @abstractmethod
    def check_available(self) -> bool:
        """Return whether this STT adapter can transcribe now."""

    @abstractmethod
    def transcribe_once(self, audio_path: Path) -> STTResult:
        """Transcribe one local audio file."""

    @abstractmethod
    def get_setup_message(self) -> str:
        """Return Korean setup guidance for unavailable adapters."""


class DisabledSTTAdapter(STTAdapter):
    engine = "disabled"

    def check_available(self) -> bool:
        return False

    def transcribe_once(self, audio_path: Path) -> STTResult:
        return STTResult(
            ok=False,
            engine=self.engine,
            message=(
                "로컬 STT가 비활성화되어 있습니다. "
                "설정에서 voice.stt_enabled를 켜주세요."
            ),
        )

    def get_setup_message(self) -> str:
        return self.transcribe_once(Path("")).message


class UnsupportedSTTAdapter(STTAdapter):
    def __init__(self, engine: str) -> None:
        self.engine = engine

    def check_available(self) -> bool:
        return False

    def transcribe_once(self, audio_path: Path) -> STTResult:
        return STTResult(
            ok=False,
            engine=self.engine,
            message=f"지원하지 않는 STT 엔진입니다: {self.engine}",
        )

    def get_setup_message(self) -> str:
        return self.transcribe_once(Path("")).message


class WhisperCppSTTAdapter(STTAdapter):
    engine = "whisper_cpp"

    def __init__(
        self,
        *,
        command_path: str,
        model_path: str,
        language: str = "ko",
    ) -> None:
        self.command_path = command_path
        self.model_path = model_path
        self.language = _normalize_language(language)

    def _command(self) -> str:
        return (
            self.command_path
            or shutil.which("whisper-cli")
            or shutil.which("main")
            or ""
        )

    def check_available(self) -> bool:
        command = self._command()
        return bool(command and Path(self.model_path).expanduser().exists())

    def transcribe_once(self, audio_path: Path) -> STTResult:
        command = self._command()
        if not command:
            return STTResult(
                ok=False,
                engine=self.engine,
                message=self.get_setup_message(),
            )
        if not self.model_path:
            return STTResult(
                ok=False,
                engine=self.engine,
                message=self.get_setup_message(),
            )
        model = str(Path(self.model_path).expanduser())
        cmd = [command, "-m", model, "-f", str(audio_path), "-nt"]
        if self.language != "auto":
            cmd.extend(["-l", self.language])
        logger.debug(
            "Running whisper.cpp STT with language option: %s",
            "auto" if self.language == "auto" else f"-l {self.language}",
        )
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return STTResult(
                ok=False,
                engine=self.engine,
                message=f"whisper.cpp 실행에 실패했습니다: {exc}",
            )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()
            return STTResult(
                ok=False,
                engine=self.engine,
                message=detail or "whisper.cpp 음성 인식에 실패했습니다.",
            )
        return STTResult(ok=True, text=proc.stdout.strip(), engine=self.engine)

    def get_setup_message(self) -> str:
        return (
            "로컬 STT 설정이 필요합니다. whisper.cpp의 whisper-cli 경로를 "
            "voice.whisper_cpp_path에, GGUF 모델 경로를 voice.stt_model에 설정해주세요."
        )


class FasterWhisperSTTAdapter(STTAdapter):
    engine = "faster_whisper"

    def __init__(self, *, model: str, language: str = "ko") -> None:
        self.model = model or "base"
        self.language = _normalize_language(language)

    def check_available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            return False
        return True

    def transcribe_once(self, audio_path: Path) -> STTResult:
        try:
            from openjarvis.speech.faster_whisper import FasterWhisperBackend

            backend = FasterWhisperBackend(model_size=self.model, device="auto")
            result = backend.transcribe(
                audio_path.read_bytes(),
                format="wav",
                language=None if self.language == "auto" else self.language,
            )
        except Exception as exc:
            return STTResult(
                ok=False,
                engine=self.engine,
                message=f"faster-whisper 음성 인식에 실패했습니다: {exc}",
            )
        return STTResult(ok=True, text=result.text.strip(), engine=self.engine)

    def get_setup_message(self) -> str:
        return (
            "faster-whisper가 설치되어 있지 않습니다. "
            "필요하면 `uv sync --extra speech`로 설치하세요."
        )


class CustomCommandSTTAdapter(STTAdapter):
    engine = "custom"

    def __init__(self, *, command: str) -> None:
        self.command = command

    def check_available(self) -> bool:
        if not self.command:
            return False
        parts = shlex.split(self.command)
        return bool(parts and shutil.which(parts[0]))

    def transcribe_once(self, audio_path: Path) -> STTResult:
        if not self.command:
            return STTResult(
                ok=False,
                engine=self.engine,
                message=self.get_setup_message(),
            )
        try:
            parts = [
                part.replace("{audio_path}", str(audio_path))
                for part in shlex.split(self.command)
            ]
            if "{audio_path}" not in self.command:
                parts.append(str(audio_path))
            proc = subprocess.run(
                parts,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return STTResult(
                ok=False,
                engine=self.engine,
                message=f"custom STT 실행 실패: {exc}",
            )
        if proc.returncode != 0:
            return STTResult(
                ok=False,
                engine=self.engine,
                message=(
                    (proc.stderr or proc.stdout).strip()
                    or "custom STT 실행에 실패했습니다."
                ),
            )
        return STTResult(ok=True, text=proc.stdout.strip(), engine=self.engine)

    def get_setup_message(self) -> str:
        return (
            "voice.custom_command에 로컬 STT 명령을 설정해주세요. "
            "{audio_path}를 사용할 수 있습니다."
        )


def create_stt_adapter(config: "VoiceConfig") -> STTAdapter:
    """Create a local STT adapter from voice config."""

    if not config.stt_enabled:
        return DisabledSTTAdapter()

    engine = (config.stt_engine or "disabled").strip()
    if engine == "local_backend":
        engine = (
            "whisper_cpp"
            if config.whisper_cpp_path or config.stt_model
            else "faster_whisper"
        )
    if engine == "web_speech":
        return UnsupportedSTTAdapter(engine)
    if engine == "whisper_cpp":
        return WhisperCppSTTAdapter(
            command_path=config.whisper_cpp_path,
            model_path=config.stt_model,
            language=_config_language(config),
        )
    if engine == "faster_whisper":
        return FasterWhisperSTTAdapter(
            model=config.stt_model,
            language=_config_language(config),
        )
    if engine == "custom":
        return CustomCommandSTTAdapter(command=config.custom_command)
    if engine == "disabled":
        return DisabledSTTAdapter()
    return UnsupportedSTTAdapter(engine)


def _normalize_language(language: str) -> str:
    value = (language or "ko").strip().lower()
    return value or "ko"


def _config_language(config: "VoiceConfig") -> str:
    return _normalize_language(config.stt_language or config.language or "ko")
