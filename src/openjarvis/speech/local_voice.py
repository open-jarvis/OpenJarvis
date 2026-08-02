"""Main-process client for the isolated local TTS worker."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from openjarvis.speech.tts import TTSBackend, TTSResult
from openjarvis.speech.voice_config import (
    AUDITION_TEXT,
    PROFILE_BY_ID,
    VOICE_CACHE_SCHEMA,
    VOICE_PROFILES,
    VOICE_REFERENCE_ASSETS,
    load_voice_config,
    public_profile,
    write_voice_config,
)


class VoiceWorkerTimeout(RuntimeError):
    """Raised after an owned voice worker exceeds a bounded request deadline."""


class LocalVoiceBackend(TTSBackend):
    """Chatterbox-first TTS with a Piper fallback in a separate environment."""

    backend_id = "chatterbox+piper"

    def __init__(
        self,
        runtime_root: Path,
        *,
        worker_python: Path | None = None,
        repo_root: Path | None = None,
        health_timeout_seconds: float = 20.0,
        synthesis_timeout_seconds: float = 28.0,
        fallback_timeout_seconds: float = 15.0,
        warmup_timeout_seconds: float = 90.0,
    ) -> None:
        self.runtime_root = runtime_root.resolve(strict=True)
        self.voice_root = self.runtime_root / "voice"
        self.config_path = self.voice_root / "voice-config.json"
        self.cache_root = self.voice_root / "cache"
        self.audition_root = self.voice_root / "auditions"
        self.model_root = self.voice_root / "models"
        for path in (self.cache_root, self.audition_root, self.model_root):
            path.mkdir(parents=True, exist_ok=True)
        load_voice_config(self.config_path)
        self.repo_root = (repo_root or Path(__file__).resolve().parents[3]).resolve()
        default_python = self.repo_root / ".venv-voice" / "Scripts" / "python.exe"
        self.worker_python = (worker_python or default_python).resolve(strict=False)
        self.health_timeout_seconds = max(float(health_timeout_seconds), 0.01)
        self.synthesis_timeout_seconds = max(float(synthesis_timeout_seconds), 0.01)
        self.fallback_timeout_seconds = max(float(fallback_timeout_seconds), 0.01)
        self.warmup_timeout_seconds = max(float(warmup_timeout_seconds), 0.01)
        self._process: subprocess.Popen[str] | None = None
        self._stderr_handle: Any = None
        self._response_queue: queue.Queue[str | None] | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_error = ""

    def _worker_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        source_root = str(self.repo_root / "src")
        inherited_pythonpath = environment.get("PYTHONPATH", "")
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (source_root, inherited_pythonpath) if part
        )
        hf_home = self.model_root / "huggingface"
        environment["HF_HOME"] = str(hf_home)
        environment["HUGGINGFACE_HUB_CACHE"] = str(hf_home / "hub")
        environment["HF_HUB_DISABLE_TELEMETRY"] = "1"
        environment["DO_NOT_TRACK"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        return environment

    def _start(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self.close()
        if not self.worker_python.is_file():
            raise RuntimeError("local voice environment is not installed")
        log_path = self.voice_root / "voice-worker.log"
        stderr_handle = log_path.open("a", encoding="utf-8")
        try:
            process = subprocess.Popen(  # noqa: S603
                [
                    str(self.worker_python),
                    "-m",
                    "openjarvis.speech.local_voice_worker",
                    "--runtime-root",
                    str(self.runtime_root),
                ],
                cwd=self.repo_root,
                env=self._worker_environment(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="strict",
                bufsize=1,
                creationflags=(
                    getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt"
                    else 0
                ),
            )
        except Exception:
            stderr_handle.close()
            raise
        response_queue: queue.Queue[str | None] = queue.Queue()
        reader_thread = threading.Thread(
            target=self._read_stdout,
            args=(process, response_queue),
            name="openjarvis-voice-worker-reader",
            daemon=True,
        )
        self._process = process
        self._stderr_handle = stderr_handle
        self._response_queue = response_queue
        self._reader_thread = reader_thread
        reader_thread.start()

    @staticmethod
    def _read_stdout(
        process: subprocess.Popen[str], response_queue: queue.Queue[str | None]
    ) -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    response_queue.put(line)
        finally:
            response_queue.put(None)

    def _request(
        self, payload: dict[str, Any], *, timeout_seconds: float | None = None
    ) -> dict[str, Any]:
        with self._lock:
            self._start()
            process = self._process
            response_queue = self._response_queue
            if process is None or process.stdin is None or response_queue is None:
                raise RuntimeError("local voice worker pipe is unavailable")
            try:
                process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
                process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                self._last_error = "VoiceWorkerPipeClosed"
                self._stop_worker_locked(graceful=False)
                raise RuntimeError(self._last_error) from exc
            deadline = time.monotonic() + max(
                float(timeout_seconds or self.synthesis_timeout_seconds), 0.01
            )
            response = None
            for _ in range(128):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._last_error = "VoiceWorkerTimeout"
                    self._stop_worker_locked(graceful=False)
                    raise VoiceWorkerTimeout(self._last_error)
                try:
                    line = response_queue.get(timeout=remaining)
                except queue.Empty as exc:
                    self._last_error = "VoiceWorkerTimeout"
                    self._stop_worker_locked(graceful=False)
                    raise VoiceWorkerTimeout(self._last_error) from exc
                if line is None:
                    code = process.poll()
                    self._last_error = f"voice worker stopped ({code})"
                    self._stop_worker_locked(graceful=False)
                    raise RuntimeError(self._last_error)
                try:
                    candidate = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(candidate, dict) and isinstance(
                    candidate.get("ok"), bool
                ):
                    response = candidate
                    break
            if response is None:
                self._last_error = "VoiceWorkerProtocolError"
                self._stop_worker_locked(graceful=False)
                raise RuntimeError("voice worker protocol was not synchronized")
            if response.get("ok") is not True:
                category = str(response.get("error", "voice synthesis failed"))
                self._last_error = category[:160]
                raise RuntimeError(self._last_error)
            self._last_error = ""
            return response

    def _synthesis_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._request(
                payload, timeout_seconds=self.synthesis_timeout_seconds
            )
        except VoiceWorkerTimeout:
            voice_id = str(payload.get("voice_id", ""))
            profile = PROFILE_BY_ID.get(voice_id)
            if profile is None or profile.backend != "chatterbox":
                raise
            return self._request(
                {
                    **payload,
                    "backend_override": "piper",
                    "primary_error": "VoiceWorkerTimeout",
                },
                timeout_seconds=self.fallback_timeout_seconds,
            )

    def synthesize(
        self,
        text: str,
        *,
        voice_id: str = "",
        speed: float = 1.0,
        output_format: str = "wav",
        bypass_cache: bool = False,
    ) -> TTSResult:
        if output_format != "wav":
            raise ValueError("local voice output format must be wav")
        clean_text = text.strip()
        if not clean_text or len(clean_text) > 4000:
            raise ValueError("speech text must contain 1 to 4000 characters")
        config = load_voice_config(self.config_path)
        selected = voice_id or str(config["selected_voice_id"])
        if selected not in PROFILE_BY_ID:
            raise ValueError("unknown voice profile")
        response = self._synthesis_request(
            {
                "command": "synthesize",
                "text": clean_text,
                "voice_id": selected,
                "speed_multiplier": max(0.75, min(float(speed), 1.25)),
                "bypass_cache": bool(bypass_cache or not config["cache_enabled"]),
            }
        )
        audio_path = Path(str(response["audio_path"])).resolve(strict=True)
        if not audio_path.is_relative_to(self.voice_root):
            raise RuntimeError("voice worker returned an invalid audio path")
        return TTSResult(
            audio=audio_path.read_bytes(),
            format="wav",
            duration_seconds=float(response.get("duration_seconds", 0.0)),
            voice_id=selected,
            sample_rate=int(response.get("sample_rate", 22050)),
            metadata={
                key: response.get(key)
                for key in (
                    "backend",
                    "cache_hit",
                    "synthesis_ms",
                    "cpu_percent",
                    "gpu_peak_vram_mb",
                    "gpu_utilization_avg_percent",
                    "gpu_utilization_peak_percent",
                    "gpu_total_memory_peak_mb",
                    "system_cpu_percent",
                    "fallback_used",
                    "primary_error",
                )
            },
        )

    def available_voices(self) -> list[str]:
        return [profile.voice_id for profile in VOICE_PROFILES]

    def health(self) -> bool:
        try:
            response = self._request(
                {"command": "health"},
                timeout_seconds=self.health_timeout_seconds,
            )
            return bool(response.get("chatterbox") and response.get("piper"))
        except Exception as exc:
            self._last_error = type(exc).__name__
            return False

    def warmup(self) -> bool:
        """Load the primary GPU model and CPU fallback before serving audio."""

        try:
            response = self._request(
                {"command": "warmup"},
                timeout_seconds=self.warmup_timeout_seconds,
            )
            ready = bool(
                response.get("chatterbox_loaded") and response.get("piper_loaded")
                and response.get("reference_profiles_loaded")
                == len(VOICE_REFERENCE_ASSETS)
            )
            if not ready:
                self._last_error = str(
                    response.get("primary_error") or "VoiceWarmupFailed"
                )
            return ready
        except Exception as exc:
            self._last_error = type(exc).__name__
            return False

    def last_error(self) -> str:
        return self._last_error

    def _audition_is_current(self, voice_id: str) -> bool:
        path = self.audition_root / f"{voice_id}.wav"
        metadata_path = path.with_suffix(".json")
        if not path.is_file() or not metadata_path.is_file():
            return False
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return metadata.get("schema") == VOICE_CACHE_SCHEMA

    def voice_status(self) -> dict[str, Any]:
        config = load_voice_config(self.config_path)
        worker = self._request(
            {"command": "health"}, timeout_seconds=self.health_timeout_seconds
        )
        return {
            "selected_voice_id": config["selected_voice_id"],
            "primary_backend": config["primary_backend"],
            "fallback_backend": config["fallback_backend"],
            "language": config["language"],
            "audition_text": AUDITION_TEXT,
            "profiles": [
                {
                    **public_profile(profile),
                    "audition_ready": self._audition_is_current(profile.voice_id),
                }
                for profile in VOICE_PROFILES
            ],
            "worker": {
                key: worker.get(key)
                for key in (
                    "chatterbox",
                    "piper",
                    "cuda",
                    "device",
                    "chatterbox_loaded",
                    "reference_profiles_loaded",
                    "piper_loaded",
                )
            },
        }

    def select_voice(self, voice_id: str) -> dict[str, Any]:
        if voice_id not in PROFILE_BY_ID:
            raise ValueError("unknown voice profile")
        config = load_voice_config(self.config_path)
        config["selected_voice_id"] = voice_id
        write_voice_config(self.config_path, config)
        return config

    def generate_auditions(self) -> list[dict[str, Any]]:
        results = []
        for profile in VOICE_PROFILES:
            response = self._synthesis_request(
                {
                    "command": "synthesize",
                    "text": AUDITION_TEXT,
                    "voice_id": profile.voice_id,
                    "audition": True,
                    "speed_multiplier": 1.0,
                }
            )
            results.append(
                {
                    "voice_id": profile.voice_id,
                    "backend": response.get("backend"),
                    "fallback_used": response.get("fallback_used", False),
                    "duration_seconds": response.get("duration_seconds", 0.0),
                    "synthesis_ms": response.get("synthesis_ms", 0.0),
                    "cache_hit": response.get("cache_hit", False),
                }
            )
        return results

    def audition_path(self, voice_id: str) -> Path:
        if voice_id not in PROFILE_BY_ID:
            raise ValueError("unknown voice profile")
        if not self._audition_is_current(voice_id):
            raise FileNotFoundError("current voice audition is not available")
        path = (self.audition_root / f"{voice_id}.wav").resolve(strict=True)
        if not path.is_relative_to(self.audition_root):
            raise ValueError("invalid audition path")
        return path

    def close(self) -> None:
        with self._lock:
            self._stop_worker_locked(graceful=True)

    def _stop_worker_locked(self, *, graceful: bool) -> None:
        process, self._process = self._process, None
        reader_thread, self._reader_thread = self._reader_thread, None
        self._response_queue = None
        if process is not None and process.poll() is None:
            if graceful:
                try:
                    if process.stdin is not None:
                        process.stdin.write('{"command":"shutdown"}\n')
                        process.stdin.flush()
                    process.wait(timeout=5)
                except Exception:
                    graceful = False
            if not graceful and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
        if process is not None:
            for stream in (process.stdin, process.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
        if (
            reader_thread is not None
            and reader_thread is not threading.current_thread()
        ):
            reader_thread.join(timeout=3)
        if self._stderr_handle is not None:
            self._stderr_handle.close()
            self._stderr_handle = None


__all__ = ["LocalVoiceBackend", "VoiceWorkerTimeout"]
