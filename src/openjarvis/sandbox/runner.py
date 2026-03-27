"""Container runner and sandboxed agent wrapper.

``ContainerRunner`` manages Docker container lifecycle for sandboxed
agent execution.  ``SandboxedAgent`` wraps any ``BaseAgent`` to run
inside a container, following the ``GuardrailsEngine`` wrapper pattern.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import uuid
from typing import Any, Dict, List, Optional

from openjarvis.agents._stubs import AgentContext, AgentResult, BaseAgent
from openjarvis.core.events import EventBus
from openjarvis.core.types import ToolResult
from openjarvis.engine._stubs import InferenceEngine

logger = logging.getLogger(__name__)

# Sentinel markers (same as ClaudeCodeAgent)
_OUTPUT_START = "---OPENJARVIS_OUTPUT_START---"
_OUTPUT_END = "---OPENJARVIS_OUTPUT_END---"


class ContainerRunner:
    """Manages Docker container lifecycle for sandboxed execution.

    Parameters
    ----------
    image:
        Docker image to run.  Defaults to ``openjarvis-sandbox:latest``.
    timeout:
        Maximum execution time in seconds.
    mount_allowlist_path:
        Path to a JSON mount-allowlist file.
    max_concurrent:
        Maximum number of concurrent containers.
    runtime:
        Container runtime binary name (``docker`` or ``podman``).
    """

    DEFAULT_IMAGE = "openjarvis-sandbox:latest"
    DEFAULT_TIMEOUT = 300

    def __init__(
        self,
        *,
        image: str = "",
        timeout: int = 0,
        mount_allowlist_path: str = "",
        max_concurrent: int = 5,
        runtime: str = "docker",
    ) -> None:
        self._image = image or self.DEFAULT_IMAGE
        self._timeout = timeout or self.DEFAULT_TIMEOUT
        self._mount_allowlist_path = mount_allowlist_path
        self._max_concurrent = max_concurrent
        self._runtime = runtime
        self._allowlist = self._load_allowlist()

    def _load_allowlist(self):
        """Load mount allowlist if configured."""
        if not self._mount_allowlist_path:
            from openjarvis.sandbox.mount_security import (
                MountAllowlist,
            )

            return MountAllowlist()
        from openjarvis.sandbox.mount_security import (
            load_mount_allowlist,
        )

        return load_mount_allowlist(self._mount_allowlist_path)

    def _check_runtime(self) -> str:
        """Return the full path to the container runtime binary.

        Raises :class:`RuntimeError` if the runtime is not found.
        """
        path = shutil.which(self._runtime)
        if path is None:
            raise RuntimeError(
                f"Container runtime '{self._runtime}' not found. "
                "Install Docker or Podman."
            )
        return path

    def _validate_mounts(
        self,
        mounts: Optional[List[str]],
    ) -> List[str]:
        """Validate mounts against the allowlist."""
        if not mounts:
            return []
        from openjarvis.sandbox.mount_security import (
            validate_mounts,
        )

        return validate_mounts(mounts, self._allowlist)

    def _build_docker_args(
        self,
        container_name: str,
        mounts: List[str],
        env: Optional[Dict[str, str]],
    ) -> List[str]:
        """Build the ``docker run`` argument list."""
        runtime = self._check_runtime()
        args = [
            runtime,
            "run",
            "--rm",
            "--name",
            container_name,
            "--label",
            "openjarvis-sandbox=true",
            "--network",
            "none",
            "-i",
        ]

        for mount in mounts:
            args.extend(["-v", f"{mount}:{mount}:ro"])

        if env:
            for key, value in env.items():
                args.extend(["-e", f"{key}={value}"])

        args.append(self._image)
        return args

    def run(
        self,
        input_data: Dict[str, Any],
        *,
        workspace: str = "",
        mounts: Optional[List[str]] = None,
        secrets: Optional[Dict[str, str]] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Spawn a container, send input, parse output.

        Parameters
        ----------
        input_data:
            JSON-serializable payload sent to the container's stdin.
        workspace:
            Working directory inside the container.
        mounts:
            Host paths to bind-mount (read-only).
        secrets:
            Key-value pairs injected into input (not env vars).
        env:
            Environment variables for the container.

        Returns
        -------
        dict
            Parsed JSON output from the container.
        """
        validated_mounts = self._validate_mounts(mounts)

        container_name = f"oj-sandbox-{uuid.uuid4().hex[:12]}"

        # Build request payload
        payload = dict(input_data)
        if secrets:
            payload["_secrets"] = secrets
        if workspace:
            payload["_workspace"] = workspace

        args = self._build_docker_args(
            container_name,
            validated_mounts,
            env,
        )

        try:
            proc = subprocess.run(
                args,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            # Kill the container on timeout
            self.stop(container_name)
            return {
                "content": (f"Container timed out after {self._timeout}s."),
                "error": True,
                "error_type": "timeout",
            }

        if proc.returncode != 0:
            stderr = proc.stderr.strip() if proc.stderr else ""
            logger.error(
                "Container %s exited %d: %s",
                container_name,
                proc.returncode,
                stderr,
            )
            return {
                "content": f"Container failed: {stderr}",
                "error": True,
                "returncode": proc.returncode,
            }

        return self._parse_output(proc.stdout)

    @staticmethod
    def _parse_output(stdout: str) -> Dict[str, Any]:
        """Extract sentinel-wrapped JSON from container stdout."""
        start = stdout.find(_OUTPUT_START)
        end = stdout.find(_OUTPUT_END)

        if start == -1 or end == -1:
            return {"content": stdout.strip()}

        json_str = stdout[start + len(_OUTPUT_START) : end].strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            return {"content": stdout.strip(), "parse_error": True}

    def stop(self, container_name: str) -> None:
        """Force-stop a running container."""
        try:
            runtime = shutil.which(self._runtime) or self._runtime
            subprocess.run(
                [runtime, "rm", "-f", container_name],
                capture_output=True,
                timeout=30,
            )
        except Exception:
            logger.debug(
                "Failed to stop container %s",
                container_name,
                exc_info=True,
            )

    def cleanup_orphans(self) -> None:
        """Remove orphaned sandbox containers."""
        try:
            runtime = shutil.which(self._runtime) or self._runtime
            result = subprocess.run(
                [
                    runtime,
                    "ps",
                    "-aq",
                    "--filter",
                    "label=openjarvis-sandbox=true",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            container_ids = result.stdout.strip().split()
            if container_ids:
                subprocess.run(
                    [runtime, "rm", "-f", *container_ids],
                    capture_output=True,
                    timeout=30,
                )
                logger.info(
                    "Cleaned up %d orphaned containers",
                    len(container_ids),
                )
        except Exception:
            logger.debug(
                "Orphan cleanup failed",
                exc_info=True,
            )


class SandboxedAgent(BaseAgent):
    """Transparent wrapper that runs any BaseAgent in a container.

    Follows the ``GuardrailsEngine`` wrapper pattern — the wrapped
    agent's configuration is serialized and sent to the container.
    """

    agent_id = "sandboxed"
    accepts_tools = False

    def __init__(
        self,
        agent: BaseAgent,
        runner: ContainerRunner,
        *,
        engine: Optional[InferenceEngine] = None,
        model: str = "",
        workspace: str = "",
        mounts: Optional[List[str]] = None,
        secrets: Optional[Dict[str, str]] = None,
        bus: Optional[EventBus] = None,
    ) -> None:
        # Use the wrapped agent's engine/model for BaseAgent init
        _engine = engine or getattr(agent, "_engine", None)
        _model = model or getattr(agent, "_model", "")
        super().__init__(
            _engine,  # type: ignore[arg-type]
            _model,
            bus=bus,
        )
        self._wrapped_agent = agent
        self._runner = runner
        self._workspace = workspace
        self._mounts = mounts or []
        self._secrets = secrets or {}

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Delegate execution to the container runner."""
        self._emit_turn_start(input)

        input_data = {
            "prompt": input,
            "agent_id": self._wrapped_agent.agent_id,
            "model": getattr(self._wrapped_agent, "_model", ""),
        }

        result = self._runner.run(
            input_data,
            workspace=self._workspace,
            mounts=self._mounts,
            secrets=self._secrets,
        )

        content = result.get("content", "")
        error = result.get("error", False)

        # Parse tool results if present
        raw_tools = result.get("tool_results", [])
        tool_results = [
            ToolResult(
                tool_name=tr.get("tool_name", "unknown"),
                content=tr.get("content", ""),
                success=tr.get("success", True),
            )
            for tr in raw_tools
        ]

        self._emit_turn_end(turns=1, error=error)
        return AgentResult(
            content=content,
            tool_results=tool_results,
            turns=1,
            metadata=result.get("metadata", {}),
        )


__all__ = ["ContainerRunner", "SandboxedAgent"]
