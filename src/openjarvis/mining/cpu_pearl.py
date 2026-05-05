"""CPU-based Pearl mining provider (decoupled from inference).

See spec ``docs/design/2026-05-05-apple-silicon-pearl-mining-design.md`` §13
for the full v1 design. This file contains the capability-detection portion
of the provider — Task 8. Lifecycle methods (start/stop/is_running/stats)
land in Task 9.

The provider runs Pearl's pure-Rust ``mine()`` function via py-pearl-mining
and runs Pearl's pearl-gateway as a sibling subprocess. Engine-independent:
this provider does not plug into the user's inference stack. The user keeps
using whatever engine they want; mining runs alongside on the CPU.
"""
from __future__ import annotations

from openjarvis.core.config import HardwareInfo

from . import _install
from ._stubs import MiningCapabilities, MiningConfig, MiningProvider, MiningStats


class CpuPearlProvider(MiningProvider):
    provider_id = "cpu-pearl"

    @classmethod
    def detect(cls, hw: HardwareInfo, engine_id: str, model: str) -> MiningCapabilities:
        # v1 platform gate: only darwin and linux. Windows requires more
        # investigation (Pearl's miner Taskfile excludes Windows from the
        # cpu-mining install path even though the algorithm itself is portable).
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
                    f"Pearl Python packages not installed — "
                    f"{_install.install_hint()}"
                ),
            )
        # No engine_id check: cpu-pearl is decoupled from inference.
        # Hashrate estimate is deferred to a calibration during `mine init`
        # — fill in when Task 9 wires the lifecycle.
        return MiningCapabilities(supported=True)

    # ------------------------------------------------------------------
    # Lifecycle stubs — implemented in Task 9
    # ------------------------------------------------------------------

    async def start(self, config: MiningConfig) -> None:
        raise NotImplementedError("CpuPearlProvider.start lands in Task 9")

    async def stop(self) -> None:
        raise NotImplementedError("CpuPearlProvider.stop lands in Task 9")

    def is_running(self) -> bool:
        raise NotImplementedError("CpuPearlProvider.is_running lands in Task 9")

    def stats(self) -> MiningStats:
        raise NotImplementedError("CpuPearlProvider.stats lands in Task 9")
