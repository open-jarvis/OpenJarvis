"""ClaudeCodeAgent -- wraps the Claude Agent SDK via Node.js subprocess bridge.

Spawns a Node.js runner process that calls the
``@anthropic-ai/claude-agent-sdk`` package, communicating via JSON over
stdin/stdout with sentinel-delimited output.

The engine parameter is accepted for interface conformance with BaseAgent but
is not used -- inference is handled entirely by the Claude Agent SDK.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, List, Optional

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

# Path to the bundled runner source (relative to this module).
# In editable installs this lives next to this file; in wheel installs
# it is placed under _node_modules/ to avoid namespace package conflicts.
_RUNNER_SRC = Path(__file__).resolve().parent / "claude_code_runner"
if not _RUNNER_SRC.exists():
    _RUNNER_SRC = (
        Path(__file__).resolve().parents[2] / "_node_modules" / "claude_code_runner"
    )


@AgentRegistry.register("claude_code")
class ClaudeCodeAgent(BaseAgent):
    """Agent that wraps the Claude Agent SDK via a Node.js subprocess.

    Spawns a Node.js process running ``index.mjs`` which imports
    ``@anthropic-ai/claude-agent-sdk`` and streams agentic responses.  Results
    are communicated back via sentinel-delimited JSON on stdout.

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

    # ------------------------------------------------------------------
    # Runner management
    # ------------------------------------------------------------------

    def _ensure_runner(self) -> Path:
        """Copy the bundled runner to ``~/.openjarvis/claude_code_runner/``
        and install the Agent SDK when it is missing or outdated.

        Returns the path to the runner directory.

        Raises :class:`RuntimeError` if Node.js or npm is not available.
        """
        node_path = shutil.which("node")
        if node_path is None:
            raise RuntimeError(
                "ClaudeCodeAgent requires Node.js (>=22). "
                "Install it from https://nodejs.org/ or via your package manager."
            )
        npm_path = shutil.which("npm")
        if npm_path is None:
            raise RuntimeError(
                "ClaudeCodeAgent requires npm. Install Node.js (>=22) with npm."
            )
        self._node_executable = node_path

        dest = get_config_dir() / "claude_code_runner"
        dest.mkdir(parents=True, exist_ok=True)

        for name in ("package.json", "index.mjs"):
            shutil.copy2(_RUNNER_SRC / name, dest / name)

        package = json.loads((dest / "package.json").read_text(encoding="utf-8"))
        expected_sdk = package["dependencies"]["@anthropic-ai/claude-agent-sdk"]
        installed_package = (
            dest
            / "node_modules"
            / "@anthropic-ai"
            / "claude-agent-sdk"
            / "package.json"
        )
        try:
            installed_sdk = json.loads(
                installed_package.read_text(encoding="utf-8")
            ).get("version")
        except (OSError, json.JSONDecodeError):
            installed_sdk = None

        # Existing caches contain the old CLI-only package, so validate the
        # installed SDK instead of trusting that node_modules merely exists.
        if installed_sdk != expected_sdk:
            logger.info("Installing claude_code_runner dependencies...")
            subprocess.run(
                [npm_path, "install", "--omit=dev", "--include=optional"],
                cwd=str(dest),
                check=True,
                capture_output=True,
                timeout=120,
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

        Spawns ``node index.mjs``, writes a JSON request to stdin, and
        reads sentinel-delimited JSON output from stdout.
        """
        self._emit_turn_start(input)

        runner_dir = self._ensure_runner()

        # Build the request payload
        request = {
            "prompt": input,
            "api_key": self._api_key,
            "workspace": self._workspace,
            "allowed_tools": self._allowed_tools or [],
            "system_prompt": self._system_prompt,
            "session_id": self._session_id,
        }

        try:
            proc = subprocess.run(
                [self._node_executable, "index.mjs"],
                cwd=str(runner_dir),
                input=json.dumps(request),
                capture_output=True,
                text=True,
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
            stderr = proc.stderr.strip() if proc.stderr else "Unknown error"
            logger.error(
                "claude_code_runner exited with code %d: %s",
                proc.returncode,
                stderr,
            )
            self._emit_turn_end(turns=1, error=True)
            return AgentResult(
                content=f"Claude Code agent failed: {stderr}",
                turns=1,
                metadata={"error": True, "returncode": proc.returncode},
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
        end = stdout.find(_OUTPUT_END)

        if start == -1 or end == -1:
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
