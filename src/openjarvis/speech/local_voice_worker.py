"""Isolated ElevenLabs/Chatterbox/Piper worker using JSON-lines stdio."""

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
import urllib.error
import urllib.parse
import urllib.request
import wave
from collections import OrderedDict
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from openjarvis.speech.voice_config import (
    PROFILE_BY_ID,
    VOICE_CACHE_SCHEMA,
    VOICE_REFERENCE_ASSETS,
    ElevenLabsUsageLimit,
    load_voice_config,
    load_elevenlabs_usage,
    reserve_elevenlabs_usage,
)

_PEAK_HEADROOM = 10 ** (-1.0 / 20.0)
_ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
_ELEVENLABS_TIMEOUT_SECONDS = 15.0
_ELEVENLABS_MAX_AUDIO_BYTES = 16 * 1024 * 1024
_ELEVENLABS_OUTPUT_FORMAT = "mp3_44100_128"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, code, msg, headers, newurl
        raise ElevenLabsUnavailable("ElevenLabsRedirectRejected")


class ElevenLabsNotConfigured(RuntimeError):
    pass


class ElevenLabsInvalidVoice(RuntimeError):
    pass


class ElevenLabsAuthenticationFailed(RuntimeError):
    pass


class ElevenLabsRateLimited(RuntimeError):
    pass


class ElevenLabsUnavailable(RuntimeError):
    pass


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
        self.reference_root = self.model_root / "references"
        for path in (
            self.cache_root,
            self.audition_root,
            self.model_root,
            self.reference_root,
        ):
            path.mkdir(parents=True, exist_ok=True)
        load_voice_config(self.config_path)
        self._chatterbox: Any = None
        self._chatterbox_conditionals: dict[str, Any] = {}
        self._piper: Any = None
        self._response_usage: OrderedDict[str, int] = OrderedDict()

    def health(self) -> dict[str, Any]:
        import importlib.util

        import torch

        config = load_voice_config(self.config_path)
        api_key_set = bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())
        voice_id_set = bool(str(config.get("elevenlabs_voice_id") or "").strip())
        return {
            "ok": True,
            "elevenlabs": True,
            "elevenlabs_api_key_set": api_key_set,
            "elevenlabs_voice_id_set": voice_id_set,
            "elevenlabs_configured": api_key_set and voice_id_set,
            "elevenlabs_usage": load_elevenlabs_usage(self.voice_root),
            "chatterbox": importlib.util.find_spec("chatterbox") is not None,
            "piper": importlib.util.find_spec("piper") is not None,
            "cuda": bool(torch.cuda.is_available()),
            "device": (
                torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
            ),
            "chatterbox_loaded": self._chatterbox is not None,
            "reference_profiles_loaded": len(self._chatterbox_conditionals),
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
            "reference_profiles_loaded": len(self._chatterbox_conditionals),
            "piper_loaded": piper_ready,
            "primary_error": primary_error,
        }

    @staticmethod
    def _api_key() -> str:
        key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if not key:
            raise ElevenLabsNotConfigured("ElevenLabsNotConfigured")
        return key

    @staticmethod
    def _voice_id(config: dict[str, Any]) -> str:
        voice_id = str(config.get("elevenlabs_voice_id") or "").strip()
        if not voice_id:
            raise ElevenLabsNotConfigured("ElevenLabsVoiceNotConfigured")
        if len(voice_id) > 128 or not all(
            character.isalnum() or character in {"_", "-"}
            for character in voice_id
        ):
            raise ElevenLabsInvalidVoice("ElevenLabsInvalidVoice")
        return voice_id

    @staticmethod
    def _url_request(
        request: urllib.request.Request,
        *,
        timeout: float = _ELEVENLABS_TIMEOUT_SECONDS,
    ) -> bytes:
        try:
            opener = urllib.request.build_opener(_NoRedirectHandler())
            with opener.open(request, timeout=timeout) as response:  # noqa: S310
                content_type = str(response.headers.get("Content-Type", ""))
                body = response.read(_ELEVENLABS_MAX_AUDIO_BYTES + 1)
                if len(body) > _ELEVENLABS_MAX_AUDIO_BYTES:
                    raise ElevenLabsUnavailable("ElevenLabsResponseTooLarge")
                if request.method == "POST" and not content_type.startswith("audio/"):
                    raise ElevenLabsUnavailable("ElevenLabsInvalidContentType")
                return body
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise ElevenLabsAuthenticationFailed(
                    "ElevenLabsAuthenticationFailed"
                ) from None
            if exc.code in {404, 422}:
                raise ElevenLabsInvalidVoice("ElevenLabsInvalidVoice") from None
            if exc.code == 429:
                raise ElevenLabsRateLimited("ElevenLabsRateLimited") from None
            raise ElevenLabsUnavailable(f"ElevenLabsHttp{exc.code}") from None
        except (TimeoutError, urllib.error.URLError, OSError):
            raise ElevenLabsUnavailable("ElevenLabsUnavailable") from None

    def list_elevenlabs_voices(self) -> dict[str, Any]:
        """Return secret-free voice metadata from the official v2 list endpoint."""

        key = self._api_key()
        query = urllib.parse.urlencode(
            {"page_size": 100, "include_total_count": "false", "sort": "name"}
        )
        request = urllib.request.Request(
            f"{_ELEVENLABS_BASE_URL}/v2/voices?{query}",
            headers={"xi-api-key": key, "Accept": "application/json"},
            method="GET",
        )
        raw = self._url_request(request)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ElevenLabsUnavailable("ElevenLabsInvalidResponse") from exc
        voices = []
        for item in payload.get("voices", []):
            if not isinstance(item, dict):
                continue
            voice_id = str(item.get("voice_id") or "")
            name = str(item.get("name") or "")
            if not voice_id or not name:
                continue
            labels = item.get("labels") if isinstance(item.get("labels"), dict) else {}
            verified = item.get("verified_languages")
            voices.append(
                {
                    "voice_id": voice_id,
                    "name": name[:160],
                    "category": str(item.get("category") or "")[:80],
                    "description": str(item.get("description") or "")[:500],
                    "labels": {
                        str(key)[:80]: str(value)[:160]
                        for key, value in labels.items()
                    },
                    "verified_languages": [
                        {
                            "language": str(language.get("language") or "")[:16],
                            "locale": str(language.get("locale") or "")[:32],
                            "accent": str(language.get("accent") or "")[:80],
                        }
                        for language in verified or []
                        if isinstance(language, dict)
                    ],
                }
            )
        return {"ok": True, "voices": voices}

    def validate_elevenlabs_voice(self, voice_id: str) -> dict[str, Any]:
        key = self._api_key()
        safe_id = self._voice_id({"elevenlabs_voice_id": voice_id})
        request = urllib.request.Request(
            f"{_ELEVENLABS_BASE_URL}/v1/voices/{urllib.parse.quote(safe_id)}",
            headers={"xi-api-key": key, "Accept": "application/json"},
            method="GET",
        )
        raw = self._url_request(request)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ElevenLabsUnavailable("ElevenLabsInvalidResponse") from exc
        if str(payload.get("voice_id") or "") != safe_id:
            raise ElevenLabsInvalidVoice("ElevenLabsInvalidVoice")
        return {"ok": True, "voice_id": safe_id, "name": str(payload.get("name") or "")[:160]}

    def _verified_reference_path(self, voice_id: str) -> Path:
        filename, expected_sha256 = VOICE_REFERENCE_ASSETS[voice_id]
        root = self.reference_root.resolve(strict=True)
        path = (root / filename).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise RuntimeError("VoiceReferenceUnavailable")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise RuntimeError("VoiceReferenceHashMismatch")
        return path

    def _prepare_chatterbox_conditionals(self, model: Any) -> None:
        if len(self._chatterbox_conditionals) == len(VOICE_REFERENCE_ASSETS):
            return
        prepared: dict[str, Any] = {}
        for voice_id in VOICE_REFERENCE_ASSETS:
            profile = PROFILE_BY_ID[voice_id]
            reference = self._verified_reference_path(voice_id)
            model.prepare_conditionals(
                str(reference), exaggeration=profile.exaggeration
            )
            if model.conds is None:
                raise RuntimeError("VoiceReferenceConditioningFailed")
            prepared[voice_id] = model.conds
        self._chatterbox_conditionals = prepared

    def _load_chatterbox(self) -> Any:
        if self._chatterbox is None:
            import torch
            from chatterbox.mtl_tts import ChatterboxMultilingualTTS

            if not torch.cuda.is_available():
                raise RuntimeError("ChatterboxCudaUnavailable")
            try:
                self._chatterbox = ChatterboxMultilingualTTS.from_pretrained(
                    device="cuda", t3_model="v3"
                )
                self._prepare_chatterbox_conditionals(self._chatterbox)
            except Exception:
                self._chatterbox = None
                self._chatterbox_conditionals = {}
                raise
        elif not self._chatterbox_conditionals:
            self._prepare_chatterbox_conditionals(self._chatterbox)
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
        import numpy as np
        import pyloudnorm as pyln

        audio = np.asarray(samples, dtype=np.float32).reshape(-1)
        audio = np.nan_to_num(audio, copy=False)
        if pitch:
            import librosa

            audio = librosa.effects.pitch_shift(
                audio, sr=sample_rate, n_steps=float(pitch), res_type="soxr_hq"
            )
        if abs(speed - 1.0) > 0.001:
            import librosa

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
        del speed  # Resampling a generated voice was the source of audible artifacts.
        import soundfile as sf
        import torch

        model = self._load_chatterbox()
        conditionals = self._chatterbox_conditionals.get(profile.voice_id)
        if conditionals is None:
            raise RuntimeError("VoiceReferenceProfileUnavailable")
        model.conds = conditionals
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
            0.0,
            1.0,
        )
        sf.write(path, samples, int(model.sr), subtype="PCM_16")
        return int(model.sr)

    def _reserve_response_usage(
        self,
        response_id: str,
        characters: int,
        per_response_limit: int,
    ) -> None:
        if not response_id:
            # Older callers send a single chunk per request; keep that safe too.
            if characters > per_response_limit:
                raise ElevenLabsUsageLimit("ElevenLabsResponseLimitReached")
            return
        current = self._response_usage.get(response_id, 0)
        if per_response_limit <= 0 or current + characters > per_response_limit:
            raise ElevenLabsUsageLimit("ElevenLabsResponseLimitReached")
        self._response_usage[response_id] = current + characters
        self._response_usage.move_to_end(response_id)
        while len(self._response_usage) > 256:
            self._response_usage.popitem(last=False)

    def _generate_elevenlabs(
        self,
        text: str,
        config: dict[str, Any],
        path: Path,
        *,
        response_id: str,
    ) -> None:
        api_key = self._api_key()
        voice_id = self._voice_id(config)
        characters = len(text)
        self._reserve_response_usage(
            response_id,
            characters,
            int(config["per_response_char_limit"]),
        )
        # Reserve before starting the potentially billable request. The local
        # tracker is intentionally conservative and is not an invoice.
        reserve_elevenlabs_usage(
            self.voice_root,
            characters,
            monthly_limit=int(config["monthly_char_limit"]),
        )
        query = urllib.parse.urlencode({"output_format": _ELEVENLABS_OUTPUT_FORMAT})
        url = (
            f"{_ELEVENLABS_BASE_URL}/v1/text-to-speech/"
            f"{urllib.parse.quote(voice_id)}?{query}"
        )
        body = json.dumps(
            {
                "text": text,
                "model_id": str(config.get("elevenlabs_model_id") or "eleven_flash_v2_5"),
                "language_code": "de",
            },
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            method="POST",
        )
        audio = self._url_request(request)
        if not audio:
            raise ElevenLabsUnavailable("ElevenLabsEmptyAudio")
        path.write_bytes(audio)

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

    @staticmethod
    def _backend_chain(profile: Any, backend_override: str) -> tuple[str, ...]:
        if backend_override:
            if backend_override == "piper":
                return ("piper",)
            if backend_override == "chatterbox":
                return ("chatterbox", "piper")
            raise ValueError("InvalidBackendOverride")
        if profile.backend == "elevenlabs":
            return ("elevenlabs", "chatterbox", "piper")
        if profile.backend == "chatterbox":
            return ("chatterbox", "piper")
        if profile.backend == "piper":
            return ("piper",)
        raise ValueError("InvalidVoiceBackend")

    def synthesize(self, request: dict[str, Any]) -> dict[str, Any]:
        import psutil
        import torch

        text = str(request.get("text", "")).strip()
        voice_id = str(request.get("voice_id", ""))
        if not text or len(text) > 4000 or voice_id not in PROFILE_BY_ID:
            raise ValueError("InvalidSynthesisRequest")
        config = load_voice_config(self.config_path)
        profile = PROFILE_BY_ID[voice_id]
        local_profile = (
            PROFILE_BY_ID[str(config["local_fallback_voice_id"])]
            if profile.backend == "elevenlabs"
            else profile
        )
        speed = max(0.75, min(float(request.get("speed_multiplier", 1.0)), 1.25))
        backend_override = str(request.get("backend_override", "")).strip()
        if backend_override not in {"", "chatterbox", "piper"}:
            raise ValueError("InvalidBackendOverride")
        chain = self._backend_chain(profile, backend_override)
        fallback_reason = str(request.get("primary_error", "")).strip() or None
        response_id = str(request.get("response_id", ""))[:128]
        cache_key = hashlib.sha256(
            json.dumps(
                {
                    "text": text,
                    "voice_id": voice_id,
                    "local_fallback_voice_id": local_profile.voice_id,
                    "elevenlabs_voice_id": (
                        str(config.get("elevenlabs_voice_id") or "")
                        if "elevenlabs" in chain
                        else None
                    ),
                    "elevenlabs_model_id": (
                        str(config.get("elevenlabs_model_id") or "")
                        if "elevenlabs" in chain
                        else None
                    ),
                    "speed": speed,
                    "pitch": local_profile.pitch_semitones,
                    "profile_speed": local_profile.speed,
                    "exaggeration": local_profile.exaggeration,
                    "cfg_weight": local_profile.cfg_weight,
                    "temperature": local_profile.temperature,
                    "seed": local_profile.seed,
                    "backend_override": backend_override or None,
                    "fallback_reason": fallback_reason,
                    "schema": VOICE_CACHE_SCHEMA,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        audition = bool(request.get("audition"))
        output_root = self.audition_root if audition else self.cache_root
        stem = voice_id if audition else cache_key
        bypass_cache = bool(request.get("bypass_cache"))
        metadata_path = output_root / f"{stem}.json"
        cached_metadata: dict[str, Any] = {}
        if metadata_path.is_file():
            try:
                cached_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached_metadata = {}
        transient_primary_fallback = bool(cached_metadata.get("fallback_used")) and (
            len(chain) > 1 and not backend_override
        )
        cached_name = str(cached_metadata.get("audio_file") or "")
        cached_path = (output_root / cached_name).resolve(strict=False)
        cache_path_valid = bool(
            cached_name
            and cached_path.is_relative_to(output_root.resolve())
            and cached_path.is_file()
        )
        if (
            cache_path_valid
            and cached_metadata.get("schema") == VOICE_CACHE_SCHEMA
            and not transient_primary_fallback
            and not bypass_cache
        ):
            audio_format = str(cached_metadata.get("format") or "wav")
            duration, sample_rate = (
                self._wav_duration(cached_path)
                if audio_format == "wav"
                else (float(cached_metadata.get("duration_seconds") or 0.0), 44100)
            )
            return {
                "ok": True,
                "audio_path": str(cached_path),
                "format": audio_format,
                "backend": cached_metadata.get("backend", profile.backend),
                "fallback_used": bool(cached_metadata.get("fallback_used", False)),
                "primary_error": cached_metadata.get("primary_error"),
                "provider_errors": cached_metadata.get("provider_errors", []),
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
        temporary_metadata = metadata_path.with_name(
            f".{metadata_path.name}.{os.getpid()}.tmp"
        )
        backend = ""
        audio_format = "wav"
        sample_rate = 22050
        errors = [fallback_reason] if fallback_reason else []
        destination: Path | None = None
        temporary: Path | None = None
        try:
            for candidate in chain:
                audio_format = "mp3" if candidate == "elevenlabs" else "wav"
                destination = output_root / f"{stem}.{audio_format}"
                # Keep the real suffix so soundfile/Piper can select the WAV
                # encoder while the file is still replace-on-success temporary.
                temporary = destination.with_name(
                    f".{destination.stem}.{os.getpid()}.tmp{destination.suffix}"
                )
                try:
                    if candidate == "elevenlabs":
                        self._generate_elevenlabs(
                            text,
                            config,
                            temporary,
                            response_id=response_id,
                        )
                        sample_rate = 44100
                    elif candidate == "chatterbox":
                        sample_rate = self._generate_chatterbox(
                            text, local_profile, temporary, speed
                        )
                    else:
                        sample_rate = self._generate_piper(
                            text, local_profile, temporary, speed
                        )
                    backend = candidate
                    break
                except Exception as exc:
                    errors.append(type(exc).__name__)
                    temporary.unlink(missing_ok=True)
            if not backend or destination is None or temporary is None:
                raise RuntimeError("VoiceProviderChainFailed")
            fallback_used = backend != chain[0]
            primary_error = errors[0] if errors else None
            temporary.replace(destination)
            duration = 0.0
            if audio_format == "wav":
                duration, sample_rate = self._wav_duration(destination)
            temporary_metadata.write_text(
                json.dumps(
                    {
                        "audio_file": destination.name,
                        "format": audio_format,
                        "backend": backend,
                        "fallback_used": fallback_used,
                        "primary_error": primary_error,
                        "provider_errors": errors,
                        "backend_override": backend_override or None,
                        "schema": VOICE_CACHE_SCHEMA,
                        "duration_seconds": duration,
                        "reference_profile": (
                            local_profile.voice_id if backend == "chatterbox" else None
                        ),
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            temporary_metadata.replace(metadata_path)
        finally:
            gpu_sampler.stop()
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            temporary_metadata.unlink(missing_ok=True)
        elapsed = max(time.perf_counter() - started, 0.001)
        cpu_after = sum(process.cpu_times()[:2])
        if destination is None:
            raise RuntimeError("VoiceProviderChainFailed")
        duration = (
            self._wav_duration(destination)[0]
            if audio_format == "wav"
            else 0.0
        )
        peak_vram = (
            float(torch.cuda.max_memory_allocated()) / (1024 * 1024)
            if torch.cuda.is_available()
            else 0.0
        )
        return {
            "ok": True,
            "audio_path": str(destination),
            "format": audio_format,
            "backend": backend,
            "fallback_used": fallback_used,
            "primary_error": primary_error,
            "provider_errors": errors,
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
                elif command == "list_elevenlabs_voices":
                    response = worker.list_elevenlabs_voices()
                elif command == "validate_elevenlabs_voice":
                    response = worker.validate_elevenlabs_voice(
                        str(request.get("voice_id") or "")
                    )
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
