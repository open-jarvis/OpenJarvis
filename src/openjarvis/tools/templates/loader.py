"""Template loader — dynamically construct BaseTool from TOML definitions."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

logger = logging.getLogger(__name__)

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


class ToolTemplate(BaseTool):
    """A tool dynamically constructed from a TOML template definition."""

    tool_id: str

    def __init__(self, template_data: Dict[str, Any]) -> None:
        self._data = template_data
        self.tool_id = template_data.get("name", "template")
        self._name = template_data.get("name", "template")
        self._description = template_data.get("description", "")
        self._parameters = template_data.get("parameters", {})
        self._action = template_data.get("action", {})

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self._name,
            description=self._description,
            parameters=self._parameters,
            category="template",
            metadata={"template": True},
        )

    def execute(self, **params: Any) -> ToolResult:
        action_type = self._action.get("type", "python")

        try:
            if action_type == "python":
                return self._execute_python(params)
            elif action_type == "shell":
                return self._execute_shell(params)
            elif action_type == "transform":
                return self._execute_transform(params)
            else:
                return ToolResult(
                    tool_name=self._name,
                    content=f"Unknown action type: {action_type}",
                    success=False,
                )
        except Exception as exc:
            return ToolResult(
                tool_name=self._name,
                content=f"Template execution error: {exc}",
                success=False,
            )

    def _execute_python(self, params: Dict[str, Any]) -> ToolResult:
        """Execute a Python expression."""
        expr = self._action.get("expression", "")
        if not expr:
            return ToolResult(
                tool_name=self._name,
                content="No expression defined.",
                success=False,
            )
        # Safe evaluation with params available
        safe_builtins = {
            "str": str,
            "int": int,
            "float": float,
            "len": len,
            "sorted": sorted,
            "list": list,
            "dict": dict,
            "json": json,
        }
        result = eval(  # noqa: S307
            expr,
            {"__builtins__": safe_builtins},
            params,
        )
        return ToolResult(
            tool_name=self._name,
            content=str(result),
            success=True,
        )

    def _execute_shell(self, params: Dict[str, Any]) -> ToolResult:
        """Execute a shell command (requires code:execute capability)."""
        cmd = self._action.get("command", "")
        if not cmd:
            return ToolResult(
                tool_name=self._name,
                content="No command defined.",
                success=False,
            )
        # Substitute params into command
        for key, val in params.items():
            cmd = cmd.replace(f"{{{key}}}", str(val))
        result = subprocess.run(  # noqa: S602, S603
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout or result.stderr
        return ToolResult(
            tool_name=self._name,
            content=output.strip(),
            success=result.returncode == 0,
        )

    def _execute_transform(self, params: Dict[str, Any]) -> ToolResult:
        """Execute a data transformation."""
        transform = self._action.get("transform", "identity")
        input_val = params.get("input", "")
        if transform == "upper":
            return ToolResult(
                tool_name=self._name,
                content=str(input_val).upper(),
                success=True,
            )
        elif transform == "lower":
            return ToolResult(
                tool_name=self._name,
                content=str(input_val).lower(),
                success=True,
            )
        elif transform == "length":
            return ToolResult(
                tool_name=self._name,
                content=str(len(str(input_val))),
                success=True,
            )
        elif transform == "reverse":
            return ToolResult(
                tool_name=self._name,
                content=str(input_val)[::-1],
                success=True,
            )
        elif transform == "json_pretty":
            try:
                parsed = json.loads(str(input_val))
                return ToolResult(
                    tool_name=self._name,
                    content=json.dumps(
                        parsed,
                        indent=2,
                    ),
                    success=True,
                )
            except json.JSONDecodeError as exc:
                return ToolResult(
                    tool_name=self._name,
                    content=f"Invalid JSON: {exc}",
                    success=False,
                )
        else:
            return ToolResult(
                tool_name=self._name,
                content=str(input_val),
                success=True,
            )


def load_template(path: str | Path) -> ToolTemplate:
    """Load a single tool template from a TOML file."""
    path = Path(path)
    with open(path, "rb") as fh:
        data = tomllib.load(fh)
    tool_data = data.get("tool", data)
    return ToolTemplate(tool_data)


def discover_templates(
    directory: Optional[str | Path] = None,
) -> List[ToolTemplate]:
    """Discover all TOML templates in a directory."""
    if directory is None:
        directory = Path(__file__).parent / "builtin"
    directory = Path(directory)
    if not directory.exists():
        return []
    templates = []
    for path in sorted(directory.glob("*.toml")):
        try:
            templates.append(load_template(path))
        except Exception as exc:
            logger.debug("Skipping unparseable template %s: %s", path, exc)
    return templates


__all__ = ["ToolTemplate", "discover_templates", "load_template"]
