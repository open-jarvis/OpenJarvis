"""Detection and install hints for the upstream Pearl Python packages.

The cpu-pearl provider depends on three upstream packages from the Pearl
research project:

- ``pearl_mining`` (PyO3 binding to the pure-Rust mining algorithm)
- ``pearl_gateway`` (JSON-RPC bridge to ``pearld``)
- ``miner_base`` (PyTorch reference of NoisyGEMM, used for parity validation)

These are not on PyPI as of 2026-05; the implementation plan covers a
build-from-pin fallback in :func:`build_from_pin` (Task 4). This module is
the single source of truth for "is the user's environment ready?" and is
called from :class:`~openjarvis.mining.cpu_pearl.CpuPearlProvider.detect`
plus ``jarvis mine doctor``.
"""

from __future__ import annotations

import importlib.util
import sys


def _module_importable(name: str) -> bool:
    """True if ``import name`` would succeed in the current environment.

    Checks ``sys.modules`` first (a module already resident is by definition
    importable); falls back to ``importlib.util.find_spec``. The find_spec
    call raises ``ValueError`` for entries in sys.modules that were inserted
    without a populated ``__spec__`` (e.g., test stubs created via
    ``types.ModuleType()``). We treat that as "available" — sys.modules
    presence implies importable.
    """
    if name in sys.modules:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except ValueError:
        return False


def pearl_packages_available() -> bool:
    """All three Pearl Python packages importable.

    Returns ``False`` if any are missing. Use :func:`install_hint` to
    surface the next step to the user.
    """
    return all(
        _module_importable(m) for m in ("pearl_mining", "pearl_gateway", "miner_base")
    )


def install_hint() -> str:
    """Human-readable instruction for installing the Pearl packages.

    Today (no PyPI publication) we point at the optional extra. When Pearl
    publishes wheels, the message stays correct because the extra still works.
    """
    return (
        "install with `uv sync --extra mining-pearl-cpu`. "
        "If Pearl wheels are not on PyPI yet, see "
        "tools/pearl-reference-oracle/README.md for the build-from-pin path."
    )
