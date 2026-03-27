"""Persistent Python REPL tool — maintains state across calls within a session.

Unlike ``CodeInterpreterTool`` (which runs each snippet in a fresh subprocess),
this tool keeps variables, functions, and imports alive across invocations
within the same session.
"""

from __future__ import annotations

import io
import threading
import time
import uuid
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------

# Layer 1: Pattern blocklist
_BLOCKED_PATTERNS = [
    "os.system",
    "os.popen",
    "subprocess",
    "shutil.rmtree",
    "__import__",
    "open(",
    "ctypes",
    "socket",
    "http.client",
    "urllib",
]

# Layer 2: Restricted builtins — remove dangerous ones
_REMOVED_BUILTINS = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "breakpoint",
    "exit",
    "quit",
    "input",
}

# Layer 3: Safe import allowlist
_SAFE_IMPORT_MODULES = frozenset(
    {
        "math",
        "cmath",
        "decimal",
        "fractions",
        "random",
        "statistics",
        "itertools",
        "functools",
        "operator",
        "collections",
        "string",
        "re",
        "textwrap",
        "datetime",
        "time",
        "calendar",
        "json",
        "csv",
        "copy",
        "dataclasses",
        "enum",
        "typing",
        "heapq",
        "bisect",
        "array",
        "pprint",
        "abc",
        "numbers",
    }
)


def _make_safe_import(allowed: frozenset = _SAFE_IMPORT_MODULES):
    """Return a custom __import__ that only allows safe modules."""
    if isinstance(__builtins__, dict):
        real_import = __builtins__["__import__"]
    else:
        real_import = __builtins__.__import__  # type: ignore[union-attr]

    def _safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
        top_level = name.split(".")[0]
        if top_level not in allowed:
            raise ImportError(
                f"Import of '{name}' is not allowed. "
                f"Allowed modules: {', '.join(sorted(allowed))}"
            )
        return real_import(name, *args, **kwargs)

    return _safe_import


def _make_restricted_builtins() -> Dict[str, Any]:
    """Build a builtins dict with dangerous functions removed."""
    import builtins

    safe = {k: v for k, v in vars(builtins).items() if k not in _REMOVED_BUILTINS}
    safe["__import__"] = _make_safe_import()
    return safe


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class _ReplSession:
    session_id: str
    namespace: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    execution_count: int = 0


# ---------------------------------------------------------------------------
# REPL Tool
# ---------------------------------------------------------------------------


@ToolRegistry.register("repl")
class ReplTool(BaseTool):
    """Persistent Python REPL with session management.

    Parameters
    ----------
    timeout:
        Maximum execution time in seconds per call.
    max_output:
        Maximum characters of captured output.
    max_sessions:
        Maximum concurrent sessions (LRU eviction).
    """

    tool_id = "repl"

    def __init__(
        self,
        timeout: int = 30,
        max_output: int = 10000,
        max_sessions: int = 16,
    ) -> None:
        self._timeout = timeout
        self._max_output = max_output
        self._max_sessions = max_sessions
        self._sessions: Dict[str, _ReplSession] = {}
        self._lock = threading.Lock()

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="repl",
            description=(
                "Execute Python code in a persistent REPL session. "
                "Variables, functions, and imports persist across calls "
                "within the same session."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "Session ID for state persistence. "
                            "Omit to auto-create a new session."
                        ),
                    },
                    "reset": {
                        "type": "boolean",
                        "description": "Reset the session state before execution.",
                    },
                },
                "required": ["code"],
            },
            category="code",
        )

    def execute(self, **params: Any) -> ToolResult:
        code = params.get("code", "")
        session_id = params.get("session_id")
        reset = params.get("reset", False)

        if not code or not code.strip():
            return ToolResult(
                tool_name="repl",
                content="No code provided.",
                success=False,
            )

        # Security pattern check
        for pattern in _BLOCKED_PATTERNS:
            if pattern in code:
                return ToolResult(
                    tool_name="repl",
                    content=f"Blocked: code contains prohibited pattern '{pattern}'",
                    success=False,
                )

        # Resolve session
        session = self._resolve_session(session_id, reset)

        # Execute with timeout
        output, success = self._exec_with_timeout(code, session)

        # Update session metadata
        session.last_used = time.time()
        session.execution_count += 1

        # Truncate output
        if len(output) > self._max_output:
            output = output[: self._max_output] + "\n... (output truncated)"

        return ToolResult(
            tool_name="repl",
            content=output or "(no output)",
            success=success,
            metadata={
                "session_id": session.session_id,
                "execution_count": session.execution_count,
            },
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def _resolve_session(
        self,
        session_id: Optional[str],
        reset: bool = False,
    ) -> _ReplSession:
        """Get or create a session, with LRU eviction at max_sessions."""
        with self._lock:
            if session_id and session_id in self._sessions and not reset:
                session = self._sessions[session_id]
                return session

            if session_id and session_id in self._sessions and reset:
                # Reset existing session
                session = self._sessions[session_id]
                session.namespace = {"__builtins__": _make_restricted_builtins()}
                session.execution_count = 0
                return session

            # Create new session
            sid = session_id or str(uuid.uuid4())

            # LRU eviction if at capacity
            if len(self._sessions) >= self._max_sessions:
                oldest_id = min(
                    self._sessions,
                    key=lambda k: self._sessions[k].last_used,
                )
                del self._sessions[oldest_id]

            session = _ReplSession(
                session_id=sid,
                namespace={"__builtins__": _make_restricted_builtins()},
            )
            self._sessions[sid] = session
            return session

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _exec_with_timeout(
        self,
        code: str,
        session: _ReplSession,
    ) -> tuple[str, bool]:
        """Execute code in a daemon thread with timeout.

        Returns (output, success).
        """
        result_holder: Dict[str, Any] = {"output": "", "success": True}

        def _run() -> None:
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            try:
                with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                    # Try eval first for expression display (REPL-like behavior)
                    try:
                        compiled = compile(code, "<repl>", "eval")
                        val = eval(compiled, session.namespace)  # noqa: S307
                        if val is not None:
                            print(repr(val))  # noqa: T201
                    except SyntaxError:
                        # Not an expression — execute as statements
                        compiled = compile(code, "<repl>", "exec")
                        exec(compiled, session.namespace)  # noqa: S102
            except Exception as exc:
                result_holder["output"] = f"{type(exc).__name__}: {exc}"
                result_holder["success"] = False
                return

            output = stdout_buf.getvalue()
            err = stderr_buf.getvalue()
            if err:
                output += ("\n" if output else "") + err
            result_holder["output"] = output

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=self._timeout)

        if thread.is_alive():
            return (
                f"Execution timed out after {self._timeout} seconds.",
                False,
            )

        return result_holder["output"], result_holder["success"]


__all__ = ["ReplTool"]
