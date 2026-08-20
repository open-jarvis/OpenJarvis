"""Subprocess launcher for Pearl providers.

Manages two coordinated subprocesses:

- ``pearl-gateway`` — Pearl's Python JSON-RPC service that talks to ``pearld``
  and brokers shares between the miner and the network.
- a provider-selected miner-loop module that polls the gateway, mines, and
  submits proofs.

Lifecycle is in-memory: while this object lives, both subprocesses live. The
provider holds it; the sidecar JSON records PIDs for crash recovery and
``mine doctor`` introspection.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# How long to wait after SIGTERM before SIGKILL. The miner loop is held to a
# tight budget because it does no network IO of consequence; the gateway gets
# a bit longer to flush state to pearld.
_GATEWAY_TERMINATE_GRACE_SECONDS = 5.0
_MINER_LOOP_TERMINATE_GRACE_SECONDS = 2.0


@dataclass(slots=True)
class _ProcessHandles:
    gateway: subprocess.Popen
    miner_loop: subprocess.Popen


class PearlSubprocessLauncher:
    """Spawn and tear down the gateway + miner-loop pair as a unit."""

    def __init__(
        self,
        *,
        gateway_host: str,
        gateway_port: int,
        metrics_port: int,
        pearld_rpc_url: str,
        pearld_rpc_user: str,
        pearld_rpc_password: str,
        wallet_address: str,
        log_dir: Path,
        provider_id: str = "cpu-pearl",
        miner_module: str = "openjarvis.mining._miner_loop_main",
    ) -> None:
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.metrics_port = metrics_port
        self.pearld_rpc_url = pearld_rpc_url
        self.pearld_rpc_user = pearld_rpc_user
        self.pearld_rpc_password = pearld_rpc_password
        self.wallet_address = wallet_address
        self.log_dir = Path(log_dir)
        self.provider_id = provider_id
        self.miner_module = miner_module
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._handles: _ProcessHandles | None = None

    def start(self, *, m: int, n: int, k: int, rank: int) -> None:
        """Spawn gateway and miner-loop subprocesses."""
        if self._handles is not None:
            raise RuntimeError(
                "PearlSubprocessLauncher already started; "
                "call stop() before starting again"
            )
        env = self._build_gateway_env()

        # Spawn pearl-gateway first. ``pearl-gateway`` is the console-script
        # entry point exposed by the pearl_gateway package's pyproject.toml.
        logger.info(
            "[%s] starting pearl-gateway on %s:%d (metrics %d)",
            self.provider_id,
            self.gateway_host,
            self.gateway_port,
            self.metrics_port,
        )
        # The pearl-gateway CLI takes a positional command argument (start|stop|
        # status|version) — see pearl/miner/pearl-gateway/src/pearl_gateway/cli.py.
        gateway_log_path = self.log_dir / "pearl-gateway.log"
        with gateway_log_path.open("a", buffering=1) as gateway_log:
            gateway = subprocess.Popen(
                ["pearl-gateway", "start"],
                env=env,
                stdout=gateway_log,
                stderr=subprocess.STDOUT,
            )
        # gateway_log closes here; the child holds its own fd

        # Spawn miner-loop pointed at the gateway.
        logger.info(
            "[%s] starting miner-loop %s (m=%d n=%d k=%d rank=%d)",
            self.provider_id,
            self.miner_module,
            m,
            n,
            k,
            rank,
        )
        miner_log_path = self.log_dir / f"{self.provider_id}-miner.log"
        with miner_log_path.open("a", buffering=1) as miner_log:
            miner_loop = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    self.miner_module,
                    "--gateway-host",
                    self.gateway_host,
                    "--gateway-port",
                    str(self.gateway_port),
                    "--m",
                    str(m),
                    "--n",
                    str(n),
                    "--k",
                    str(k),
                    "--rank",
                    str(rank),
                ],
                stdout=miner_log,
                stderr=subprocess.STDOUT,
            )

        self._handles = _ProcessHandles(gateway=gateway, miner_loop=miner_loop)

    def stop(self) -> None:
        """SIGTERM both subprocesses with bounded waits and SIGKILL fallback.

        Idempotent — calling stop() when already stopped is a no-op.
        """
        if self._handles is None:
            return
        # Stop miner-loop first (it doesn't need to flush state), then gateway.
        for proc, grace in (
            (self._handles.miner_loop, _MINER_LOOP_TERMINATE_GRACE_SECONDS),
            (self._handles.gateway, _GATEWAY_TERMINATE_GRACE_SECONDS),
        ):
            if proc.poll() is None:
                proc.terminate()
                deadline = time.monotonic() + grace
                while time.monotonic() < deadline and proc.poll() is None:
                    time.sleep(0.05)
                if proc.poll() is None:
                    logger.warning(
                        "[%s] subprocess %d did not exit after %.1fs; SIGKILL",
                        self.provider_id,
                        proc.pid,
                        grace,
                    )
                    proc.kill()
                    proc.wait()  # reap the zombie
        self._handles = None

    def is_running(self) -> bool:
        """True iff both subprocesses are alive."""
        if self._handles is None:
            return False
        return (
            self._handles.gateway.poll() is None
            and self._handles.miner_loop.poll() is None
        )

    def pids(self) -> tuple[int, int] | None:
        """Return (gateway_pid, miner_loop_pid), or None if not started."""
        if self._handles is None:
            return None
        return (self._handles.gateway.pid, self._handles.miner_loop.pid)

    def _build_gateway_env(self) -> dict[str, str]:
        """Construct the environment passed to pearl-gateway.

        Env var names verified against
        ``pearl/miner/pearl-gateway/src/pearl_gateway/config.py`` (PearlConfig
        with ``env_prefix="PEARLD_"`` and MinerRpcConfig with
        ``env_prefix="MINER_RPC_"``) and the canonical names in
        ``pearl/miner/conftest.py`` line 281+.

        - PEARLD_*: pearld node RPC connection (PearlConfig)
        - MINER_RPC_*: the JSON-RPC server miners connect to (MinerRpcConfig)
        - METRICS_BIND: a single ``HOST:PORT`` string for the Prometheus
          metrics endpoint (defaults to ``127.0.0.1:9109`` upstream).
        """
        env = dict(os.environ)
        env.update(
            {
                "PEARLD_RPC_URL": self.pearld_rpc_url,
                "PEARLD_RPC_USER": self.pearld_rpc_user,
                "PEARLD_RPC_PASSWORD": self.pearld_rpc_password,
                "PEARLD_MINING_ADDRESS": self.wallet_address,
                "MINER_RPC_TRANSPORT": "tcp",
                "MINER_RPC_HOST": self.gateway_host,
                "MINER_RPC_PORT": str(self.gateway_port),
                "METRICS_BIND": f"{self.gateway_host}:{self.metrics_port}",
            }
        )
        return env
