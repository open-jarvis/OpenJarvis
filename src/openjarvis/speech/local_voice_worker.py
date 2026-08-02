"""Isolated Chatterbox/Piper worker using a JSON-lines stdio protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import wave
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from openjarvis.speech.voice_config import PROFILE_BY_ID, load_voice_config

_VOICE_SCHEMA = "voice-v7-chatterbox-5de7a54a-seeded-lufs19-peak1db-timeout"
_PEAK_HEADROOM = 10 ** (-1.0 / 20.0)


class _GpuSampler:
    """Best-effort, credential-free NVIDIA utilization sampler."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.utilization: list[float] = []
        self.memory_mb: list[float] = []

    def start(self) -> None:
        if shutil.which("nvidia-smi") is None:
            return
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)

    def _sample(self) -> None:
        while not self._stop.is_set():
            try:
                result = subprocess.run(  # noqa: S603
                    [
                        "nvidia-smi",
                        "--query-gpu=utilization.gpu,memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                    creationflags=(
                        getattr(subprocess, "CREATE_NO_WINDOW", 0)
                        if os.name == "nt"
                        else 0
                    ),
                )
                if result.returncode == 0 and result.stdout.strip():
                    utilization, memory = result.stdout.splitlines()[0].split(",")[:2]
                    self.utilization.append(float(utilization.strip()))
                    self.memory_mb.append(float(memory.strip()))
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
            self._stop.wait(0.4)

    def metrics(self) -> dict[str, float]:
        return {
            "gpu_utilization_avg_percent": (
                sum(self.utilization) / len(self.utilization)
                if self.utilization
                else 0.0
            ),
            "gpu_utilization_peak_percent": max(self.utilization, default=0.0),
            "gpu_total_memory_peak_mb": max(self.memory_mb, default=0.0),
        }


class VoiceWorker:
    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = runtime_root.resolve(strict=True)
        self.voice_root = self.runtime_root / "voice"
        self.config_path = self.voice_root / "voice-config.json"
        self.cache_root = self.voice_root / "cache"
        self.audition_root = self.voice_root / "auditions"
        self.model_root = self.voice_root / "models"
        for path in (self.cache_root, self.audition_root, self.model_root):
            path.mkdir(parents=True, exist_ok=True)
        load_voice_config(self.config_path)
        self._chatterbox: Any = None
        self._piper: Any = None

    def health(self) -> dict[str, Any]:
        import importlib.util

        import torch

        return {
            "ok": True,
            "chatterbox": importlib.util.find_spec("chatterbox") is not None,
            "piper": importlib.util.find_spec("piper") is not None,
            "cuda": bool(torch.cuda.is_available()),
            "device": (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
            ),
            "chatterbox_loaded": self._chatterbox is not None,
            "piper_loaded": self._piper is not None,
        }

    def warmup(self) -> dict[str, Any]:
        response = self.health()
        primary_error = None
        try:
            self._load_chatterbox()
        except Exception as exc:
            primary_error = type(exc).__name__
        try:
            self._load_piper()
            piper_ready = True
        except Exception:
            piper_ready = False
        return {
            **response,
            "chatterbox_loaded": self._chatterbox is not None,
            "piper_loaded": piper_ready,
            "primary_error": primary_error,
        }

    def _load_chatterbox(self) -> Any:
        if self._chatterbox is None:
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            if not torch.cuda.is_available():
                raise RuntimeError("ChatterboxCudaUnavailable")
            self._chatterbox = ChatterboxMultilingualTTS.from_pretrained(
                device="cuda", t3_model="v3"
            )
        return self._chatterbox

    def _load_piper(self) -> Any:
        if self._piper is None:
            from piper.voice import PiperVoice

            model = self.model_root / "piper" / "de_DE-thorsten-high.onnx"
            config = model.with_suffix(".onnx.json")
            if not model.is_file() or not config.is_file():
                raise RuntimeError("PiperModelUnavailable")
            self._piper = PiperVoice.load(model, config_path=config, use_cuda=False)
        return self._piper

    @staticmethod
    def _postprocess(samples: Any, sample_rate: int, pitch: float, speed: float) -> Any:
        import librosa
        import numpy as np
        import pyloudnorm as pyln

        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        audio = np.nan_to_num(audio, copy=False)
        if pitch:
            audio = librosa.effects.pitch_shift(
                audio, sr=sample_rate, n_steps=float(pitch), res_type="soxr_hq"
            )
        if abs(speed - 1.0) > 0.001:
            audio = librosa.effects.time_stretch(audio, rate=float(speed))
        if audio.size >= sample_rate // 2:
            meter = pyln.Meter(sample_rate)
            loudness = float(meter.integrated_loudness(audio))
            if np.isfinite(loudness):
                requested_gain = 10 ** ((-19.0 - loudness) / 20.0)
                peak = float(np.max(np.abs(audio))) if audio.size else 0.0
                peak_safe_gain = _PEAK_HEADROOM / peak if peak else requested_gain
                audio = audio * min(requested_gain, peak_safe_gain)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > _PEAK_HEADROOM:
            audio = audio * (_PEAK_HEADROOM / peak)
        return audio.astype(np.float32, copy=False)

    def _generate_chatterbox(
        self, text: str, profile: Any, path: Path, speed: float
    ) -> int:
        import soundfile as sf
        import torch

        model = self._load_chatterbox()
        torch.manual_seed(profile.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(profile.seed)
        wav = model.generate(
            text,
            language_id="de",
            audio_prompt_path=None,
            exaggeration=profile.exaggeration,
            cfg_weight=profile.cfg_weight,
            temperature=profile.temperature,
            repetition_penalty=1.2,
            min_p=0.05,
            top_p=1.0,
        )
        samples = wav.squeeze().detach().cpu().numpy()
        samples = self._postprocess(
            samples,
            int(model.sr),
            profile.pitch_semitones,
            profile.speed * speed,
        )
        sf.write(path, samples, int(model.sr), subtype="PCM_16")
        return int(model.sr)

    def _generate_piper(self, text: str, profile: Any, path: Path, speed: float) -> int:
        from piper.config import SynthesisConfig

        voice = self._load_piper()
        raw_path = path.with_name(f".{path.stem}.piper.wav")
        try:
            with wave.open(str(raw_path), "wb") as wav_file:
                voice.synthesize_wav(
                    text,
                    wav_file,
                    syn_config=SynthesisConfig(
                        length_scale=1.0 / (profile.speed * speed),
                        noise_scale=0.50,
                        noise_w_scale=0.72,
                        normalize_audio=True,
                    ),
                )
            import soundfile as sf

            samples, sample_rate = sf.read(raw_path, dtype="float32")
            samples = self._postprocess(
                samples, int(sample_rate), profile.pitch_semitones, 1.0
            )
            sf.write(path, samples, int(sample_rate), subtype="PCM_16")
            return int(sample_rate)
        finally:
            raw_path.unlink(missing_ok=True)

    @staticmethod
    def _wav_duration(path: Path) -> tuple[float, int]:
        with wave.open(str(path), "rb") as wav_file:
            rate = wav_file.getframerate()
            return wav_file.getnframes() / float(rate), rate

    def synthesize(self, request: dict[str, Any]) -> dict[str, Any]:
        import psutil
        import torch

        text = str(request.get("text", "")).strip()
        voice_id = str(request.get("voice_id", ""))
        if not text or len(text) > 4000 or voice_id not in PROFILE_BY_ID:
            raise ValueError("InvalidSynthesisRequest")
        profile = PROFILE_BY_ID[voice_id]
        speed = max(0.75, min(float(request.get("speed_multiplier", 1.0)), 1.25))
        backend_override = str(request.get("backend_override", "")).strip()
        if backend_override not in {"", "piper"}:
            raise ValueError("InvalidBackendOverride")
        fallback_reason = str(request.get("primary_error", "")).strip() or None
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "text": text,
                    "voice_id": voice_id,
                    "speed": speed,
                    "pitch": profile.pitch_semitones,
                    "profile_speed": profile.speed,
                    "exaggeration": profile.exaggeration,
                    "cfg_weight": profile.cfg_weight,
                    "temperature": profile.temperature,
                    "seed": profile.seed,
                    "backend_override": backend_override or None,
                    "fallback_reason": fallback_reason,
                    "schema": _VOICE_SCHEMA,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        if bool(request.get("audition")):
            destination = self.audition_root / f"{voice_id}.wav"
        else:
            destination = self.cache_root / f"{cache_key}.wav"
        bypass_cache = bool(request.get("bypass_cache"))
        metadata_path = destination.with_suffix(".json")
        cached_metadata: dict[str, Any] = {}
        if metadata_path.is_file():
            cached_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        transient_primary_fallback = bool(cached_metadata.get("fallback_used")) and (
            profile.backend == "chatterbox" and not backend_override
        )
        if (
            destination.is_file()
            and cached_metadata.get("schema") == _VOICE_SCHEMA
            and not transient_primary_fallback
            and not bypass_cache
        ):
            duration, sample_rate = self._wav_duration(destination)
            return {
                "ok": True,
                "audio_path": str(destination),
                "backend": cached_metadata.get("backend", profile.backend),
                "fallback_used": bool(cached_metadata.get("fallback_used", False)),
                "primary_error": cached_metadata.get("primary_error"),
                "cache_hit": True,
                "duration_seconds": duration,
                "sample_rate": sample_rate,
                "synthesis_ms": 0.0,
                "cpu_percent": 0.0,
                "gpu_peak_vram_mb": 0.0,
                "gpu_utilization_avg_percent": 0.0,
                "gpu_utilization_peak_percent": 0.0,
                "gpu_total_memory_peak_mb": 0.0,
                "system_cpu_percent": 0.0,
            }

        started = time.perf_counter()
        process = psutil.Process()
        cpu_before = sum(process.cpu_times()[:2])
        psutil.cpu_percent(interval=None)
        gpu_sampler = _GpuSampler()
        gpu_sampler.start()
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
        temporary = destination.with_name(f".{destination.name}.{os.getpid()}.tmp.wav")
        temporary_metadata = metadata_path.with_name(
            f".{metadata_path.name}.{os.getpid()}.tmp"
        )
        backend = backend_override or profile.backend
        fallback_used = bool(
            profile.backend == "chatterbox" and backend == "piper"
        )
        primary_error = fallback_reason if fallback_used else None
        try:
            if backend == "chatterbox":
                try:
                    sample_rate = self._generate_chatterbox(
                        text, profile, temporary, speed
                    )
                except Exception as exc:
                    backend = "piper"
                    fallback_used = True
                    primary_error = type(exc).__name__
                    sample_rate = self._generate_piper(text, profile, temporary, speed)
            else:
                sample_rate = self._generate_piper(text, profile, temporary, speed)
            temporary.replace(destination)
            temporary_metadata.write_text(
                json.dumps(
                    {
                        "backend": backend,
                        "fallback_used": fallback_used,
                        "primary_error": primary_error,
                        "backend_override": backend_override or None,
                        "schema": _VOICE_SCHEMA,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary_metadata.replace(metadata_path)
        finally:
            gpu_sampler.stop()
            temporary.unlink(missing_ok=True)
            temporary_metadata.unlink(missing_ok=True)
        elapsed = max(time.perf_counter() - started, 0.001)
        cpu_after = sum(process.cpu_times()[:2])
        duration, sample_rate = self._wav_duration(destination)
        peak_vram = (
            float(torch.cuda.max_memory_allocated()) / (1024 * 1024)
            if torch.cuda.is_available()
            else 0.0
        )
        return {
            "ok": True,
            "audio_path": str(destination),
            "backend": backend,
            "fallback_used": fallback_used,
            "primary_error": primary_error,
            "cache_hit": False,
            "duration_seconds": duration,
            "sample_rate": sample_rate,
            "synthesis_ms": elapsed * 1000.0,
            "cpu_percent": max(0.0, (cpu_after - cpu_before) / elapsed * 100.0),
            "gpu_peak_vram_mb": peak_vram,
            "system_cpu_percent": float(psutil.cpu_percent(interval=None)),
            **gpu_sampler.metrics(),
        }


def _serve(runtime_root: Path) -> int:
    worker = VoiceWorker(runtime_root)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            command = request.get("command")
            if command == "shutdown":
                print('{"ok":true}', flush=True)
                return 0
            with redirect_stdout(sys.stderr):
                if command == "health":
                    response = worker.health()
                elif command == "warmup":
                    response = worker.warmup()
                elif command == "synthesize":
                    response = worker.synthesize(request)
                else:
                    raise ValueError("UnknownWorkerCommand")
        except Exception as exc:
            response = {"ok": False, "error": type(exc).__name__}
        print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True, type=Path)
    args = parser.parse_args()
    return _serve(args.runtime_root)


if __name__ == "__main__":
    raise SystemExit(main())
