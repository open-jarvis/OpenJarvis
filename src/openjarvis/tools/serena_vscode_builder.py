"""Native Serena VS Code Builder tools.

Foundation placeholder after failed nested-string write.
The full builder implementation will be added in smaller safe patches.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec
from openjarvis.tools.serena_vscode import SerenaVSCodeFinalCheckTool


BUILDER_OUTPUT_ROOT = Path("outputs/vscode-builder")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "build"


def _builder_root() -> Path:
    BUILDER_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "plans", "builds", "snapshots"]:
        (BUILDER_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return BUILDER_OUTPUT_ROOT


def _file_roots_config_path() -> Path:
    return Path("config/serena_file_roots.json")


def _load_file_roots() -> dict[str, Any]:
    path = _file_roots_config_path()
    if not path.exists():
        return {"roots": {}}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _resolve_root(root_key: str) -> tuple[str, dict[str, Any], Path]:
    root_key = str(root_key or "").strip()
    if not root_key:
        raise RuntimeError("Root key is required.")

    roots = _load_file_roots().get("roots", {})
    if root_key not in roots:
        available = ", ".join(sorted(roots.keys())) or "none"
        raise RuntimeError(f"Unknown approved root: {root_key}. Available roots: {available}")

    root = roots[root_key]
    path = Path(str(root.get("path") or "")).expanduser()

    if not path.exists():
        raise RuntimeError(f"Approved root path does not exist: {path}")
    if not path.is_dir():
        raise RuntimeError(f"Approved root path is not a folder: {path}")

    return root_key, root, path


class _BuilderBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_vscode_builder_status")
class SerenaVSCodeBuilderStatusTool(_BuilderBaseTool):
    tool_id = "serena_vscode_builder_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena VS Code Builder status.",
            parameters={"type": "object", "properties": {}},
            category="serena_vscode_builder",
        )

    def execute(self, **params: Any) -> ToolResult:
        roots = _load_file_roots().get("roots", {})
        root = _builder_root()

        return self._result(
            "Serena VS Code Builder status\n\n"
            "- Status: active\n"
            f"- Approved roots available: {len(roots)}\n"
            "- Builder role: high-level website, feature, component, test, and docs generator\n"
            "- Uses approved roots only\n"
            "- Publish/deploy/push: blocked unless explicit future approval layer handles it\n"
            f"- Output root: {root}\n"
            f"- Plans: {root / 'plans'}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Builds: {root / 'builds'}",
            metadata={"approved_roots": sorted(roots.keys()), "output_root": str(root)},
        )


@ToolRegistry.register("serena_vscode_builder_templates")
class SerenaVSCodeBuilderTemplatesTool(_BuilderBaseTool):
    tool_id = "serena_vscode_builder_templates"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List available Serena VS Code Builder templates.",
            parameters={"type": "object", "properties": {}},
            category="serena_vscode_builder",
        )

    def execute(self, **params: Any) -> ToolResult:
        templates = {
            "landing-html": "HTML/CSS landing page section.",
            "wordpress-section": "WordPress-ready HTML section.",
            "react-component": "React/TSX-style component.",
            "feature-scaffold": "Feature folder with source, test, and docs.",
            "docs-only": "Documentation page/section.",
        }

        lines = ["Serena VS Code Builder templates", "", "Templates:"]
        lines.extend(f"- {name}: {desc}" for name, desc in templates.items())

        return self._result("\n".join(lines), metadata={"templates": templates})


@ToolRegistry.register("serena_vscode_builder_final_check")
class SerenaVSCodeBuilderFinalCheckTool(_BuilderBaseTool):
    tool_id = "serena_vscode_builder_final_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run builder final check through the VS Code operator.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "module": {"type": "string"},
                },
                "required": ["root"],
            },
            category="serena_vscode_builder",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key = str(params.get("root") or "").strip()
            module = str(params.get("module") or "openjarvis.tools.serena_vscode_builder").strip()

            result = SerenaVSCodeFinalCheckTool().execute(root=key, module=module)

            return self._result(
                "Serena VS Code Builder final check\n\n"
                + result.content
                + "\n\nBuilder note:\n"
                "- Publish/deploy/push performed: no\n"
                "- Generated output must be reviewed before commit/publish.",
                success=result.success,
                metadata=result.metadata,
            )
        except Exception as exc:
            return self._result(f"Failed to run builder final check: {exc}", success=False)


__all__ = [
    "SerenaVSCodeBuilderStatusTool",
    "SerenaVSCodeBuilderTemplatesTool",
    "SerenaVSCodeBuilderFinalCheckTool",
]
