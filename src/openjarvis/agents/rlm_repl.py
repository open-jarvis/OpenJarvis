"""Sandboxed REPL environment for the RLM agent.

Provides a persistent Python namespace with injected helper functions
(``llm_query``, ``llm_batch``, ``FINAL``, ``FINAL_VAR``) that the RLM
agent's generated code uses to decompose context and make recursive
sub-LM calls.
"""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, Callable, Dict, List, Optional

# Safe stdlib modules pre-injected into the REPL namespace
_SAFE_MODULES = [
    "json",
    "re",
    "math",
    "collections",
    "itertools",
    "functools",
    "textwrap",
    "string",
    "copy",
    "datetime",
]

# Patterns blocked for security
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


class RLMRepl:
    """Sandboxed Python REPL with persistent namespace for the RLM agent.

    Parameters
    ----------
    llm_query_fn:
        Callback invoked when REPL code calls ``llm_query(prompt)``.
    llm_batch_fn:
        Callback invoked when REPL code calls ``llm_batch(prompts)``.
    max_output_chars:
        Maximum characters captured from stdout per execution.
    """

    def __init__(
        self,
        llm_query_fn: Optional[Callable[[str], str]] = None,
        llm_batch_fn: Optional[Callable[[List[str]], List[str]]] = None,
        tool_call_fn: Optional[Callable[[str, Dict[str, Any]], str]] = None,
        tool_arg_names: Optional[Dict[str, Optional[str]]] = None,
        *,
        max_output_chars: int = 10000,
    ) -> None:
        self._max_output_chars = max_output_chars
        self._terminated = False
        self._final_value: Any = None
        self._tool_call_fn = tool_call_fn

        # Build namespace
        self._namespace: Dict[str, Any] = {}

        # Inject safe stdlib modules
        for mod_name in _SAFE_MODULES:
            try:
                import importlib

                self._namespace[mod_name] = importlib.import_module(mod_name)
            except ImportError:
                pass

        # answer dict — code can set answer["ready"] = True, answer["value"] = ...
        self._namespace["answer"] = {"ready": False, "value": None}

        # Inject FINAL / FINAL_VAR
        self._namespace["FINAL"] = self._final
        self._namespace["FINAL_VAR"] = self._final_var

        # Inject llm_query / llm_batch
        if llm_query_fn is not None:
            self._namespace["llm_query"] = llm_query_fn
        if llm_batch_fn is not None:
            self._namespace["llm_batch"] = llm_batch_fn
        if tool_call_fn is not None:
            self._namespace["tool_call"] = self._tool_call

            # Expose each tool as a direct Python helper (e.g.
            # file_read(path="...")) so the model does not need to invent
            # pseudo-tool syntax or fall back to blocked file I/O.
            for tool_name, primary_arg in (tool_arg_names or {}).items():
                self._namespace[tool_name] = self._make_tool_wrapper(
                    tool_name,
                    primary_arg,
                )

    # ------------------------------------------------------------------
    # Termination helpers
    # ------------------------------------------------------------------

    def _final(self, value: Any) -> None:
        """Mark the REPL as terminated with a final answer."""
        self._terminated = True
        self._final_value = value

    def _final_var(self, var_name: str) -> None:
        """Mark the REPL as terminated, using a namespace variable as the answer."""
        value = self._namespace.get(var_name)
        self._terminated = True
        self._final_value = value

    @property
    def is_terminated(self) -> bool:
        """Check if FINAL/FINAL_VAR was called or answer["ready"] is True."""
        if self._terminated:
            return True
        answer = self._namespace.get("answer", {})
        if isinstance(answer, dict) and answer.get("ready"):
            return True
        return False

    @property
    def final_answer(self) -> Any:
        """Return the termination value."""
        if self._terminated:
            return self._final_value
        answer = self._namespace.get("answer", {})
        if isinstance(answer, dict) and answer.get("ready"):
            return answer.get("value")
        return None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _tool_call(self, tool_name: str, *args: Any, **kwargs: Any) -> str:
        """Execute an injected OpenJarvis tool from within the REPL.

        Supported forms:
        - ``tool_call("file_read", {"path": "foo.txt"})``
        - ``tool_call("file_read", path="foo.txt")``
        """
        if self._tool_call_fn is None:
            raise RuntimeError("tool_call is not available in this REPL")

        if args:
            if len(args) != 1 or kwargs:
                raise TypeError(
                    "tool_call expects either a single dict argument or keyword args"
                )
            if not isinstance(args[0], dict):
                raise TypeError("tool_call positional argument must be a dict")
            params = dict(args[0])
        else:
            params = dict(kwargs)

        return self._tool_call_fn(tool_name, params)

    def _make_tool_wrapper(
        self,
        tool_name: str,
        primary_arg: Optional[str],
    ) -> Callable[..., str]:
        """Return a Python helper that dispatches to ``tool_call``."""

        def _wrapper(*args: Any, **kwargs: Any) -> str:
            if kwargs:
                params = dict(kwargs)
            elif len(args) == 1 and primary_arg is not None:
                params = {primary_arg: args[0]}
            elif len(args) == 1 and isinstance(args[0], dict):
                params = dict(args[0])
            elif not args:
                params = {}
            else:
                raise TypeError(
                    f"{tool_name} expects keyword args or a single {primary_arg!r} argument"
                )
            return self._tool_call(tool_name, params)

        _wrapper.__name__ = tool_name
        return _wrapper

    def security_check(self, code: str) -> Optional[str]:
        """Check code for dangerous patterns. Returns error message or None."""
        for pattern in _BLOCKED_PATTERNS:
            if pattern in code:
                return f"Blocked: code contains prohibited pattern '{pattern}'"
        return None

    def execute(self, code: str) -> str:
        """Execute *code* in the persistent namespace and return captured stdout.

        Raises are caught and returned as error strings.
        """
        # Security check
        violation = self.security_check(code)
        if violation is not None:
            return f"Error: {violation}"

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, self._namespace)  # noqa: S102
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            return error_msg

        output = stdout_buf.getvalue()
        err_output = stderr_buf.getvalue()
        if err_output:
            output += ("\n" if output else "") + err_output

        # Truncate if needed
        if len(output) > self._max_output_chars:
            output = output[: self._max_output_chars] + "\n... (output truncated)"

        return output

    # ------------------------------------------------------------------
    # Namespace access
    # ------------------------------------------------------------------

    def set_variable(self, name: str, value: Any) -> None:
        """Set a variable in the REPL namespace."""
        self._namespace[name] = value

    def get_variable(self, name: str) -> Any:
        """Get a variable from the REPL namespace."""
        return self._namespace.get(name)


__all__ = ["RLMRepl"]
