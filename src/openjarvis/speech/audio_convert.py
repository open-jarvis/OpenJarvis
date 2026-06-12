"""Convert uploaded browser audio to 16 kHz mono WAV via ffmpeg."""

from __future__ import annotations

import io
import logging
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

logger = logging.getLogger(__name__)

# Resolve at call time — serve may start before ffmpeg is on PATH (common on Windows).
_FFMPEG_CACHED: str | None = None


def _resolve_ffmpeg() -> str | None:
    global _FFMPEG_CACHED
    if _FFMPEG_CACHED and Path(_FFMPEG_CACHED).is_file():
        return _FFMPEG_CACHED
    found = shutil.which("ffmpeg")
    if found:
        _FFMPEG_CACHED = found
        return found
    for candidate in (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Microsoft/WinGet/Links/ffmpeg.exe",
        Path(os.environ.get("ProgramFiles", "")) / "ffmpeg/bin/ffmpeg.exe",
    ):
        if candidate.is_file():
            _FFMPEG_CACHED = str(candidate)
            return _FFMPEG_CACHED
    # WinGet installs ffmpeg under Packages without always adding Links.
    winget_packages = (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
    )
    if winget_packages.is_dir():
        for exe in sorted(winget_packages.glob("**/ffmpeg.exe")):
            if exe.is_file():
                _FFMPEG_CACHED = str(exe)
                return _FFMPEG_CACHED
    return None


def ffmpeg_available() -> bool:
    return _resolve_ffmpeg() is not None


def wav_rms(wav_bytes: bytes) -> float | None:
    """Return normalized RMS (0–1) of 16-bit PCM WAV, or None if unreadable."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            nchannels = wf.getnchannels()
            nframes = wf.getnframes()
            if nframes == 0:
                return 0.0
            raw = wf.readframes(nframes)
            count = nframes * nchannels
            samples = struct.unpack(f"<{count}h", raw)
            if nchannels > 1:
                samples = [
                    sum(samples[i : i + nchannels]) / nchannels
                    for i in range(0, count, nchannels)
                ]
            sum_sq = sum(s * s for s in samples)
            rms = math.sqrt(sum_sq / len(samples))
            return rms / 32768.0
    except Exception:
        return None


def is_silent_wav(wav_bytes: bytes, *, threshold: float = 0.001) -> bool:
    """True when WAV energy is below threshold (mic silence / no speech)."""
    rms = wav_rms(wav_bytes)
    return rms is not None and rms < threshold


def convert_to_wav(audio_bytes: bytes, input_ext: str) -> bytes | None:
    """Return 16 kHz mono PCM WAV bytes, or None if conversion fails."""
    ffmpeg = _resolve_ffmpeg()
    if not ffmpeg or not audio_bytes:
        return None

    ext = input_ext.lstrip(".") or "webm"
    in_path = out_path = ""
    try:
        fd, in_path = tempfile.mkstemp(suffix=f".{ext}")
        os.close(fd)
        Path(in_path).write_bytes(audio_bytes)
        out_fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(out_fd)

        proc = subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-y",
                "-i",
                in_path,
                "-af",
                "highpass=f=80,volume=12.0,dynaudnorm",
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                out_path,
            ],
            capture_output=True,
            timeout=60,
        )
        if proc.returncode != 0:
            logger.debug(
                "ffmpeg failed (%s): %s",
                proc.returncode,
                proc.stderr.decode(errors="replace")[:500],
            )
            return None
        return Path(out_path).read_bytes()
    except Exception:
        logger.debug("ffmpeg conversion error", exc_info=True)
        return None
    finally:
        for p in (in_path, out_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass
