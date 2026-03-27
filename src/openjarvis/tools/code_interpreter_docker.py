"""Docker-sandboxed code interpreter tool."""

from __future__ import annotations

from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec


@ToolRegistry.register("code_interpreter_docker")
class DockerCodeInterpreterTool(BaseTool):
    """Execute Python code in a disposable Docker container."""

    tool_id = "code_interpreter_docker"

    def __init__(
        self,
        *,
        image: str = "python:3.12-slim",
        timeout: int = 30,
        max_output: int = 10000,
        memory_limit: str = "512m",
        cpu_count: int = 1,
        network_disabled: bool = True,
        pids_limit: int = 100,
    ) -> None:
        self._image = image
        self._timeout = timeout
        self._max_output = max_output
        self._memory_limit = memory_limit
        self._cpu_count = cpu_count
        self._network_disabled = network_disabled
        self._pids_limit = pids_limit

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="code_interpreter_docker",
            description=(
                "Execute Python code in an isolated Docker container. "
                "Provides sandboxed execution with resource limits "
                "(512MB memory, 1 CPU, no network, PID limit 100)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute.",
                    },
                },
                "required": ["code"],
            },
            category="code",
            timeout_seconds=60.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        code = params.get("code", "")
        if not code:
            return ToolResult(
                tool_name="code_interpreter_docker",
                content="No code provided.",
                success=False,
            )

        try:
            import docker
        except ImportError:
            return ToolResult(
                tool_name="code_interpreter_docker",
                content=(
                    "Docker SDK not available. "
                    "Install with: uv sync --extra sandbox-docker"
                ),
                success=False,
            )

        try:
            client = docker.from_env()

            container = client.containers.run(
                self._image,
                ["python", "-c", code],
                detach=True,
                mem_limit=self._memory_limit,
                nano_cpus=self._cpu_count * 10**9,
                network_disabled=self._network_disabled,
                pids_limit=self._pids_limit,
                read_only=True,
                # tmpfs for /tmp so code can write temp files
                tmpfs={"/tmp": "size=64m"},
                stderr=True,
                stdout=True,
            )

            try:
                result = container.wait(timeout=self._timeout)
                exit_code = result.get("StatusCode", -1)
                stdout = container.logs(
                    stdout=True,
                    stderr=False,
                ).decode("utf-8", errors="replace")
                stderr = container.logs(
                    stdout=False,
                    stderr=True,
                ).decode("utf-8", errors="replace")
            finally:
                container.remove(force=True)

            output = stdout
            if stderr:
                output += ("\n" if output else "") + stderr
            if len(output) > self._max_output:
                output = output[: self._max_output] + "\n... (output truncated)"

            return ToolResult(
                tool_name="code_interpreter_docker",
                content=output or "(no output)",
                success=exit_code == 0,
                metadata={"exit_code": exit_code},
            )

        except Exception as exc:
            error_type = type(exc).__name__
            if "timeout" in str(exc).lower() or "read timed out" in str(exc).lower():
                return ToolResult(
                    tool_name="code_interpreter_docker",
                    content=(f"Execution timed out after {self._timeout} seconds."),
                    success=False,
                )
            return ToolResult(
                tool_name="code_interpreter_docker",
                content=f"Docker execution error ({error_type}): {exc}",
                success=False,
            )


__all__ = ["DockerCodeInterpreterTool"]
