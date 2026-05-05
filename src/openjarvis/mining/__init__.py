# src/openjarvis/mining/__init__.py
"""Pearl mining subsystem.

See spec ``docs/design/2026-05-05-vllm-pearl-mining-integration-design.md``.

Provider modules are soft-imported below — each one fails gracefully if the
``mining-pearl`` (or future ``mining-pearl-mlx`` etc.) extra isn't installed.
"""

from __future__ import annotations

# Re-export the public ABCs and dataclasses for ergonomic imports.
from openjarvis.mining._stubs import (
    MiningCapabilities,
    MiningConfig,
    MiningProvider,
    MiningStats,
    PoolTarget,
    Sidecar,
    SoloTarget,
    SubmitTarget,
)

# Soft-import provider implementations to trigger registration. Each provider
# defines an idempotent ``ensure_registered()`` so it survives the autouse
# registry clear in ``tests/conftest.py``.
try:
    from openjarvis.mining import vllm_pearl  # noqa: F401

    vllm_pearl.ensure_registered()
except ImportError:
    pass

__all__ = [
    "MiningCapabilities",
    "MiningConfig",
    "MiningProvider",
    "MiningStats",
    "PoolTarget",
    "Sidecar",
    "SoloTarget",
    "SubmitTarget",
]
