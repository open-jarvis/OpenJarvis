# src/openjarvis/mining/_stubs.py
"""ABCs and dataclasses for the mining subsystem.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``
section 4.4 for the design rationale.
"""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from openjarvis.core.config import HardwareInfo

# ---------------------------------------------------------------------------
# Capability descriptor
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MiningCapabilities:
    """Result of a provider's ``detect()`` call.

    ``reason`` is human-readable and surfaced verbatim by ``jarvis mine doctor``
    when ``supported=False``.
    """

    supported: bool
    reason: Optional[str] = None
    estimated_hashrate: Optional[float] = None  # shares/sec, best-effort


# ---------------------------------------------------------------------------
# Submit-target tagged union (v2 seam — see spec §8.5)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SoloTarget:
    """Mine directly to a pearld node. v1 default."""

    pearld_rpc_url: str


@dataclass(slots=True)
class PoolTarget:
    """Mine through an OJ-operated pool. v2 — raises NotImplementedError in v1."""

    url: str
    worker_id: Optional[str] = None


SubmitTarget = Union[SoloTarget, PoolTarget]


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MiningConfig:
    """User-supplied mining configuration.

    Loaded from the ``[mining]`` TOML section by ``core/config.py``.
    """

    provider: str
    wallet_address: str
    submit_target: SubmitTarget
    fee_bps: int = 0  # v1: 0; v2: 2000 (=20%)
    fee_payout_address: Optional[str] = None  # v1: ignored; v2: OJ's address
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Live stats (returned by ``MiningProvider.stats()``)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MiningStats:
    provider_id: str
    shares_submitted: int = 0
    shares_accepted: int = 0
    blocks_found: int = 0
    hashrate: float = 0.0
    uptime_seconds: float = 0.0
    last_share_at: Optional[float] = None
    last_error: Optional[str] = None
    payout_target: str = "solo"  # v1: always "solo"; v2: "pool:<url>"
    fees_owed: int = 0  # v2 accounting hook; 0 in v1


# ---------------------------------------------------------------------------
# The ABC
# ---------------------------------------------------------------------------


class MiningProvider(ABC):
    """A mining provider — orchestrates a Pearl mining session.

    One provider per ``(hardware, engine, model)`` combo. All future
    hardware/engine paths (Apple Silicon, AMD, Ollama) implement this exact
    contract. See spec §4.4.
    """

    provider_id: str  # set by subclass

    @classmethod
    @abstractmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        """Return whether this provider can run on the given combo.

        Must be a pure inspection — no subprocess, no network, no Docker. Used
        by ``jarvis mine doctor`` and ``jarvis mine init`` for fast capability
        reporting.
        """

    @abstractmethod
    async def start(self, config: MiningConfig) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def is_running(self) -> bool: ...

    @abstractmethod
    def stats(self) -> MiningStats: ...


# ---------------------------------------------------------------------------
# Sidecar IO (see spec §5.3)
# ---------------------------------------------------------------------------


class Sidecar:
    """Read/write helpers for ``~/.openjarvis/runtime/mining.json``."""

    @staticmethod
    def write(path: Path, payload: dict[str, Any]) -> None:
        """Atomically write the sidecar JSON to ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: tmp file + rename
        fd, tmp = tempfile.mkstemp(prefix=".mining-", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def read(path: Path) -> Optional[dict[str, Any]]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def remove(path: Path) -> None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
