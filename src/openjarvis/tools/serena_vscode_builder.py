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


def _resolve_project_path(root_key: str, relative_path: str) -> tuple[str, dict[str, Any], Path, Path]:
    key, root, root_path = _resolve_root(root_key)
    rel = Path(str(relative_path or "").replace("\\", "/"))

    if rel.is_absolute() or ".." in rel.parts:
        raise RuntimeError("Relative path must stay inside the approved root.")

    target = (root_path / rel).resolve()
    root_resolved = root_path.resolve()

    if target != root_resolved and root_resolved not in target.parents:
        raise RuntimeError("Resolved path escapes the approved root.")

    return key, root, root_path, target


def _is_sensitive_path(path: Path) -> bool:
    lower = str(path).lower()
    protected = [
        ".env",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "password",
        "token",
        "prod",
        "production",
    ]
    return any(item in lower for item in protected)


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _builder_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _write_file(target: Path, content: str, overwrite: bool = False) -> dict[str, Any]:
    if _is_sensitive_path(target):
        raise RuntimeError("Target path looks sensitive or production-related.")

    existed = target.exists()
    if existed and not overwrite:
        raise RuntimeError(f"Target already exists: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    return {
        "path": str(target),
        "existed": existed,
        "bytes": len(content.encode("utf-8")),
    }


def _python_name(value: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9_]+", "_", str(value or "serena_feature")).strip("_").lower()
    return raw or "serena_feature"


def _markdown_doc(title: str, summary: str, files: list[str]) -> str:
    lines = [
        f"# {title}",
        "",
        summary,
        "",
        "## Files",
        "",
    ]
    lines.extend(f"- `{item}`" for item in files)
    lines.extend([
        "",
        "## Operator notes",
        "",
        "- Generated by Serena VS Code Builder Full Operator v1.",
        "- Review generated files before committing.",
        "- Publish/deploy/push still requires explicit approval.",
    ])
    return "\n".join(lines) + "\n"


@ToolRegistry.register("serena_vscode_builder_plan")
class SerenaVSCodeBuilderPlanTool(_BuilderBaseTool):
    tool_id = "serena_vscode_builder_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a build plan without writing project files.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "name": {"type": "string"},
                    "goal": {"type": "string"},
                    "kind": {"type": "string"},
                    "target_path": {"type": "string"},
                },
                "required": ["root", "name", "goal"],
            },
            category="serena_vscode_builder",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            name = str(params.get("name") or "").strip()
            goal = str(params.get("goal") or "").strip()
            kind = str(params.get("kind") or "feature-scaffold").strip()
            target_path = str(
                params.get("target_path")
                or f"conversion-workspace/vscode-builder-full-operator/generated/{_safe_slug(name)}"
            ).strip()

            if not name:
                return self._result("Build name is required.", success=False)
            if not goal:
                return self._result("Build goal is required.", success=False)

            plan = {
                "report_type": "serena_vscode_builder_plan",
                "created_at": _timestamp(),
                "root": key,
                "root_path": str(path),
                "name": name,
                "goal": goal,
                "kind": kind,
                "target_path": target_path,
                "steps": [
                    "Create build plan.",
                    "Scaffold target folder under approved root.",
                    "Generate source/component files.",
                    "Generate test file where useful.",
                    "Generate documentation/build report.",
                    "Inspect generated files.",
                    "Run final local checks through VS Code operator.",
                    "Do not publish, deploy, or push.",
                ],
                "approval_required_for": [
                    "publish",
                    "deploy",
                    "push",
                    "dependency changes",
                    "secrets/credentials",
                    "destructive changes",
                ],
            }

            out = _save_json("plans", name, plan)

            return self._result(
                "Serena VS Code Builder plan created\n\n"
                f"- Root: {key}\n"
                f"- Name: {name}\n"
                f"- Kind: {kind}\n"
                f"- Target path: {target_path}\n"
                f"- Plan: {out}\n\n"
                "Steps:\n"
                + "\n".join(f"- {step}" for step in plan["steps"])
                + "\n\nApproval required for:\n"
                + "\n".join(f"- {item}" for item in plan["approval_required_for"]),
                metadata={**plan, "plan_path": str(out)},
            )
        except Exception as exc:
            return self._result(f"Failed to create builder plan: {exc}", success=False)


@ToolRegistry.register("serena_vscode_builder_scaffold")
class SerenaVSCodeBuilderScaffoldTool(_BuilderBaseTool):
    tool_id = "serena_vscode_builder_scaffold"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Scaffold a feature folder with source, test, and docs.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "name": {"type": "string"},
                    "target_path": {"type": "string"},
                    "kind": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["root", "name", "target_path"],
            },
            category="serena_vscode_builder",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_path(
                str(params.get("root") or ""),
                str(params.get("target_path") or ""),
            )
            name = str(params.get("name") or "").strip()
            kind = str(params.get("kind") or "python").strip().lower()
            overwrite = bool(params.get("overwrite", False))

            if not name:
                return self._result("Name is required.", success=False)

            if _is_sensitive_path(target):
                return self._result("Scaffold blocked. Target path looks sensitive or production-related.", success=False)

            py_name = _python_name(name)
            files: list[dict[str, Any]] = []

            if kind in {"python", "py"}:
                source_name = "src.py"
                test_name = "test_src.py"
                source = (
                    '"""Feature module generated by Serena VS Code Builder Full Operator v1."""\n\n'
                    "from __future__ import annotations\n\n\n"
                    f"def {py_name}() -> str:\n"
                    f'    return "{name} ready"\n'
                )

                test = (
                    '"""Generated tests for Serena VS Code Builder scaffold."""\n\n\n'
                    f"def test_{py_name}_ready() -> None:\n"
                    f'    assert "{name}"\n'
                )
            elif kind in {"typescript", "ts"}:
                source_name = "src.ts"
                test_name = "src.test.ts"
                component_name = "".join(part[:1].upper() + part[1:] for part in re.split(r"[^a-zA-Z0-9]+", name) if part) or "SerenaFeature"
                source = (
                    "/** Feature module generated by Serena VS Code Builder Full Operator v1. */\n\n"
                    f"export function {component_name}(): string {{\n"
                    f'  return "{name} ready";\n'
                    "}\n"
                )
                test = (
                    f'describe("{component_name}", () => {{\n'
                    '  it("has a placeholder test", () => {\n'
                    f'    expect("{name}").toBeTruthy();\n'
                    "  });\n"
                    "});\n"
                )
            else:
                source_name = "src.md"
                test_name = "test-plan.md"
                source = (
                    f"# {name}\n\n"
                    "Generated by Serena VS Code Builder Full Operator v1.\n\n"
                    f"Kind: {kind}\n"
                )
                test = (
                    f"# {name} Test Plan\n\n"
                    "- Confirm generated files exist.\n"
                    "- Review output before commit.\n"
                    "- Run final-check before publish/push/deploy.\n"
                )

            docs = _markdown_doc(
                title=f"{name} Feature",
                summary="Generated feature scaffold created by Serena VS Code Builder Full Operator v1.",
                files=[source_name, test_name, "README.md"],
            )

            files.append(_write_file(target / source_name, source, overwrite=overwrite))
            files.append(_write_file(target / test_name, test, overwrite=overwrite))
            files.append(_write_file(target / "README.md", docs, overwrite=overwrite))

            report = {
                "report_type": "serena_vscode_builder_scaffold",
                "created_at": _timestamp(),
                "root": key,
                "target": str(target),
                "relative_target": str(target.relative_to(root_path)),
                "name": name,
                "kind": kind,
                "files": files,
                "publish_deploy_push_performed": False,
            }
            report_path = _save_json("reports", name, report)

            return self._result(
                "Serena VS Code Builder scaffold created\n\n"
                f"- Root: {key}\n"
                f"- Target: {target.relative_to(root_path)}\n"
                f"- Name: {name}\n"
                f"- Kind: {kind}\n"
                f"- Files created: {len(files)}\n"
                f"- Report: {report_path}\n"
                "- Publish/deploy/push performed: no\n\n"
                "Files:\n"
                + "\n".join(f"- {Path(item['path']).relative_to(root_path)}" for item in files),
                metadata={**report, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to scaffold builder feature: {exc}", success=False)


__all__ = [
    "SerenaVSCodeBuilderStatusTool",
    "SerenaVSCodeBuilderTemplatesTool",
    "SerenaVSCodeBuilderScaffoldTool",
    "SerenaVSCodeBuilderPlanTool",
    "SerenaVSCodeBuilderFinalCheckTool",
]
