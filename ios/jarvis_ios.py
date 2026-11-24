"""iPadOS (a-Shell) launcher for OpenJarvis.

Mocks native C/Rust/Swift modules that cannot be compiled or imported inside
the a-Shell sandbox (``zeus_apple_silicon``, ``apple_fm_sdk``, ``psutil``) and
delegates CLI execution to ``openjarvis.cli.main``.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path


def _make_zeus_mock() -> types.ModuleType:
    mod = types.ModuleType("zeus_apple_silicon")

    class AppleEnergyMetrics:
        cpu_total_mj: float = 0.0
        gpu_mj: float = 0.0
        ane_mj: float = 0.0
        dram_mj: float = 0.0
        package_mj: float = 0.0

    class AppleEnergyMonitor:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def begin_window(self, name: str = "default") -> None:
            pass

        def end_window(self, name: str = "default") -> AppleEnergyMetrics:
            return AppleEnergyMetrics()

        def get_metrics(self) -> AppleEnergyMetrics:
            return AppleEnergyMetrics()

    mod.AppleEnergyMetrics = AppleEnergyMetrics  # type: ignore[attr-defined]
    mod.AppleEnergyMonitor = AppleEnergyMonitor  # type: ignore[attr-defined]
    return mod


def _make_apple_fm_mock() -> types.ModuleType:
    mod = types.ModuleType("apple_fm_sdk")

    class LanguageModelError(Exception):
        pass

    class GuardrailViolationError(LanguageModelError):
        pass

    class ContextWindowExceededError(LanguageModelError):
        pass

    class GenerationOptions:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.kwargs = kwargs

    class SystemLanguageModel:
        is_available: bool = False

        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

    class LanguageModelSession:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def respond(self, prompt: str, **kwargs: object) -> str:
            raise RuntimeError(
                "apple_fm_sdk is mocked on iPadOS; route requests through "
                "the AskAFM HTTP bridge at http://127.0.0.1:8085."
            )

    mod.LanguageModelError = LanguageModelError  # type: ignore[attr-defined]
    mod.GuardrailViolationError = GuardrailViolationError  # type: ignore[attr-defined]
    mod.ContextWindowExceededError = ContextWindowExceededError  # type: ignore[attr-defined]
    mod.GenerationOptions = GenerationOptions  # type: ignore[attr-defined]
    mod.SystemLanguageModel = SystemLanguageModel  # type: ignore[attr-defined]
    mod.LanguageModelSession = LanguageModelSession  # type: ignore[attr-defined]
    return mod


def _make_psutil_mock() -> types.ModuleType:
    mod = types.ModuleType("psutil")

    class Error(Exception):
        pass

    class NoSuchProcess(Error):
        pass

    class AccessDenied(Error):
        pass

    class ZombieProcess(Error):
        pass

    class _VirtualMemory:
        total: int = 8 * 1024 * 1024 * 1024
        available: int = 4 * 1024 * 1024 * 1024
        percent: float = 50.0

    class Process:
        def __init__(self, pid: int | None = None) -> None:
            self.pid = pid or os.getpid()

        def status(self) -> str:
            return "running"

        def create_time(self) -> float:
            return 0.0

        def cmdline(self) -> list[str]:
            return []

        def children(self, recursive: bool = False) -> list["Process"]:
            return []

        def terminate(self) -> None:
            pass

        def kill(self) -> None:
            pass

        def is_running(self) -> bool:
            return False

    mod.Error = Error  # type: ignore[attr-defined]
    mod.NoSuchProcess = NoSuchProcess  # type: ignore[attr-defined]
    mod.AccessDenied = AccessDenied  # type: ignore[attr-defined]
    mod.ZombieProcess = ZombieProcess  # type: ignore[attr-defined]
    mod.STATUS_ZOMBIE = "zombie"  # type: ignore[attr-defined]
    mod.Process = Process  # type: ignore[attr-defined]
    mod.wait_procs = lambda procs, timeout=None: ([], [])  # type: ignore[attr-defined]
    mod.pid_exists = lambda pid: False  # type: ignore[attr-defined]
    mod.cpu_count = lambda logical=True: os.cpu_count() or 1  # type: ignore[attr-defined]
    mod.virtual_memory = lambda: _VirtualMemory()  # type: ignore[attr-defined]
    return mod


def install_ios_mocks(*, force: bool = False) -> list[str]:
    """Install mock modules for native dependencies unavailable in a-Shell."""
    factories = {
        "zeus_apple_silicon": _make_zeus_mock,
        "apple_fm_sdk": _make_apple_fm_mock,
        "psutil": _make_psutil_mock,
    }
    installed: list[str] = []
    for name, factory in factories.items():
        if force or name not in sys.modules:
            sys.modules[name] = factory()
            installed.append(name)
    return installed


def configure_ios_environment() -> None:
    """Default ``OPENJARVIS_CONFIG`` to ``~/Library/openjarvis/config.toml``."""
    ios_config = Path.home() / "Library" / "openjarvis" / "config.toml"
    if "OPENJARVIS_CONFIG" not in os.environ and ios_config.exists():
        os.environ["OPENJARVIS_CONFIG"] = str(ios_config)


def main(argv: list[str] | None = None) -> None:
    """Bootstrap iOS mocks and invoke the OpenJarvis CLI."""
    configure_ios_environment()
    install_ios_mocks()

    if argv is not None:
        sys.argv = ["jarvis", *argv]

    from openjarvis.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
