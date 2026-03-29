"""Text-to-speech backends with interruption support.

Priority chain:
  1. PiperTTS  — local ONNX, fast, high quality (requires piper-tts + a voice model)
  2. MacOSSayTTS — wraps the built-in `say` command (macOS only, no install needed)
  3. SilentTTS  — print-only fallback (always works)

Usage
-----
from openjarvis.voice.tts import build_tts
tts = build_tts()        # auto-selects best available
tts.speak("Hey there")   # plays audio
tts.stop()               # interrupts mid-sentence
"""

from __future__ import annotations

import io
import logging
import subprocess
import sys
import threading
from typing import Callable, Optional

from openjarvis.voice._stubs import TTSBackend

logger = logging.getLogger(__name__)


# ── Piper TTS ─────────────────────────────────────────────────────────────────

class PiperTTS(TTSBackend):
    """Local neural TTS via piper-tts ONNX.

    Requires:
        uv pip install piper-tts
    And a voice model (.onnx + .onnx.json), e.g.:
        python -m piper --download-dir ~/.local/share/piper-tts en_US-lessac-medium

    If model_path is None we try ~/.local/share/piper-tts/en_US-lessac-medium.onnx.
    """

    DEFAULT_MODEL_DIRS = [
        "~/.local/share/piper-tts",
        "~/.piper",
        "/usr/share/piper-tts",
    ]
    DEFAULT_VOICE = "en_US-lessac-medium"

    def __init__(self, model_path: Optional[str] = None) -> None:
        self._model_path = model_path or self._find_model()
        self._voice = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._playing = False
        self._playback_thread: Optional[threading.Thread] = None

    def _find_model(self) -> Optional[str]:
        import pathlib
        for d in self.DEFAULT_MODEL_DIRS:
            base = pathlib.Path(d).expanduser()
            for candidate in base.glob(f"{self.DEFAULT_VOICE}.onnx"):
                return str(candidate)
        return None

    def _load(self) -> bool:
        if self._voice is not None:
            return True
        if not self._model_path:
            logger.warning(
                "No piper voice model found. Download with:\n"
                "  python -m piper --download-dir ~/.local/share/piper-tts en_US-lessac-medium"
            )
            return False
        try:
            from piper import PiperVoice
            self._voice = PiperVoice.load(self._model_path)
            logger.info("Piper TTS loaded: %s", self._model_path)
            return True
        except ImportError:
            logger.warning("piper-tts not installed. Run: uv pip install piper-tts")
            return False
        except Exception as exc:
            logger.warning("Piper TTS load failed: %s", exc)
            return False

    def speak(self, text: str, *, on_word: Optional[Callable[[str], None]] = None) -> None:
        if not self._load() or not self._voice:
            return
        try:
            import sounddevice as sd
        except ImportError:
            logger.warning("sounddevice not installed — cannot play audio")
            return

        self._stop_event.clear()

        try:
            import wave
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                self._voice.synthesize(text, wf)
            buf.seek(0)
            with wave.open(buf, "rb") as wf:
                sample_rate = wf.getframerate()
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)

            import numpy as np
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

            CHUNK = 4096
            with self._lock:
                self._playing = True
            i = 0
            while i < len(audio) and not self._stop_event.is_set():
                chunk = audio[i : i + CHUNK]
                sd.play(chunk, samplerate=sample_rate, blocking=True)
                i += CHUNK
        except Exception as exc:
            logger.warning("Piper TTS speak error: %s", exc)
        finally:
            with self._lock:
                self._playing = False

    def stop(self) -> None:
        self._stop_event.set()
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass

    def is_speaking(self) -> bool:
        with self._lock:
            return self._playing


# ── macOS say ─────────────────────────────────────────────────────────────────

class MacOSSayTTS(TTSBackend):
    """Wraps macOS `say` command. Zero dependencies, decent quality."""

    def __init__(self, voice: str = "Samantha", rate: int = 185) -> None:
        self._voice = voice
        self._rate = rate
        self._proc: Optional[subprocess.Popen] = None  # type: ignore[type-arg]
        self._lock = threading.Lock()

    def speak(self, text: str, *, on_word: Optional[Callable[[str], None]] = None) -> None:
        if sys.platform != "darwin":
            logger.warning("MacOSSayTTS only works on macOS")
            return
        self.stop()
        cmd = ["say", "-v", self._voice, "-r", str(self._rate), text]
        with self._lock:
            self._proc = subprocess.Popen(cmd)
        self._proc.wait()
        with self._lock:
            self._proc = None

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        with self._lock:
            self._proc = None

    def is_speaking(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None


# ── silent fallback ───────────────────────────────────────────────────────────

class SilentTTS(TTSBackend):
    """No audio — just prints to stdout. Always works."""

    def speak(self, text: str, *, on_word: Optional[Callable[[str], None]] = None) -> None:
        print(f"[TTS] {text}")

    def stop(self) -> None:
        pass

    def is_speaking(self) -> bool:
        return False


# ── factory ───────────────────────────────────────────────────────────────────

def build_tts(prefer: Optional[str] = None) -> TTSBackend:
    """Auto-select the best available TTS backend.

    prefer: 'piper' | 'say' | 'silent'
    """
    order = [prefer] if prefer else ["piper", "say", "silent"]
    for name in order:
        if name == "piper":
            t = PiperTTS()
            if t._load():
                logger.info("TTS: using Piper")
                return t
        elif name == "say" and sys.platform == "darwin":
            # Verify `say` exists
            if subprocess.run(["which", "say"], capture_output=True).returncode == 0:
                logger.info("TTS: using macOS say")
                return MacOSSayTTS()
        elif name == "silent":
            logger.info("TTS: using silent (text-only) fallback")
            return SilentTTS()
    return SilentTTS()


__all__ = ["MacOSSayTTS", "PiperTTS", "SilentTTS", "TTSBackend", "build_tts"]
