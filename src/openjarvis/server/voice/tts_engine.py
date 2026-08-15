"""Validated metadata for a provisioned local VieNeu artifact."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from dataclasses import dataclass
from importlib.metadata import version as _package_version
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from openjarvis.server.voice.audio import RealtimeTtsChunk

_COMMIT_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{40}$")
_ITERATION_COMPLETE = object()
_SUPPORTED_VIENEU_VERSION = "3.2.3"
_VIENEU_CONSTRUCTION_LOCK = Lock()


@dataclass(frozen=True, slots=True)
class LocalVieNeuArtifact:
    """Local VieNeu assets and their pinned provenance."""

    root: Path
    model_dir: Path
    onnx_dir: Path
    codec_dir: Path
    revision: str
    voice: str
    style: str
    model_repo: str
    model_revision: str
    codec_repo: str
    codec_revision: str


_BENCHMARK_RESULT_KEYS = {
    "schema_version",
    "artifact",
    "ttfa_ms",
    "real_time_factor",
    "max_gap_ms",
    "thresholds",
    "accepted",
}
_BENCHMARK_ARTIFACT_KEYS = {
    "model_repo",
    "model_revision",
    "codec_repo",
    "codec_revision",
    "voice",
    "style",
}
_BENCHMARK_THRESHOLD_KEYS = {
    "max_ttfa_ms",
    "max_real_time_factor",
    "max_gap_ms",
}


def load_vieneu_artifact(root: Path) -> LocalVieNeuArtifact:
    """Load an explicit local artifact without importing or warming VieNeu."""
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("vieneu_artifact_manifest_missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("vieneu_artifact_manifest_invalid") from exc
    if not isinstance(manifest, dict):
        raise ValueError("vieneu_artifact_manifest_invalid")

    schema_version = manifest.get("schema_version")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int):
        raise ValueError("vieneu_artifact_manifest_invalid")
    if schema_version != 1:
        raise ValueError("vieneu_artifact_schema_unsupported")

    required = (
        "model_dir",
        "onnx_dir",
        "codec_dir",
        "model_repo",
        "model_revision",
        "codec_repo",
        "codec_revision",
        "revision",
        "voice",
        "style",
    )
    if any(not _is_nonempty_text(manifest.get(name)) for name in required):
        raise ValueError("vieneu_artifact_manifest_invalid")
    if any(
        _COMMIT_ID_PATTERN.fullmatch(manifest[name]) is None
        for name in ("model_revision", "codec_revision")
    ):
        raise ValueError("vieneu_artifact_manifest_invalid")
    if manifest["revision"] != manifest["model_revision"]:
        raise ValueError("vieneu_artifact_manifest_invalid")

    model_dir, onnx_dir, codec_dir = tuple(
        _local_asset_path(root, manifest[name])
        for name in ("model_dir", "onnx_dir", "codec_dir")
    )
    if any(not path.is_dir() for path in (model_dir, onnx_dir, codec_dir)):
        raise ValueError("vieneu_artifact_assets_missing")
    return LocalVieNeuArtifact(
        root=root,
        model_dir=model_dir,
        onnx_dir=onnx_dir,
        codec_dir=codec_dir,
        revision=manifest["revision"],
        voice=manifest["voice"],
        style=manifest["style"],
        model_repo=manifest["model_repo"],
        model_revision=manifest["model_revision"],
        codec_repo=manifest["codec_repo"],
        codec_revision=manifest["codec_revision"],
    )


def load_accepted_vieneu_artifact(root: Path) -> LocalVieNeuArtifact:
    """Load a local artifact only when its current benchmark was accepted."""
    artifact = load_vieneu_artifact(root)
    _require_accepted_benchmark(artifact)
    return artifact


def _require_accepted_benchmark(artifact: LocalVieNeuArtifact) -> None:
    result_path = artifact.root / "benchmark-result.json"
    if not result_path.is_file():
        raise ValueError("vieneu_benchmark_result_required")
    try:
        result = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("vieneu_benchmark_result_invalid") from exc
    if (
        not isinstance(result, dict)
        or set(result) != _BENCHMARK_RESULT_KEYS
        or type(result.get("schema_version")) is not int
        or result["schema_version"] != 1
        or type(result.get("accepted")) is not bool
    ):
        raise ValueError("vieneu_benchmark_result_invalid")

    provenance = result.get("artifact")
    if (
        not isinstance(provenance, dict)
        or set(provenance) != _BENCHMARK_ARTIFACT_KEYS
        or any(not _is_nonempty_text(value) for value in provenance.values())
    ):
        raise ValueError("vieneu_benchmark_result_invalid")
    expected_provenance = {
        "model_repo": artifact.model_repo,
        "model_revision": artifact.model_revision,
        "codec_repo": artifact.codec_repo,
        "codec_revision": artifact.codec_revision,
        "voice": artifact.voice,
        "style": artifact.style,
    }
    if provenance != expected_provenance:
        raise ValueError("vieneu_benchmark_result_stale")

    thresholds = result.get("thresholds")
    if (
        not isinstance(thresholds, dict)
        or set(thresholds) != _BENCHMARK_THRESHOLD_KEYS
        or not _is_nonnegative_int(result.get("ttfa_ms"))
        or not _is_nonnegative_number(result.get("real_time_factor"))
        or not _is_nonnegative_int(result.get("max_gap_ms"))
        or not _is_nonnegative_int(thresholds.get("max_ttfa_ms"))
        or not _is_nonnegative_number(thresholds.get("max_real_time_factor"))
        or not _is_nonnegative_int(thresholds.get("max_gap_ms"))
    ):
        raise ValueError("vieneu_benchmark_result_invalid")

    accepted = (
        result["ttfa_ms"] <= thresholds["max_ttfa_ms"]
        and result["real_time_factor"] <= thresholds["max_real_time_factor"]
        and result["max_gap_ms"] <= thresholds["max_gap_ms"]
    )
    if result["accepted"] is not accepted:
        raise ValueError("vieneu_benchmark_result_invalid")
    if not accepted:
        raise ValueError("vieneu_benchmark_result_rejected")


VIENEU_THREADS_ENV = "OPENJARVIS_VIENEU_THREADS"
DEFAULT_VIENEU_THREADS = 4


def _limit_onnx_threads() -> None:
    """Cap ONNX thread pools before the first session is built.

    Left alone, ONNX Runtime sizes each session's pool to the core count and
    VieNeu opens several — 86 threads on a 16-core box, which thrashes. The
    renderer then produces audio slower than it plays and speech breaks up
    mid-word. Measured on that machine, per realtime factor:

        4 threads  3.3x     8 threads  2.8x
        16 threads 1.6x     unset      0.4-0.7x

    A pinned pool is both faster and steadier, and steadiness is what keeps
    the speaker fed. Override with OPENJARVIS_VIENEU_THREADS.

    Setting it here only partially helps (measured 1.3x): importing openjarvis
    already pulls numpy, whose pool sizes itself at import. Export the variable
    before the process starts — as scripts/start-openjarvis.sh does — to
    get the full effect.
    """
    raw = os.environ.get(VIENEU_THREADS_ENV, "").strip()
    try:
        threads = int(raw) if raw else DEFAULT_VIENEU_THREADS
    except ValueError:
        threads = DEFAULT_VIENEU_THREADS
    if threads <= 0:
        threads = DEFAULT_VIENEU_THREADS
    for name in ("OMP_NUM_THREADS", "ORT_NUM_THREADS"):
        os.environ.setdefault(name, str(threads))


def create_vieneu_runtime(artifact: LocalVieNeuArtifact) -> Any:
    """Construct the pinned public VieNeu wrapper with the validated ONNX codec."""
    if _package_version("vieneu") != _SUPPORTED_VIENEU_VERSION:
        raise RuntimeError("vieneu_version_unsupported")

    _limit_onnx_threads()

    from vieneu import Vieneu
    from vieneu._v3_turbo_engine import onnx_runtime_lite

    with _VIENEU_CONSTRUCTION_LOCK:
        engine_type = onnx_runtime_lite.OnnxV3LiteEngine

        def create_local_engine(*args: Any, **kwargs: Any) -> Any:
            kwargs["codec_dir"] = str(artifact.codec_dir)
            return engine_type(*args, **kwargs)

        onnx_runtime_lite.OnnxV3LiteEngine = create_local_engine
        try:
            return Vieneu(
                mode="v3turbo",
                backend="onnx",
                backbone_repo=str(artifact.model_dir),
                onnx_dir=str(artifact.onnx_dir),
            )
        finally:
            onnx_runtime_lite.OnnxV3LiteEngine = engine_type


class VieNeuRealtimeTts:
    """Render a validated local VieNeu artifact as transient PCM frames."""

    def __init__(
        self,
        artifact: LocalVieNeuArtifact,
        runtime_factory: Callable[[LocalVieNeuArtifact], Any] = create_vieneu_runtime,
        to_thread: Callable[..., Awaitable[Any]] = asyncio.to_thread,
    ) -> None:
        self._artifact = artifact
        self._runtime_factory = runtime_factory
        self._to_thread = to_thread
        self._runtime_instance: Any | None = None
        self._runtime_task: asyncio.Future[Any] | None = None
        self._inference_lock = asyncio.Lock()

    async def start(self) -> None:
        await self._runtime()

    async def stream_tts(self, text: str) -> AsyncIterator[RealtimeTtsChunk]:
        runtime = await self._runtime()
        await self._inference_lock.acquire()
        pending: asyncio.Future[Any] | None = None
        try:
            pending = asyncio.ensure_future(
                self._to_thread(
                    lambda: iter(
                        runtime.infer_stream(
                            text,
                            voice=self._artifact.voice,
                            style=self._artifact.style,
                        )
                    )
                )
            )
            iterator = await asyncio.shield(pending)
            pending = None
            while True:
                pending = asyncio.ensure_future(
                    self._to_thread(_next_or_none, iterator)
                )
                block = await asyncio.shield(pending)
                pending = None
                if block is _ITERATION_COMPLETE:
                    return
                pcm = _float32_to_pcm_s16le(block)
                if pcm:
                    yield RealtimeTtsChunk(pcm, "local", "pcm_s16le", 48_000, 1)
        finally:
            if pending is not None and not pending.done():
                pending.add_done_callback(self._release_inference_after)
            else:
                if pending is not None and not pending.cancelled():
                    pending.exception()
                self._inference_lock.release()

    async def _runtime(self) -> Any:
        if self._runtime_instance is None:
            task = self._runtime_task
            if task is None:
                task = asyncio.ensure_future(
                    self._to_thread(self._runtime_factory, self._artifact)
                )
                task.add_done_callback(self._consume_task_exception)
                self._runtime_task = task
            try:
                runtime = await asyncio.shield(task)
            except asyncio.CancelledError:
                raise
            except Exception:
                if self._runtime_task is task:
                    self._runtime_task = None
                raise
            self._runtime_instance = runtime
            if self._runtime_task is task:
                self._runtime_task = None
        return self._runtime_instance

    def _release_inference_after(self, task: asyncio.Future[Any]) -> None:
        self._inference_lock.release()
        self._consume_task_exception(task)

    @staticmethod
    def _consume_task_exception(task: asyncio.Future[Any]) -> None:
        if not task.cancelled():
            task.exception()


def _next_or_none(iterator: Iterator[Any]) -> Any:
    try:
        return next(iterator)
    except StopIteration:
        return _ITERATION_COMPLETE


def _float32_to_pcm_s16le(samples: np.ndarray) -> bytes:
    clipped = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    ints = np.where(clipped <= -1.0, -32768, np.rint(clipped * 32767)).astype("<i2")
    return ints.tobytes()


def _is_nonempty_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _is_nonnegative_number(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value >= 0
    )


def _local_asset_path(root: Path, value: Any) -> Path:
    relative = Path(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("vieneu_artifact_path_invalid")
    path = root / relative
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("vieneu_artifact_path_invalid") from exc
    return path


__all__ = [
    "LocalVieNeuArtifact",
    "VieNeuRealtimeTts",
    "create_vieneu_runtime",
    "load_accepted_vieneu_artifact",
    "load_vieneu_artifact",
]
