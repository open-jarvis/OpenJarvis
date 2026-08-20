"""ClaudeCodeAgent -- wraps the Claude Agent SDK via Node.js subprocess bridge.

Spawns a Node.js runner process that calls the
``@anthropic-ai/claude-agent-sdk`` package, communicating via JSON over
stdin/stdout with sentinel-delimited output.

The engine parameter is accepted for interface conformance with BaseAgent but
is not used -- inference is handled entirely by the Claude Agent SDK.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.events import EventBus
from openjarvis.core.paths import get_config_dir
from openjarvis.core.registry import AgentRegistry
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import InferenceEngine

logger = logging.getLogger(__name__)

# Sentinel markers for parsing subprocess output
_OUTPUT_START = "---OPENJARVIS_OUTPUT_START---"
_OUTPUT_END = "---OPENJARVIS_OUTPUT_END---"
_RUNNER_FILES = ("package.json", "package-lock.json", "index.mjs")
_RUNNER_DEPENDENCY_FILES = ("package.json", "package-lock.json")
_INSTALL_STATE_FILE = ".openjarvis-install-state"
_RUNNER_THREAD_LOCK = threading.Lock()

# Path to the bundled runner source (relative to this module).
# In editable installs this lives next to this file; in wheel installs
# it is placed under _node_modules/ to avoid namespace package conflicts.
_RUNNER_SRC = Path(__file__).resolve().parent / "claude_code_runner"
if not _RUNNER_SRC.exists():
    _RUNNER_SRC = (
        Path(__file__).resolve().parents[2] / "_node_modules" / "claude_code_runner"
    )


def _native_cli_path(
    node_modules: Path,
    node_platform: str,
    node_arch: str,
    node_libc: str,
) -> Optional[Path]:
    """Return the CLI binary for the resolved Node runtime, if installed."""
    package_suffix = f"{node_platform}-{node_arch}"
    if node_platform == "linux" and node_libc == "musl":
        package_suffix += "-musl"
    executable = "claude.exe" if node_platform == "win32" else "claude"
    candidate = (
        node_modules
        / "@anthropic-ai"
        / f"claude-agent-sdk-{package_suffix}"
        / executable
    )
    return candidate if candidate.is_file() else None


def _node_major_version(node_path: str) -> int:
    """Return the resolved Node.js major version with a clear failure."""
    try:
        proc = subprocess.run(
            [node_path, "--version"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        raw_version = (proc.stdout or proc.stderr or "").strip()
        return int(raw_version.removeprefix("v").split(".", 1)[0])
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Unable to determine the installed Node.js version."
        ) from exc


def _node_runtime_platform(node_path: str) -> tuple[str, str, str]:
    """Return ``(platform, architecture, libc)`` from the Node executable."""
    expression = (
        "JSON.stringify({platform:process.platform,arch:process.arch,"
        "libc:process.platform==='linux'"
        "?(process.report?.getReport?.().header?.glibcVersionRuntime"
        "?'glibc':'musl'):''})"
    )
    try:
        proc = subprocess.run(
            [node_path, "--print", expression],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        runtime = json.loads(proc.stdout)
        values = (runtime["platform"], runtime["arch"], runtime["libc"])
        if not all(isinstance(value, str) and value for value in values[:2]):
            raise ValueError("Node returned incomplete platform information")
        if not isinstance(values[2], str):
            raise ValueError("Node returned invalid libc information")
        return values
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "Unable to determine the installed Node.js platform."
        ) from exc


def _is_lock_contention(exc: OSError) -> bool:
    """Return whether a non-blocking file-lock failure means 'try again'."""
    if os.name == "nt":
        return getattr(exc, "winerror", None) == 33 or exc.errno in {
            errno.EACCES,
            errno.EAGAIN,
        }
    return exc.errno in {errno.EACCES, errno.EAGAIN}


def _atomic_copy_if_changed(source: Path, target: Path) -> None:
    """Copy a bundled runner file without exposing a partial target."""
    try:
        if target.read_bytes() == source.read_bytes():
            return
    except OSError:
        pass

    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _runner_lock(path: Path, timeout: float = 360.0) -> Iterator[None]:
    """Serialize runner updates across threads and OpenJarvis processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout

    with _RUNNER_THREAD_LOCK, path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()

        if os.name == "nt":  # pragma: no cover - exercised on Windows CI
            import msvcrt

            while True:
                lock_file.seek(0)
                try:
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError as exc:
                    if not _is_lock_contention(exc):
                        raise RuntimeError(
                            "Unable to lock the Claude Agent runner cache."
                        ) from exc
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Timed out waiting for another Claude Agent runner install."
                        ) from exc
                    time.sleep(0.1)
            try:
                yield
            finally:
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if not _is_lock_contention(exc):
                        raise RuntimeError(
                            "Unable to lock the Claude Agent runner cache."
                        ) from exc
                    if time.monotonic() >= deadline:
                        raise RuntimeError(
                            "Timed out waiting for another Claude Agent runner install."
                        ) from exc
                    time.sleep(0.1)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


@AgentRegistry.register("claude_code")
class ClaudeCodeAgent(BaseAgent):
    """Agent that wraps the Claude Agent SDK via a Node.js subprocess.

    Spawns a Node.js process running a content-addressed copy of ``index.mjs``
    which imports ``@anthropic-ai/claude-agent-sdk`` and streams agentic
    responses. Results are communicated back via sentinel-delimited JSON on
    stdout.

    The ``engine`` parameter is accepted for BaseAgent interface conformance
    but is not used -- all inference is handled by the Claude Agent SDK.
    """

    agent_id = "claude_code"
    accepts_tools = False
    _default_temperature = 0.7
    _default_max_tokens = 1024

    def __init__(
        self,
        engine: InferenceEngine,
        model: str,
        *,
        bus: Optional[EventBus] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        api_key: str = "",
        workspace: str = "",
        session_id: str = "",
        allowed_tools: Optional[List[str]] = None,
        system_prompt: str = "",
        timeout: int = 300,
    ) -> None:
        super().__init__(
            engine,
            model,
            bus=bus,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._workspace = workspace or os.getcwd()
        self._session_id = session_id
        self._allowed_tools = allowed_tools
        self._system_prompt = system_prompt
        self._timeout = timeout
        self._node_executable = "node"
        self._runner_entrypoint = "index.mjs"

    # ------------------------------------------------------------------
    # Runner management
    # ------------------------------------------------------------------

    def _ensure_runner(self) -> Path:
        """Copy the bundled runner to ``~/.openjarvis/claude_code_runner/``
        and install its locked production dependencies when needed.

        Returns the path to the runner directory.

        Raises :class:`RuntimeError` if Node.js is not available.
        """
        node_path = shutil.which("node")
        if node_path is None:
            raise RuntimeError(
                "ClaudeCodeAgent requires Node.js (>=22). "
                "Install it from https://nodejs.org/ or via your package manager."
            )
        node_major = _node_major_version(node_path)
        if node_major < 22:
            raise RuntimeError(
                f"ClaudeCodeAgent requires Node.js >=22; found v{node_major}."
            )
        npm_path = shutil.which("npm")
        if npm_path is None:
            raise RuntimeError(
                "ClaudeCodeAgent requires npm. Install Node.js (>=22) with npm "
                "from https://nodejs.org/ or via your package manager."
            )
        self._node_executable = node_path
        node_platform, node_arch, node_libc = _node_runtime_platform(node_path)

        missing = [name for name in _RUNNER_FILES if not (_RUNNER_SRC / name).is_file()]
        if missing:
            raise RuntimeError(
                "Bundled claude_code_runner is incomplete; missing: "
                + ", ".join(missing)
            )

        dependency_hash = hashlib.sha256()
        for name in _RUNNER_DEPENDENCY_FILES:
            dependency_hash.update(name.encode("utf-8"))
            dependency_hash.update(b"\0")
            dependency_hash.update((_RUNNER_SRC / name).read_bytes())
            dependency_hash.update(b"\0")
        runtime_fingerprint = "|".join((node_platform, node_arch, node_libc))
        expected_install_state = f"{dependency_hash.hexdigest()}|{runtime_fingerprint}"

        cache_hash = hashlib.sha256(expected_install_state.encode("utf-8"))
        cache_key = cache_hash.hexdigest()[:20]
        entrypoint_hash = hashlib.sha256(
            (_RUNNER_SRC / "index.mjs").read_bytes()
        ).hexdigest()[:20]
        self._runner_entrypoint = f"index.{entrypoint_hash}.mjs"

        config_dir = get_config_dir()
        with _runner_lock(config_dir / ".claude_code_runner.lock"):
            # Dependency/runtime generations are immutable during normal upgrades.
            # Code revisions share their heavyweight node_modules but execute a
            # content-addressed entrypoint, so an active old runner stays untouched.
            dest = config_dir / "claude_code_runner" / cache_key
            dest.mkdir(parents=True, exist_ok=True)

            # The runner is canonical JavaScript, so editable installs and wheels
            # execute the same checked-in file without a first-use TypeScript build.
            for name in _RUNNER_FILES:
                _atomic_copy_if_changed(_RUNNER_SRC / name, dest / name)
            _atomic_copy_if_changed(
                _RUNNER_SRC / "index.mjs",
                dest / self._runner_entrypoint,
            )

            node_modules = dest / "node_modules"
            install_state = dest / _INSTALL_STATE_FILE
            installed_sdk = (
                node_modules / "@anthropic-ai" / "claude-agent-sdk" / "package.json"
            )
            try:
                current_install_state = install_state.read_text(
                    encoding="utf-8"
                ).strip()
            except OSError:
                current_install_state = ""

            if (
                not node_modules.is_dir()
                or not installed_sdk.is_file()
                or _native_cli_path(
                    node_modules,
                    node_platform,
                    node_arch,
                    node_libc,
                )
                is None
                or current_install_state != expected_install_state
            ):
                logger.info("Installing claude_code_runner dependencies...")
                try:
                    subprocess.run(
                        [npm_path, "ci", "--omit=dev", "--include=optional"],
                        cwd=str(dest),
                        check=True,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=300,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError(
                        "Timed out while installing Claude Agent runner dependencies."
                    ) from exc
                except subprocess.CalledProcessError as exc:
                    detail = (exc.stderr or exc.stdout or "").strip()
                    message = "Failed to install Claude Agent runner dependencies"
                    if detail:
                        message += f": {detail}"
                    raise RuntimeError(message) from exc
                if (
                    not installed_sdk.is_file()
                    or _native_cli_path(
                        node_modules,
                        node_platform,
                        node_arch,
                        node_libc,
                    )
                    is None
                ):
                    raise RuntimeError(
                        "Claude Agent SDK installation is incomplete; its platform "
                        "CLI binary is missing. Check npm optional-dependency settings."
                    )
                install_state.write_text(
                    expected_install_state + "\n",
                    encoding="utf-8",
                )

            entrypoint = dest / self._runner_entrypoint
            if not entrypoint.is_file() or entrypoint.stat().st_size == 0:
                raise RuntimeError(
                    f"Claude Agent runner entry point not found at {entrypoint}."
                )

            return dest

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Execute a query via the Claude Agent SDK subprocess.

        Spawns the content-addressed Node.js runner, writes a JSON request to
        stdin, and reads sentinel-delimited JSON output from stdout.
        """
        self._emit_turn_start(input)

        runner_dir = self._ensure_runner()

        # Build the request payload
        request = {
            "prompt": input,
            "api_key": self._api_key,
            "workspace": self._workspace,
            "allowed_tools": self._allowed_tools,
            "system_prompt": self._system_prompt,
            "session_id": self._session_id,
        }

        try:
            proc = subprocess.run(
                [self._node_executable, self._runner_entrypoint],
                cwd=str(runner_dir),
                input=json.dumps(request),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=f"Claude Code agent timed out after {self._timeout}s.",
                turns=1,
                metadata={"error": True, "error_type": "timeout"},
            )

        if proc.returncode != 0:
            stdout = proc.stdout or ""
            if _OUTPUT_START in stdout and _OUTPUT_END in stdout:
                parsed_content, _, parsed_metadata = self._parse_output(stdout)
            else:
                parsed_content, parsed_metadata = "", {}
            stderr = proc.stderr.strip() if proc.stderr else ""
            error_message = (
                parsed_content or stderr or stdout.strip() or "Unknown error"
            )
            logger.error(
                "claude_code_runner exited with code %d: %s",
                proc.returncode,
                error_message,
            )
            self._emit_turn_end(turns=1, error=True)
            metadata = {
                **parsed_metadata,
                "error": True,
                "returncode": proc.returncode,
            }
            return AgentResult(
                content=f"Claude Code agent failed: {error_message}",
                turns=1,
                metadata=metadata,
            )

        # Parse sentinel-delimited output
        content, tool_results, metadata = self._parse_output(proc.stdout)

        self._emit_turn_end(turns=1)
        return AgentResult(
            content=content,
            tool_results=tool_results,
            turns=1,
            metadata=metadata,
        )

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_output(
        stdout: str,
    ) -> tuple[str, list[ToolResult], dict[str, Any]]:
        """Extract the sentinel-wrapped JSON from subprocess stdout.

        Returns ``(content, tool_results, metadata)``.
        """
        start = stdout.find(_OUTPUT_START)
        end = stdout.rfind(_OUTPUT_END)

        if start == -1 or end == -1 or end <= start:
            # No sentinels -- treat entire stdout as plain content
            return stdout.strip(), [], {}

        json_str = stdout[start + len(_OUTPUT_START) : end].strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return stdout.strip(), [], {"parse_error": True}

        content = data.get("content", "")
        raw_tools = data.get("tool_results", [])
        metadata = data.get("metadata", {})

        tool_results = [
            ToolResult(
                tool_name=tr.get("tool_name", "unknown"),
                content=tr.get("content", ""),
                success=tr.get("success", True),
            )
            for tr in raw_tools
        ]

        return content, tool_results, metadata


__all__ = ["ClaudeCodeAgent"]
