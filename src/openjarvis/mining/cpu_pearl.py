"""CPU-based Pearl mining provider (decoupled from inference).

See spec ``docs/design/2026-05-05-apple-silicon-pearl-mining-design.md`` §13
for the full v1 design.

The provider runs Pearl's pure-Rust ``mine()`` function via py-pearl-mining
and runs Pearl's pearl-gateway as a sibling subprocess. Engine-independent:
this provider does not plug into the user's inference stack. The user keeps
using whatever engine they want; mining runs alongside on the CPU.
"""

from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path

from openjarvis.core.config import HardwareInfo
from openjarvis.core.registry import MinerRegistry

from . import _install
from ._constants import (
    CPU_PEARL_DEFAULT_K,
    CPU_PEARL_DEFAULT_M,
    CPU_PEARL_DEFAULT_N,
    CPU_PEARL_DEFAULT_RANK,
    DEFAULT_GATEWAY_METRICS_PORT,
    DEFAULT_GATEWAY_RPC_PORT,
    DEFAULT_PEARLD_RPC_URL,
    SIDECAR_PATH,
)
from ._pearl_subprocess import PearlSubprocessLauncher
from ._stubs import (
    MiningCapabilities,
    MiningConfig,
    MiningProvider,
    MiningStats,
    Sidecar,
)


def _sidecar_path() -> Path:
    """Return the runtime sidecar path. Override in tests."""
    return SIDECAR_PATH


def _log_dir() -> Path:
    """Return the logs directory. Override in tests."""
    return Path.home() / ".openjarvis" / "logs" / "mining"


def _parse_gateway_metrics(text: str, *, provider_id: str) -> MiningStats:
    """Parse Prometheus exposition format into a MiningStats.

    Pearl-gateway exposes counters/gauges that we map onto MiningStats fields.
    Unknown / unparseable metric lines are ignored. If the gateway changes
    metric names, this is the single point of update.

    Expected metrics (verified empirically the first time the gateway runs;
    if names differ, update the dispatch table below):
    - pearl_gateway_shares_submitted_total
    - pearl_gateway_shares_accepted_total
    - pearl_gateway_blocks_found_total
    """
    stats = MiningStats(provider_id=provider_id)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Prometheus line: "metric_name{labels} value [timestamp]"
        # We only care about metrics with no labels (the totals); a labeled
        # variant would still parse — we just take the value of the first
        # whitespace-separated token after the name.
        parts = line.split()
        if len(parts) < 2:
            continue
        name_part = parts[0]
        # strip any "{...}" label suffix
        bare_name = name_part.split("{", 1)[0]
        try:
            value = float(parts[1])
        except ValueError:
            continue
        if bare_name == "pearl_gateway_shares_submitted_total":
            stats.shares_submitted = int(value)
        elif bare_name == "pearl_gateway_shares_accepted_total":
            stats.shares_accepted = int(value)
        elif bare_name == "pearl_gateway_blocks_found_total":
            stats.blocks_found = int(value)
    return stats


class CpuPearlProvider(MiningProvider):
    """v1 cpu-pearl: decoupled CPU mining via py-pearl-mining + pearl-gateway."""

    provider_id = "cpu-pearl"

    def __init__(self) -> None:
        self._launcher: PearlSubprocessLauncher | None = None
        self._config: MiningConfig | None = None
        self._started_at: float | None = None

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        if hw.platform not in {"darwin", "linux"}:
            return MiningCapabilities(
                supported=False,
                reason=(
                    f"v1 cpu-pearl supports darwin/linux only; this host is "
                    f"'{hw.platform}'"
                ),
            )
        if not _install.pearl_packages_available():
            return MiningCapabilities(
                supported=False,
                reason=(
                    f"Pearl Python packages not installed — {_install.install_hint()}"
                ),
            )
        return MiningCapabilities(supported=True)

    async def start(self, config: MiningConfig) -> None:
        """Spawn pearl-gateway and miner-loop subprocesses; write sidecar."""
        extra = dict(config.extra or {})
        password_env = extra.get("pearld_rpc_password_env", "PEARLD_RPC_PASSWORD")
        password = os.environ.get(password_env, "")

        self._launcher = PearlSubprocessLauncher(
            gateway_host=extra.get("gateway_host", "127.0.0.1"),
            gateway_port=int(extra.get("gateway_port", DEFAULT_GATEWAY_RPC_PORT)),
            metrics_port=int(extra.get("metrics_port", DEFAULT_GATEWAY_METRICS_PORT)),
            pearld_rpc_url=extra.get("pearld_rpc_url", DEFAULT_PEARLD_RPC_URL),
            pearld_rpc_user=extra.get("pearld_rpc_user", "rpcuser"),
            pearld_rpc_password=password,
            wallet_address=config.wallet_address,
            log_dir=_log_dir(),
        )
        self._launcher.start(
            m=int(extra.get("m", CPU_PEARL_DEFAULT_M)),
            n=int(extra.get("n", CPU_PEARL_DEFAULT_N)),
            k=int(extra.get("k", CPU_PEARL_DEFAULT_K)),
            rank=int(extra.get("rank", CPU_PEARL_DEFAULT_RANK)),
        )
        self._config = config
        self._started_at = time.time()
        self._write_sidecar()

    async def stop(self) -> None:
        """SIGTERM both subprocesses; remove sidecar."""
        if self._launcher is not None:
            self._launcher.stop()
        self._launcher = None
        self._config = None
        self._started_at = None
        Sidecar.remove(_sidecar_path())

    def is_running(self) -> bool:
        return self._launcher is not None and self._launcher.is_running()

    def stats(self) -> MiningStats:
        if not self.is_running() or self._launcher is None:
            return MiningStats(provider_id=self.provider_id)
        extra = (self._config.extra or {}) if self._config else {}
        host = extra.get("gateway_host", "127.0.0.1")
        metrics_port = int(extra.get("metrics_port", DEFAULT_GATEWAY_METRICS_PORT))
        try:
            with urllib.request.urlopen(
                f"http://{host}:{metrics_port}/metrics", timeout=2.0
            ) as resp:
                text = resp.read().decode()
        except Exception as e:  # noqa: BLE001 — we want any read failure to surface
            return MiningStats(
                provider_id=self.provider_id,
                last_error=f"gateway metrics unreachable: {e}",
            )
        stats = _parse_gateway_metrics(text, provider_id=self.provider_id)
        if self._started_at is not None:
            stats.uptime_seconds = time.time() - self._started_at
        return stats

    def _write_sidecar(self) -> None:
        if self._launcher is None or self._config is None:
            return
        pids = self._launcher.pids() or (None, None)
        extra = self._config.extra or {}
        host = extra.get("gateway_host", "127.0.0.1")
        gw_port = extra.get("gateway_port", DEFAULT_GATEWAY_RPC_PORT)
        mt_port = extra.get("metrics_port", DEFAULT_GATEWAY_METRICS_PORT)
        Sidecar.write(
            _sidecar_path(),
            {
                "provider": self.provider_id,
                "started_at": self._started_at,
                "wallet_address": self._config.wallet_address,
                "gateway_url": f"http://{host}:{gw_port}",
                "metrics_url": f"http://{host}:{mt_port}/metrics",
                "gateway_pid": pids[0],
                "miner_loop_pid": pids[1],
            },
        )


def ensure_registered() -> None:
    """Idempotently register CpuPearlProvider in MinerRegistry.

    Called once at import time from ``openjarvis.mining.__init__``. Tests that
    rely on the autouse registry-clear fixture in ``tests/conftest.py`` must
    call this from a fixture or test body to re-register after the clear.
    """
    if MinerRegistry.contains("cpu-pearl"):
        return
    MinerRegistry.register_value("cpu-pearl", CpuPearlProvider)
