# src/openjarvis/mining/_discovery.py
"""Capability detection for mining providers.

Each function answers a single yes/no question and returns ``(ok: bool,
info: str)`` where ``info`` is a short human-readable explanation surfaced
verbatim by ``jarvis mine doctor``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Tuple

import httpx

from openjarvis.core.config import HardwareInfo
from openjarvis.mining._models import get_pearl_model_spec, pearl_variant_for_base_model
from openjarvis.mining._stubs import MiningCapabilities

# ---------------------------------------------------------------------------
# Constants for the v1 vllm-pearl provider
# ---------------------------------------------------------------------------

REQUIRED_COMPUTE_CAPABILITY = "9.0"  # sm_90a — Hopper
REQUIRED_VRAM_GB = 70.0
SUPPORTED_VLLM_ENGINE_IDS = frozenset({"vllm"})


def detect_for_engine_model(
    *,
    hw: HardwareInfo,
    engine_id: str,
    model: str,
    provider_id: str,
) -> MiningCapabilities:
    """Capability matrix for the ``vllm-pearl`` provider.

    Pure inspection. No subprocess, no Docker, no network. Used by
    ``jarvis mine doctor`` and ``jarvis mine init``.
    """
    if provider_id != "vllm-pearl":
        return MiningCapabilities(False, reason=f"unknown provider {provider_id!r}")

    # Engine
    if engine_id not in SUPPORTED_VLLM_ENGINE_IDS:
        return MiningCapabilities(
            False,
            reason=f"engine '{engine_id}' has no Pearl plugin in v1; use vllm",
        )

    # Hardware
    if hw.gpu is None:
        return MiningCapabilities(False, reason="no GPU detected")
    if hw.gpu.vendor != "nvidia":
        return MiningCapabilities(
            False,
            reason=f"vllm-pearl requires NVIDIA Hopper; detected {hw.gpu.vendor!r}. "
            f"Apple Silicon support tracked in Spec B.",
        )
    if not hw.gpu.compute_capability.startswith("9.0"):
        return MiningCapabilities(
            False,
            reason=f"needs compute_capability 9.0 (sm_90a / H100/H200); detected "
            f"{hw.gpu.compute_capability!r} ({hw.gpu.name})",
        )
    spec = get_pearl_model_spec(model)
    required_vram_gb = spec.min_vram_gb if spec else REQUIRED_VRAM_GB
    if hw.gpu.vram_gb < required_vram_gb:
        return MiningCapabilities(
            False,
            reason=f"needs ≥{required_vram_gb:.0f} GB VRAM for {model}; "
            f"detected {hw.gpu.vram_gb:.0f} GB",
        )

    # Model
    pearl_variant = pearl_variant_for_base_model(model)
    if pearl_variant:
        return MiningCapabilities(
            False,
            reason=f"model {model!r} is a raw base model; planned Pearl variant is "
            f"{pearl_variant!r}",
        )
    if spec is None:
        return MiningCapabilities(
            False,
            reason=f"model {model!r} is not in OpenJarvis' Pearl model registry",
        )
    if not spec.is_validated:
        return MiningCapabilities(
            False,
            reason=f"model {model!r} is {spec.status}; it needs Pearl quantization "
            "and H100/H200 validation before mining is enabled",
        )

    return MiningCapabilities(supported=True)


# ---------------------------------------------------------------------------
# Doctor checks (one per row of `jarvis mine doctor` output)
# ---------------------------------------------------------------------------


def _docker_client():  # pragma: no cover - trivial wrapper, mocked in tests
    try:
        import docker
    except ImportError as exc:
        raise RuntimeError(
            "Docker SDK not installed; install with `uv sync --extra mining-pearl-vllm`"
        ) from exc

    return docker.from_env()


def check_docker_available() -> Tuple[bool, str]:
    try:
        c = _docker_client()
        c.ping()
        ver = c.version().get("Version", "unknown")
        return True, f"running {ver}"
    except Exception as e:  # noqa: BLE001 - intentionally broad
        return False, str(e).splitlines()[0]


def check_disk_free(path: Path) -> Tuple[bool, str]:
    from openjarvis.mining._constants import MIN_FREE_DISK_GB

    usage = shutil.disk_usage(path)
    free_gb = usage.free / (1024**3)
    if free_gb < MIN_FREE_DISK_GB:
        return False, f"only {free_gb:.0f} GB free (need ≥{MIN_FREE_DISK_GB} GB)"
    return True, f"{free_gb:.0f} GB free"


def check_pearld_reachable(url: str, user: str, password: str) -> Tuple[bool, str]:
    """Probe pearld via JSON-RPC ``getblockchaininfo``."""
    try:
        resp = httpx.post(
            url,
            json={
                "jsonrpc": "1.0",
                "id": "ojprobe",
                "method": "getblockchaininfo",
                "params": [],
            },
            auth=(user, password),
            timeout=5.0,
        )
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        data = resp.json()
        result = data.get("result") or {}
        blocks = result.get("blocks", "?")
        headers = result.get("headers", "?")
        synced = blocks == headers
        marker = "synced" if synced else f"syncing ({blocks}/{headers})"
        return True, f"block height {blocks} ({marker})"
    except httpx.ConnectError as e:
        return False, f"connection refused: {e}"
    except Exception as e:  # noqa: BLE001
        return False, str(e).splitlines()[0]


def check_wallet_address_format(address: str) -> Tuple[bool, str]:
    """Pearl bech32/bech32m addresses begin with ``prl1q...`` or ``prl1p...``.

    We do *not* attempt to validate the bech32 checksum — that's a stronger
    contract that may shift between Pearl revs. Format check only.
    """
    if not address:
        return False, "empty"
    if not address.startswith(("prl1q", "prl1p")):
        return False, f"expected 'prl1q...' or 'prl1p...' prefix; got {address[:6]!r}"
    if len(address) < 14:
        return False, f"too short ({len(address)} chars)"
    return True, "format ok"
