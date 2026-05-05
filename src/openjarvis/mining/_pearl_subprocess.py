"""Subprocess launcher for the cpu-pearl provider.

Manages two coordinated subprocesses:

- ``pearl-gateway`` — Pearl's Python JSON-RPC service that talks to ``pearld``
  and brokers shares between the miner and the network.
- ``openjarvis.mining._miner_loop_main`` — this repo's miner loop that polls
  the gateway and runs ``pearl_mining.mine()``.

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
    ) -> None:
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.metrics_port = metrics_port
        self.pearld_rpc_url = pearld_rpc_url
        self.pearld_rpc_user = pearld_rpc_user
        self.pearld_rpc_password = pearld_rpc_password
        self.wallet_address = wallet_address
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._handles: _ProcessHandles | None = None

    def start(self, *, m: int, n: int, k: int, rank: int) -> None:
        """Spawn gateway and miner-loop subprocesses."""
        env = self._build_gateway_env()

        # Spawn pearl-gateway first. ``pearl-gateway`` is the console-script
        # entry point exposed by the pearl_gateway package's pyproject.toml.
        gateway_log = (self.log_dir / "pearl-gateway.log").open("a", buffering=1)
        logger.info(
            "[cpu-pearl] starting pearl-gateway on %s:%d (metrics %d)",
            self.gateway_host,
            self.gateway_port,
            self.metrics_port,
        )
        gateway = subprocess.Popen(
            ["pearl-gateway"],
            env=env,
            stdout=gateway_log,
            stderr=subprocess.STDOUT,
        )

        # Spawn miner-loop pointed at the gateway.
        miner_log = (self.log_dir / "cpu-pearl-miner.log").open("a", buffering=1)
        logger.info(
            "[cpu-pearl] starting miner-loop (m=%d n=%d k=%d rank=%d)",
            m,
            n,
            k,
            rank,
        )
        miner_loop = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "openjarvis.mining._miner_loop_main",
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
                        "[cpu-pearl] subprocess %d did not exit after %.1fs; SIGKILL",
                        proc.pid,
                        grace,
                    )
                    proc.kill()
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

        Env-var names here are best-effort; Task 7 verifies them against
        pearl-gateway's actual ``config.py``.
        """
        env = dict(os.environ)
        env.update(
            {
                "PEARL_GATEWAY_HOST": self.gateway_host,
                "PEARL_GATEWAY_PORT": str(self.gateway_port),
                "PEARL_GATEWAY_METRICS_PORT": str(self.metrics_port),
                "PEARLD_RPC_URL": self.pearld_rpc_url,
                "PEARLD_RPC_USER": self.pearld_rpc_user,
                "PEARLD_RPC_PASSWORD": self.pearld_rpc_password,
                "PEARLD_MINING_ADDRESS": self.wallet_address,
                "MINER_RPC_TRANSPORT": "tcp",
            }
        )
        return env
