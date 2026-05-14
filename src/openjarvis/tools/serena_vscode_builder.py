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


def _html_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _landing_html(title: str, subtitle: str, cta_text: str, cta_url: str) -> str:
    return (
        '<section class="serena-landing-section">\n'
        '  <div class="serena-landing-inner">\n'
        '    <p class="serena-eyebrow">Built with Serena</p>\n'
        f'    <h1>{_html_escape(title)}</h1>\n'
        f'    <p class="serena-subtitle">{_html_escape(subtitle)}</p>\n'
        '    <div class="serena-actions">\n'
        f'      <a class="serena-primary-cta" href="{_html_escape(cta_url)}">{_html_escape(cta_text)}</a>\n'
        '    </div>\n'
        '  </div>\n'
        '</section>\n'
    )


def _landing_css() -> str:
    return (
        ".serena-landing-section {\n"
        "  padding: 72px 24px;\n"
        "  background: linear-gradient(135deg, #f7fbff 0%, #ffffff 55%, #eef6ff 100%);\n"
        "  color: #172033;\n"
        "}\n\n"
        ".serena-landing-inner {\n"
        "  max-width: 1040px;\n"
        "  margin: 0 auto;\n"
        "}\n\n"
        ".serena-eyebrow {\n"
        "  margin: 0 0 12px;\n"
        "  font-size: 0.82rem;\n"
        "  font-weight: 700;\n"
        "  letter-spacing: 0.08em;\n"
        "  text-transform: uppercase;\n"
        "}\n\n"
        ".serena-landing-section h1 {\n"
        "  margin: 0;\n"
        "  max-width: 820px;\n"
        "  font-size: clamp(2.4rem, 6vw, 4.8rem);\n"
        "  line-height: 1.02;\n"
        "}\n\n"
        ".serena-subtitle {\n"
        "  max-width: 680px;\n"
        "  margin: 22px 0 0;\n"
        "  font-size: 1.16rem;\n"
        "  line-height: 1.7;\n"
        "}\n\n"
        ".serena-actions {\n"
        "  margin-top: 32px;\n"
        "}\n\n"
        ".serena-primary-cta {\n"
        "  display: inline-flex;\n"
        "  align-items: center;\n"
        "  justify-content: center;\n"
        "  min-height: 48px;\n"
        "  padding: 0 22px;\n"
        "  border-radius: 999px;\n"
        "  background: #102a43;\n"
        "  color: #ffffff;\n"
        "  font-weight: 700;\n"
        "  text-decoration: none;\n"
        "}\n"
    )


def _wordpress_html_block(title: str, subtitle: str, cta_text: str, cta_url: str) -> str:
    return (
        "<!-- wp:html -->\n"
        + _landing_html(title, subtitle, cta_text, cta_url)
        + "<!-- /wp:html -->\n"
    )


@ToolRegistry.register("serena_vscode_builder_build_section")
class SerenaVSCodeBuilderBuildSectionTool(_BuilderBaseTool):
    tool_id = "serena_vscode_builder_build_section"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Build a polished HTML/CSS website section under an approved root.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "target_path": {"type": "string"},
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "cta_text": {"type": "string"},
                    "cta_url": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["root", "target_path", "title"],
            },
            category="serena_vscode_builder",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_path(
                str(params.get("root") or ""),
                str(params.get("target_path") or ""),
            )
            title = str(params.get("title") or "").strip()
            subtitle = str(params.get("subtitle") or "A polished website section generated by Serena.").strip()
            cta_text = str(params.get("cta_text") or "Get started").strip()
            cta_url = str(params.get("cta_url") or "#").strip()
            overwrite = bool(params.get("overwrite", False))

            if not title:
                return self._result("Title is required.", success=False)

            html = _landing_html(title, subtitle, cta_text, cta_url)
            css = _landing_css()
            docs = _markdown_doc(
                title=f"{title} Website Section",
                summary="HTML/CSS website section generated by Serena VS Code Builder Full Operator v1.",
                files=["section.html", "section.css", "README.md"],
            )

            files = [
                _write_file(target / "section.html", html, overwrite=overwrite),
                _write_file(target / "section.css", css, overwrite=overwrite),
                _write_file(target / "README.md", docs, overwrite=overwrite),
            ]

            report = {
                "report_type": "serena_vscode_builder_build_section",
                "created_at": _timestamp(),
                "root": key,
                "target": str(target),
                "relative_target": str(target.relative_to(root_path)),
                "title": title,
                "subtitle": subtitle,
                "cta_text": cta_text,
                "cta_url": cta_url,
                "files": files,
                "publish_deploy_push_performed": False,
            }
            report_path = _save_json("reports", title, report)

            return self._result(
                "Serena website section built\n\n"
                f"- Root: {key}\n"
                f"- Target: {target.relative_to(root_path)}\n"
                f"- Title: {title}\n"
                f"- Files created: {len(files)}\n"
                f"- Report: {report_path}\n"
                "- Publish/deploy/push performed: no\n\n"
                "Files:\n"
                + "\n".join(f"- {Path(item['path']).relative_to(root_path)}" for item in files),
                metadata={**report, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to build website section: {exc}", success=False)


@ToolRegistry.register("serena_vscode_builder_build_wordpress_section")
class SerenaVSCodeBuilderBuildWordPressSectionTool(_BuilderBaseTool):
    tool_id = "serena_vscode_builder_build_wordpress_section"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Build a WordPress-ready HTML section under an approved root without publishing.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "target_path": {"type": "string"},
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "cta_text": {"type": "string"},
                    "cta_url": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["root", "target_path", "title"],
            },
            category="serena_vscode_builder",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_path(
                str(params.get("root") or ""),
                str(params.get("target_path") or ""),
            )
            title = str(params.get("title") or "").strip()
            subtitle = str(params.get("subtitle") or "A WordPress-ready section generated by Serena.").strip()
            cta_text = str(params.get("cta_text") or "Book now").strip()
            cta_url = str(params.get("cta_url") or "#").strip()
            overwrite = bool(params.get("overwrite", False))

            if not title:
                return self._result("Title is required.", success=False)

            html = _wordpress_html_block(title, subtitle, cta_text, cta_url)
            notes = _markdown_doc(
                title=f"{title} WordPress Section",
                summary="WordPress-ready HTML block generated by Serena VS Code Builder Full Operator v1. Review before importing into WordPress.",
                files=["section.wordpress.html", "README.md"],
            )

            files = [
                _write_file(target / "section.wordpress.html", html, overwrite=overwrite),
                _write_file(target / "README.md", notes, overwrite=overwrite),
            ]

            report = {
                "report_type": "serena_vscode_builder_build_wordpress_section",
                "created_at": _timestamp(),
                "root": key,
                "target": str(target),
                "relative_target": str(target.relative_to(root_path)),
                "title": title,
                "subtitle": subtitle,
                "cta_text": cta_text,
                "cta_url": cta_url,
                "files": files,
                "wordpress_ready": True,
                "published_to_wordpress": False,
                "publish_deploy_push_performed": False,
            }
            report_path = _save_json("reports", title, report)

            return self._result(
                "Serena WordPress-ready section built\n\n"
                f"- Root: {key}\n"
                f"- Target: {target.relative_to(root_path)}\n"
                f"- Title: {title}\n"
                f"- Files created: {len(files)}\n"
                "- WordPress-ready: yes\n"
                "- Published to WordPress: no\n"
                "- Publish/deploy/push performed: no\n"
                f"- Report: {report_path}\n\n"
                "Files:\n"
                + "\n".join(f"- {Path(item['path']).relative_to(root_path)}" for item in files),
                metadata={**report, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to build WordPress-ready section: {exc}", success=False)


def _component_name(value: str) -> str:
    raw = re.sub(r"[^a-zA-Z0-9]+", " ", str(value or "SerenaComponent")).strip()
    parts = raw.split()
    return "".join(part[:1].upper() + part[1:] for part in parts) or "SerenaComponent"


def _react_component_source(name: str, title: str, subtitle: str, cta_text: str, cta_url: str) -> str:
    comp = _component_name(name)
    safe_title = _html_escape(title)
    safe_subtitle = _html_escape(subtitle)
    safe_cta_text = _html_escape(cta_text)
    safe_cta_url = _html_escape(cta_url)

    return (
        'import React from "react";\n\n'
        f"export default function {comp}() {{\n"
        "  return (\n"
        '    <section className="mx-auto max-w-6xl px-6 py-20">\n'
        '      <p className="mb-3 text-sm font-semibold uppercase tracking-wide">\n'
        "        Built with Serena\n"
        "      </p>\n"
        '      <h1 className="max-w-4xl text-4xl font-bold tracking-tight md:text-6xl">\n'
        f"        {safe_title}\n"
        "      </h1>\n"
        '      <p className="mt-6 max-w-2xl text-lg leading-8">\n'
        f"        {safe_subtitle}\n"
        "      </p>\n"
        '      <div className="mt-8">\n'
        "        <a\n"
        f'          href="{safe_cta_url}"\n'
        '          className="inline-flex min-h-12 items-center rounded-full px-6 font-semibold shadow-sm"\n'
        "        >\n"
        f"          {safe_cta_text}\n"
        "        </a>\n"
        "      </div>\n"
        "    </section>\n"
        "  );\n"
        "}\n"
    )


@ToolRegistry.register("serena_vscode_builder_build_react_component")
class SerenaVSCodeBuilderBuildReactComponentTool(_BuilderBaseTool):
    tool_id = "serena_vscode_builder_build_react_component"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Build a React component with documentation under an approved root.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "target_path": {"type": "string"},
                    "name": {"type": "string"},
                    "title": {"type": "string"},
                    "subtitle": {"type": "string"},
                    "cta_text": {"type": "string"},
                    "cta_url": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["root", "target_path", "name"],
            },
            category="serena_vscode_builder",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_path(
                str(params.get("root") or ""),
                str(params.get("target_path") or ""),
            )
            name = str(params.get("name") or "SerenaSection").strip()
            title = str(params.get("title") or name).strip()
            subtitle = str(params.get("subtitle") or "A polished React component generated by Serena.").strip()
            cta_text = str(params.get("cta_text") or "Get started").strip()
            cta_url = str(params.get("cta_url") or "#").strip()
            overwrite = bool(params.get("overwrite", False))

            if not name:
                return self._result("Component name is required.", success=False)

            component_name = _component_name(name)
            component = _react_component_source(name, title, subtitle, cta_text, cta_url)
            docs = _markdown_doc(
                title=f"{name} React Component",
                summary="React component generated by Serena VS Code Builder Full Operator v1. Review styling, imports, and framework conventions before production use.",
                files=[f"{component_name}.tsx", "README.md"],
            )

            files = [
                _write_file(target / f"{component_name}.tsx", component, overwrite=overwrite),
                _write_file(target / "README.md", docs, overwrite=overwrite),
            ]

            report = {
                "report_type": "serena_vscode_builder_build_react_component",
                "created_at": _timestamp(),
                "root": key,
                "target": str(target),
                "relative_target": str(target.relative_to(root_path)),
                "name": name,
                "component_name": component_name,
                "title": title,
                "subtitle": subtitle,
                "cta_text": cta_text,
                "cta_url": cta_url,
                "files": files,
                "publish_deploy_push_performed": False,
            }
            report_path = _save_json("reports", name, report)

            return self._result(
                "Serena React component built\n\n"
                f"- Root: {key}\n"
                f"- Target: {target.relative_to(root_path)}\n"
                f"- Name: {name}\n"
                f"- Component: {component_name}.tsx\n"
                f"- Files created: {len(files)}\n"
                f"- Report: {report_path}\n"
                "- Publish/deploy/push performed: no\n\n"
                "Files:\n"
                + "\n".join(f"- {Path(item['path']).relative_to(root_path)}" for item in files),
                metadata={**report, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to build React component: {exc}", success=False)


@ToolRegistry.register("serena_vscode_builder_inspect_build")
class SerenaVSCodeBuilderInspectBuildTool(_BuilderBaseTool):
    tool_id = "serena_vscode_builder_inspect_build"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect generated build files under an approved root.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "target_path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["root", "target_path"],
            },
            category="serena_vscode_builder",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, root_path, target = _resolve_project_path(
                str(params.get("root") or ""),
                str(params.get("target_path") or ""),
            )
            limit = int(params.get("limit") or 100)

            if not target.exists():
                return self._result(f"Build target does not exist: {target}", success=False)
            if not target.is_dir():
                return self._result(f"Build target is not a folder: {target}", success=False)

            files = [p for p in target.rglob("*") if p.is_file()][:limit]
            suffix_counts: dict[str, int] = {}
            total_bytes = 0

            expected_docs = False
            expected_source = False
            expected_styles = False
            wordpress_ready = False
            react_ready = False

            inspected_files: list[dict[str, Any]] = []

            for file in files:
                suffix = file.suffix.lower() or "(none)"
                suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
                size = file.stat().st_size
                total_bytes += size

                rel = str(file.relative_to(root_path))

                if file.name.lower() == "readme.md":
                    expected_docs = True
                if suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".html"}:
                    expected_source = True
                if suffix == ".css":
                    expected_styles = True
                if file.name.lower().endswith(".wordpress.html"):
                    wordpress_ready = True
                if suffix == ".tsx":
                    react_ready = True

                preview = ""
                if suffix in {".md", ".txt", ".html", ".css", ".py", ".ts", ".tsx", ".js", ".jsx", ".json"}:
                    try:
                        preview = file.read_text(encoding="utf-8-sig", errors="replace")[:800]
                    except Exception:
                        preview = ""

                inspected_files.append(
                    {
                        "relative_path": rel,
                        "size_bytes": size,
                        "suffix": suffix,
                        "preview": preview,
                    }
                )

            issues: list[str] = []
            recommendations: list[str] = []

            if not files:
                issues.append("No files found in generated build folder.")
            if not expected_docs:
                recommendations.append("Add README.md documentation for the generated build.")
            if not expected_source:
                recommendations.append("No source/section/component file detected.")
            if total_bytes == 0:
                issues.append("Generated files appear empty.")
            if wordpress_ready:
                recommendations.append("WordPress-ready HTML detected. Review with WordPress checklist before publishing.")
            if react_ready:
                recommendations.append("React/TSX component detected. Review framework conventions and styling before integration.")

            report = {
                "report_type": "serena_vscode_builder_inspect_build",
                "created_at": _timestamp(),
                "root": key,
                "target": str(target),
                "relative_target": str(target.relative_to(root_path)),
                "files_found": len(files),
                "total_bytes": total_bytes,
                "suffix_counts": suffix_counts,
                "wordpress_ready": wordpress_ready,
                "react_ready": react_ready,
                "has_docs": expected_docs,
                "has_source": expected_source,
                "has_styles": expected_styles,
                "issues": issues,
                "recommendations": recommendations,
                "files": inspected_files,
                "publish_deploy_push_performed": False,
            }
            report_path = _save_json("reports", target.name + "-inspection", report)

            lines = [
                "Serena VS Code Builder build inspection",
                "",
                f"- Root: {key}",
                f"- Target: {target.relative_to(root_path)}",
                f"- Files found: {len(files)}",
                f"- Total size: {total_bytes} bytes",
                f"- WordPress-ready: {'yes' if wordpress_ready else 'no'}",
                f"- React/TSX detected: {'yes' if react_ready else 'no'}",
                f"- README detected: {'yes' if expected_docs else 'no'}",
                f"- Source/section/component detected: {'yes' if expected_source else 'no'}",
                f"- Report: {report_path}",
                "- Publish/deploy/push performed: no",
                "",
                "File types:",
            ]

            if suffix_counts:
                lines.extend(f"- {suffix}: {count}" for suffix, count in sorted(suffix_counts.items()))
            else:
                lines.append("- none")

            lines.extend(["", "Files:"])
            if inspected_files:
                for item in inspected_files[:60]:
                    lines.append(f"- {item['relative_path']} | {item['suffix']} | {item['size_bytes']} bytes")
            else:
                lines.append("- none")

            lines.extend(["", "Issues:"])
            lines.extend(f"- {issue}" for issue in issues) if issues else lines.append("- none")

            lines.extend(["", "Recommendations:"])
            lines.extend(f"- {rec}" for rec in recommendations) if recommendations else lines.append("- No immediate recommendations.")

            return self._result("\n".join(lines), metadata={**report, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to inspect builder output: {exc}", success=False)


__all__ = [
    "SerenaVSCodeBuilderStatusTool",
    "SerenaVSCodeBuilderTemplatesTool",
    "SerenaVSCodeBuilderScaffoldTool",
    "SerenaVSCodeBuilderBuildWordPressSectionTool",
    "SerenaVSCodeBuilderBuildReactComponentTool",
    "SerenaVSCodeBuilderInspectBuildTool",
    "SerenaVSCodeBuilderBuildSectionTool",
    "SerenaVSCodeBuilderPlanTool",
    "SerenaVSCodeBuilderFinalCheckTool",
]
