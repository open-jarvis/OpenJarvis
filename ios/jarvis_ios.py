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


def configure_ios_environment(repo_root: Path | str | None = None) -> None:
    """Default ``OPENJARVIS_CONFIG`` to ``~/Library/openjarvis/config.toml`` or ``ios/config.toml``."""
    if os.environ.get("OPENJARVIS_CONFIG"):
        return
    ios_config = Path.home() / "Library" / "openjarvis" / "config.toml"
    if ios_config.is_file():
        os.environ["OPENJARVIS_CONFIG"] = str(ios_config)
        return
    src_dir = _find_repo_src(repo_root)
    if src_dir is not None:
        repo_cfg = src_dir.parent / "ios" / "config.toml"
        if repo_cfg.is_file():
            os.environ["OPENJARVIS_CONFIG"] = str(repo_cfg)


def _find_repo_src(repo_root: Path | str | None = None) -> Path | None:
    """Locate the ``src`` directory containing ``openjarvis``."""
    candidates: list[Path] = []
    if repo_root is not None:
        candidates.append(Path(repo_root))

    env_root = os.environ.get("OPENJARVIS_REPO_ROOT")
    if env_root:
        candidates.append(Path(env_root).expanduser())

    marker = Path(__file__).resolve().with_name("repo_root.txt")
    if marker.is_file():
        saved = marker.read_text(encoding="utf-8").strip()
        if saved:
            candidates.append(Path(saved).expanduser())

    # Works when running directly from <repo>/ios/jarvis_ios.py
    candidates.append(Path(__file__).resolve().parents[1])
    candidates.append(Path.cwd())
    docs = Path.home() / "Documents"
    candidates.extend([docs / "OpenJarvis", docs / "GitHub" / "OpenJarvis"])

    seen: set[Path] = set()
    for root in candidates:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        src_dir = resolved / "src"
        if (src_dir / "openjarvis" / "__init__.py").is_file():
            return src_dir
    return None


def configure_ios_pythonpath(repo_root: Path | str | None = None) -> Path | None:
    """Ensure ``<repo_root>/src`` is on ``sys.path`` so ``openjarvis`` imports work in a-Shell."""
    src_dir = _find_repo_src(repo_root)
    if src_dir is not None:
        src_str = str(src_dir)
        if src_str not in sys.path:
            sys.path.insert(0, src_str)
    return src_dir


def _patch_apple_fm_default_host() -> str:
    """Ensure ``apple_fm`` and ``AskAFM`` defaults are used on iOS."""
    target_host = os.environ.get("OPENJARVIS_APPLE_FM_HOST", "http://127.0.0.1:8085")
    try:
        from openjarvis.core import config as cfg_mod

        if hasattr(cfg_mod, "load_config"):
            orig_load = cfg_mod.load_config

            def _ios_load_config(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
                cfg = orig_load(*args, **kwargs)
                if cfg.engine.default == "llamacpp":
                    cfg.engine.default = "apple_fm"
                if cfg.intelligence.default_model == "AskAFMLocal":
                    cfg.intelligence.default_model = "AskAFM"
                if os.environ.get("OPENJARVIS_APPLE_FM_HOST"):
                    cfg.engine.apple_fm.host = os.environ["OPENJARVIS_APPLE_FM_HOST"]
                elif cfg.engine.apple_fm.host == "http://localhost:8079":
                    cfg.engine.apple_fm.host = target_host
                return cfg

            cfg_mod.load_config = _ios_load_config  # type: ignore[assignment]
    except Exception:
        pass
    return target_host


def _maybe_start_inline_bridge(target_host: str) -> object | None:
    """Start an in-process AskAFM HTTP bridge if none is listening yet."""
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "version", "config"):
        return None

    import urllib.request
    from urllib.parse import urlparse

    parsed = urlparse(target_host)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8085

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/v1/models", timeout=0.4) as resp:
            if resp.status == 200:
                return None
    except Exception:
        pass

    try:
        import importlib.util
        import threading
        from http.server import ThreadingHTTPServer

        server_path = Path(__file__).resolve().with_name("jarvis_server.py")
        spec = importlib.util.spec_from_file_location("jarvis_server", server_path)
        if spec is None or spec.loader is None:
            return None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        srv = ThreadingHTTPServer((host, port), mod.JarvisBridgeHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv
    except Exception:
        return None


def main(argv: list[str] | None = None) -> None:
    """Bootstrap iOS mocks and invoke the OpenJarvis CLI."""
    configure_ios_pythonpath()
    configure_ios_environment()
    install_ios_mocks()

    if argv is not None:
        sys.argv = ["jarvis", *argv]

    target_host = _patch_apple_fm_default_host()
    inline_srv = _maybe_start_inline_bridge(target_host)

    from openjarvis.cli import main as cli_main

    try:
        cli_main()
    finally:
        if inline_srv is not None:
            try:
                inline_srv.shutdown()  # type: ignore[attr-defined]
                inline_srv.server_close()  # type: ignore[attr-defined]
            except Exception:
                pass


if __name__ == "__main__":
    main()
