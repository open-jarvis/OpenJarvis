"""Measure cold/warm latency and ten consecutive local voice outputs."""

from __future__ import annotations

import argparse
import array
import hashlib
import io
import json
import math
import sys
import time
import wave
from pathlib import Path

from openjarvis.speech.local_voice import LocalVoiceBackend

_FIRST_SENTENCE = "Guten Abend, Deaa."
_FULL_TEXT = (
    "Guten Abend, Deaa. Alle Systeme sind betriebsbereit. Ich habe deine "
    "aktuellen Aufgaben analysiert und bin bereit, sie auszuführen."
)
_STABILITY_TEXTS = (
    "Stabilitätstest eins. Alle Systeme arbeiten normal.",
    "Stabilitätstest zwei. Die Sprachsynthese ist bereit.",
    "Stabilitätstest drei. Der lokale Dienst antwortet zuverlässig.",
    "Stabilitätstest vier. Die Audioausgabe bleibt kontrolliert.",
    "Stabilitätstest fünf. Der Satz wurde vollständig erzeugt.",
    "Stabilitätstest sechs. Die Stimme bleibt ruhig und klar.",
    "Stabilitätstest sieben. Der Cache wird getrennt geprüft.",
    "Stabilitätstest acht. Die GPU-Verarbeitung ist stabil.",
    "Stabilitätstest neun. Es ist kein Cloud-Dienst beteiligt.",
    "Stabilitätstest zehn. Alle Prüfungen sind abgeschlossen.",
)


def _wav_quality(audio: bytes) -> dict[str, object]:
    with wave.open(io.BytesIO(audio), "rb") as wav_file:
        if wav_file.getsampwidth() != 2:
            return {"pcm_sample_width_bytes": wav_file.getsampwidth()}
        samples = array.array("h", wav_file.readframes(wav_file.getnframes()))
    if sys.byteorder != "little":
        samples.byteswap()
    peak = max((abs(sample) for sample in samples), default=0)
    peak_ratio = peak / 32768.0
    return {
        "pcm_sample_width_bytes": 2,
        "sample_peak_dbfs": (
            round(20.0 * math.log10(peak_ratio), 3) if peak_ratio else None
        ),
        "clipped_samples": sum(abs(sample) >= 32767 for sample in samples),
    }


def _run(
    backend: LocalVoiceBackend, text: str, *, bypass_cache: bool = False
) -> dict[str, object]:
    started = time.perf_counter()
    result = backend.synthesize(
        text, output_format="wav", bypass_cache=bypass_cache
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    return {
        "ok": bool(result.audio),
        "wall_ms": round(wall_ms, 2),
        "audio_seconds": round(result.duration_seconds, 3),
        "audio_sha256": hashlib.sha256(result.audio).hexdigest(),
        **_wav_quality(result.audio),
        **result.metadata,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True, type=Path)
    args = parser.parse_args()
    backend = LocalVoiceBackend(args.runtime_root)
    try:
        status = backend.voice_status()
        cold_first_audio = _run(backend, _FIRST_SENTENCE, bypass_cache=True)
        full_generation = _run(backend, _FULL_TEXT, bypass_cache=True)
        warm_cache = _run(backend, _FIRST_SENTENCE)
        stability = [
            _run(backend, text, bypass_cache=True) for text in _STABILITY_TEXTS
        ]
        report = {
            "schema_version": "1.1",
            "selected_voice_id": status["selected_voice_id"],
            "device": status["worker"]["device"],
            "measurement_semantics": {
                "time_to_first_audio_ready": (
                    "Request start until the first complete sentence WAV is ready."
                ),
                "request_to_playback_event": (
                    "openjarvis:audio-start detail.requestToPlaybackMs records "
                    "request start until HTMLAudioElement onplay in the desktop UI."
                ),
            },
            "time_to_first_audio_ready": cold_first_audio,
            "full_generation": full_generation,
            "warm_cache": warm_cache,
            "stability": stability,
            "stability_passed": len(stability) == 10
            and all(
                bool(row["ok"])
                and row.get("backend") == "chatterbox"
                and not bool(row.get("fallback_used"))
                and int(row.get("clipped_samples", 1)) == 0
                for row in stability
            ),
        }
        destination = args.runtime_root / "voice" / "benchmark.json"
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(destination)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["stability_passed"] else 1
    finally:
        backend.close()


if __name__ == "__main__":
    raise SystemExit(main())
