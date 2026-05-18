"""Experimental Apple-GPU Pearl mining provider via PyTorch MPS.

This provider is a correctness-first bridge to upstream Pearl ``miner-base``.
It uses the Apple GPU for the NoisyGEMM matmuls through PyTorch MPS, while
leaving transcript hashing and proof construction on CPU until a native Metal
kernel exists.
"""

from __future__ import annotations

import os
import time

from openjarvis.core.config import HardwareInfo
from openjarvis.core.registry import MinerRegistry

from . import _install
from ._constants import (
    CPU_PEARL_DEFAULT_K,
    DEFAULT_GATEWAY_METRICS_PORT,
    DEFAULT_GATEWAY_RPC_PORT,
    DEFAULT_PEARLD_RPC_URL,
)
from ._pearl_subprocess import PearlSubprocessLauncher
from ._stubs import MiningCapabilities, MiningConfig
from .cpu_pearl import CpuPearlProvider, _log_dir


def _torch_mps_available() -> tuple[bool, str | None]:
    try:
        import torch
    except ImportError:
        return False, "PyTorch is not installed"
    if not torch.backends.mps.is_built():
        return False, "PyTorch was not built with MPS support"
    if not torch.backends.mps.is_available():
        return False, "PyTorch MPS is not available on this host"
    return True, None


class AppleMpsPearlProvider(CpuPearlProvider):
    """Experimental MPS-backed Pearl provider."""

    provider_id = "apple-mps-pearl"

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        if hw.platform != "darwin":
            return MiningCapabilities(
                supported=False,
                reason=f"apple-mps-pearl requires macOS; this host is '{hw.platform}'",
            )
        if hw.gpu is None or hw.gpu.vendor.lower() != "apple":
            return MiningCapabilities(
                supported=False,
                reason="apple-mps-pearl requires an Apple GPU",
            )
        if not _install.pearl_packages_available():
            return MiningCapabilities(
                supported=False,
                reason=(
                    f"Pearl Python packages not installed — {_install.install_hint()}"
                ),
            )
        mps_ok, reason = _torch_mps_available()
        if not mps_ok:
            return MiningCapabilities(supported=False, reason=reason)
        return MiningCapabilities(supported=True)

    async def start(self, config: MiningConfig) -> None:
        """Spawn pearl-gateway and the MPS miner-loop subprocess."""
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
            provider_id=self.provider_id,
            miner_module="openjarvis.mining._mps_miner_loop_main",
        )
        self._launcher.start(
            m=int(extra.get("m", 128)),
            n=int(extra.get("n", 128)),
            k=int(extra.get("k", CPU_PEARL_DEFAULT_K)),
            rank=int(extra.get("rank", 64)),
        )
        self._config = config
        self._started_at = time.time()
        self._write_sidecar()


def ensure_registered() -> None:
    """Idempotently register AppleMpsPearlProvider in MinerRegistry."""
    if MinerRegistry.contains("apple-mps-pearl"):
        return
    MinerRegistry.register_value("apple-mps-pearl", AppleMpsPearlProvider)
