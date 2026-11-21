"""Windows SAPI text-to-speech backend (no extra Python packages).

Uses ``System.Speech.Synthesis.SpeechSynthesizer`` from Windows PowerShell,
which ships with Windows. This gives voice output on machines where the
Kokoro/PyTorch stack is too heavy (or blocked by Smart App Control), without
adding a cloud dependency.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from openjarvis.core.registry import TTSRegistry
from openjarvis.speech.tts import TTSBackend, TTSResult

logger = logging.getLogger(__name__)

_SAMPLE_RATE = 22050

_SYNTH_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($env:JARVIS_TTS_VOICE) {
        try { $synth.SelectVoice($env:JARVIS_TTS_VOICE) } catch { }
    }
    $synth.Rate = [int]$env:JARVIS_TTS_RATE
    $synth.SetOutputToWaveFile($env:JARVIS_TTS_WAV)
    $text = [IO.File]::ReadAllText($env:JARVIS_TTS_TEXT, [Text.Encoding]::UTF8)
    $synth.Speak($text)
} finally {
    $synth.Dispose()
}
"""

_VOICES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.GetInstalledVoices() | ForEach-Object {
        if ($_.Enabled) { $_.VoiceInfo.Name }
    }
} finally {
    $synth.Dispose()
}
"""


def _powershell() -> Optional[str]:
    """Return Windows PowerShell (System.Speech is not in PowerShell 7)."""
    return shutil.which("powershell") or shutil.which("powershell.exe")


@TTSRegistry.register("windows")
class WindowsTTSBackend(TTSBackend):
    """Local TTS through the Windows Speech API."""

    backend_id = "windows"

    def __init__(self) -> None:
        self._voice_cache: Optional[List[str]] = None
        self._health_cache: Optional[bool] = None

    def _run(self, script: str, env: Dict[str, str], timeout: float) -> subprocess.CompletedProcess:
        shell = _powershell()
        if shell is None:
            raise RuntimeError("Windows PowerShell is not available")
        return subprocess.run(  # noqa: S603 - fixed executable, static script
            [shell, "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def health(self) -> bool:
        if os.name != "nt":
            return False
        if self._health_cache is not None:
            return self._health_cache
        try:
            result = self._run(
                "Add-Type -AssemblyName System.Speech; 'ok'", {}, timeout=20.0
            )
            self._health_cache = result.returncode == 0 and "ok" in result.stdout
        except (OSError, subprocess.SubprocessError):
            self._health_cache = False
        return self._health_cache

    def available_voices(self) -> List[str]:
        if self._voice_cache is not None:
            return self._voice_cache
        try:
            result = self._run(_VOICES_SCRIPT, {}, timeout=20.0)
        except (OSError, subprocess.SubprocessError):
            self._voice_cache = []
            return self._voice_cache
        if result.returncode != 0:
            self._voice_cache = []
            return self._voice_cache
        self._voice_cache = [
            line.strip() for line in result.stdout.splitlines() if line.strip()
        ]
        return self._voice_cache

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "mp3",
    ) -> TTSResult:
        if not self.health():
            raise RuntimeError(
                "Windows TTS is unavailable: System.Speech could not be loaded "
                "through Windows PowerShell."
            )
        text = (text or "").strip()
        if not text:
            raise ValueError("Cannot synthesize empty text")

        # SAPI rate is -10..10, where 0 is normal speed.
        rate = max(-10, min(10, int(round((speed - 1.0) * 10))))

        with tempfile.TemporaryDirectory(prefix="jarvis-tts-") as tmp:
            tmp_path = Path(tmp)
            text_path = tmp_path / "text.txt"
            wav_path = tmp_path / "speech.wav"
            text_path.write_text(text, encoding="utf-8")
            env = {
                "JARVIS_TTS_TEXT": str(text_path),
                "JARVIS_TTS_WAV": str(wav_path),
                "JARVIS_TTS_RATE": str(rate),
                "JARVIS_TTS_VOICE": voice_id or "",
            }
            result = self._run(_SYNTH_SCRIPT, env, timeout=120.0)
            if result.returncode != 0 or not wav_path.exists():
                detail = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(f"Windows TTS synthesis failed: {detail[:400]}")
            audio = wav_path.read_bytes()

        # SAPI only emits WAV; the format argument is kept for interface
        # compatibility and reported accurately in the result.
        return TTSResult(
            audio=audio,
            format="wav",
            duration_seconds=0.0,
            voice_id=voice_id,
            sample_rate=_SAMPLE_RATE,
            metadata={"engine": "windows-sapi", "requested_format": output_format},
        )


__all__ = ["WindowsTTSBackend"]
