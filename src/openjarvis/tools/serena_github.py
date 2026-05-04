"""Native Serena GitHub/Git operator tools.

Serena GitHub Full Operator v1 foundation:
- inspect approved Git repositories
- inspect branch/remotes/recent commits
- inspect local changes
- run safety checks
- block remote writes unless approval-gated future layer handles them
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.tools._stubs import BaseTool, ToolResult, ToolSpec


GITHUB_OUTPUT_ROOT = Path("outputs/github")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _safe_slug(value: str) -> str:
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return slug or "github"


def _github_root() -> Path:
    GITHUB_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    for child in ["reports", "plans", "drafts", "snapshots"]:
        (GITHUB_OUTPUT_ROOT / child).mkdir(parents=True, exist_ok=True)
    return GITHUB_OUTPUT_ROOT


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


def _run_git(root_path: Path, args: list[str], timeout: int = 60) -> dict[str, Any]:
    cmd = ["git"] + args
    result = subprocess.run(
        cmd,
        cwd=str(root_path),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")
    return {
        "command": cmd,
        "returncode": result.returncode,
        "stdout": result.stdout or "",
        "stderr": result.stderr or "",
        "output": output.strip(),
    }


def _is_git_repo(root_path: Path) -> bool:
    try:
        result = _run_git(root_path, ["rev-parse", "--is-inside-work-tree"])
        return result["returncode"] == 0 and result["stdout"].strip().lower() == "true"
    except Exception:
        return False


def _save_json(kind: str, name: str, payload: dict[str, Any]) -> Path:
    root = _github_root()
    folder = root / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _collect_repo_snapshot(root_key: str, root_path: Path) -> dict[str, Any]:
    commands = {
        "inside_work_tree": ["rev-parse", "--is-inside-work-tree"],
        "top_level": ["rev-parse", "--show-toplevel"],
        "current_branch": ["branch", "--show-current"],
        "status_short": ["status", "--short"],
        "status_branch": ["status", "--short", "--branch"],
        "remotes": ["remote", "-v"],
        "recent_commits": ["log", "--oneline", "-n", "10"],
        "diff_stat": ["diff", "--stat"],
        "diff_name_only": ["diff", "--name-only"],
    }

    results: dict[str, Any] = {}

    for name, args in commands.items():
        try:
            results[name] = _run_git(root_path, args)
        except Exception as exc:
            results[name] = {
                "command": ["git"] + args,
                "returncode": -1,
                "output": str(exc),
            }

    return {
        "root": root_key,
        "path": str(root_path),
        "created_at": _timestamp(),
        "results": results,
    }


class _GitHubBaseTool(BaseTool):
    def _result(self, content: str, success: bool = True, metadata: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(
            tool_name=getattr(self, "tool_id", self.__class__.__name__),
            success=success,
            content=content,
            metadata=metadata or {},
        )


@ToolRegistry.register("serena_github_status")
class SerenaGitHubStatusTool(_GitHubBaseTool):
    tool_id = "serena_github_status"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show Serena GitHub operator status.",
            parameters={"type": "object", "properties": {}},
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        roots = _load_file_roots().get("roots", {})
        root = _github_root()

        return self._result(
            "Serena GitHub status\n\n"
            "- Status: active\n"
            f"- Approved roots available: {len(roots)}\n"
            "- GitHub role: safe local Git/GitHub planning and inspection operator\n"
            "- Remote writes: approval-gated\n"
            "- Push/force-push/merge/release/delete: blocked in v1 unless explicit future approval layer handles it\n"
            f"- Output root: {root}\n"
            f"- Reports: {root / 'reports'}\n"
            f"- Plans: {root / 'plans'}\n"
            f"- Drafts: {root / 'drafts'}",
            metadata={"approved_roots": sorted(roots.keys()), "output_root": str(root)},
        )


@ToolRegistry.register("serena_github_repo_info")
class SerenaGitHubRepoInfoTool(_GitHubBaseTool):
    tool_id = "serena_github_repo_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect basic Git repository information for an approved root.",
            parameters={
                "type": "object",
                "properties": {"root": {"type": "string"}},
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            snapshot = _collect_repo_snapshot(key, path)
            report_path = _save_json("reports", f"{key}-repo-info", snapshot)

            results = snapshot["results"]
            top_level = results["top_level"]["output"]
            branch = results["current_branch"]["output"]
            remotes = results["remotes"]["output"]

            return self._result(
                "Serena GitHub repository info\n\n"
                f"- Root: {key}\n"
                f"- Path: {path}\n"
                f"- Git top-level: {top_level or 'unknown'}\n"
                f"- Current branch: {branch or 'unknown'}\n"
                f"- Report: {report_path}\n\n"
                "Remotes:\n"
                f"{remotes or 'none'}",
                metadata={**snapshot, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to inspect GitHub repository: {exc}", success=False)


@ToolRegistry.register("serena_github_branches")
class SerenaGitHubBranchesTool(_GitHubBaseTool):
    tool_id = "serena_github_branches"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List local and remote branches for an approved Git root.",
            parameters={
                "type": "object",
                "properties": {"root": {"type": "string"}},
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            local = _run_git(path, ["branch", "--list"])
            remote = _run_git(path, ["branch", "-r"])
            current = _run_git(path, ["branch", "--show-current"])

            payload = {
                "report_type": "serena_github_branches",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "current_branch": current["output"],
                "local_branches": local["output"],
                "remote_branches": remote["output"],
            }
            report_path = _save_json("reports", f"{key}-branches", payload)

            return self._result(
                "Serena GitHub branches\n\n"
                f"- Root: {key}\n"
                f"- Current branch: {current['output'] or 'unknown'}\n"
                f"- Report: {report_path}\n\n"
                "Local branches:\n"
                f"{local['output'] or 'none'}\n\n"
                "Remote branches:\n"
                f"{remote['output'] or 'none'}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to inspect Git branches: {exc}", success=False)


@ToolRegistry.register("serena_github_remotes")
class SerenaGitHubRemotesTool(_GitHubBaseTool):
    tool_id = "serena_github_remotes"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="List Git remotes for an approved root.",
            parameters={
                "type": "object",
                "properties": {"root": {"type": "string"}},
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            remotes = _run_git(path, ["remote", "-v"])

            payload = {
                "report_type": "serena_github_remotes",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "remotes": remotes["output"],
            }
            report_path = _save_json("reports", f"{key}-remotes", payload)

            return self._result(
                "Serena GitHub remotes\n\n"
                f"- Root: {key}\n"
                f"- Report: {report_path}\n\n"
                f"{remotes['output'] or 'No remotes found.'}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to inspect Git remotes: {exc}", success=False)


@ToolRegistry.register("serena_github_recent_commits")
class SerenaGitHubRecentCommitsTool(_GitHubBaseTool):
    tool_id = "serena_github_recent_commits"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Show recent commits for an approved Git root.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            limit = int(params.get("limit") or 10)

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            commits = _run_git(path, ["log", "--oneline", "-n", str(limit)])

            payload = {
                "report_type": "serena_github_recent_commits",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "limit": limit,
                "commits": commits["output"],
            }
            report_path = _save_json("reports", f"{key}-recent-commits", payload)

            return self._result(
                "Serena GitHub recent commits\n\n"
                f"- Root: {key}\n"
                f"- Limit: {limit}\n"
                f"- Report: {report_path}\n\n"
                f"{commits['output'] or 'No commits found.'}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to inspect recent commits: {exc}", success=False)


@ToolRegistry.register("serena_github_changes")
class SerenaGitHubChangesTool(_GitHubBaseTool):
    tool_id = "serena_github_changes"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Inspect local Git changes for an approved root.",
            parameters={
                "type": "object",
                "properties": {"root": {"type": "string"}},
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            status = _run_git(path, ["status", "--short", "--branch"])
            diff_stat = _run_git(path, ["diff", "--stat"])
            diff_name_only = _run_git(path, ["diff", "--name-only"])
            staged_stat = _run_git(path, ["diff", "--cached", "--stat"])

            payload = {
                "report_type": "serena_github_changes",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "status": status["output"],
                "diff_stat": diff_stat["output"],
                "diff_name_only": diff_name_only["output"],
                "staged_stat": staged_stat["output"],
            }
            report_path = _save_json("reports", f"{key}-changes", payload)

            return self._result(
                "Serena GitHub local changes\n\n"
                f"- Root: {key}\n"
                f"- Report: {report_path}\n\n"
                "Status:\n"
                f"{status['output'] or 'clean'}\n\n"
                "Diff stat:\n"
                f"{diff_stat['output'] or 'no unstaged diff'}\n\n"
                "Changed files:\n"
                f"{diff_name_only['output'] or 'none'}\n\n"
                "Staged diff stat:\n"
                f"{staged_stat['output'] or 'no staged diff'}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to inspect local Git changes: {exc}", success=False)


@ToolRegistry.register("serena_github_safety_check")
class SerenaGitHubSafetyCheckTool(_GitHubBaseTool):
    tool_id = "serena_github_safety_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run Serena GitHub safety check for an approved root.",
            parameters={
                "type": "object",
                "properties": {"root": {"type": "string"}},
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            snapshot = _collect_repo_snapshot(key, path)
            results = snapshot["results"]

            status = results["status_branch"]["output"]
            remotes = results["remotes"]["output"]
            branch = results["current_branch"]["output"]

            issues: list[str] = []
            recommendations: list[str] = []

            if not branch:
                issues.append("Could not detect current branch.")
            if not remotes:
                recommendations.append("No remotes detected. Remote GitHub actions may not be available.")
            if "??" in status:
                recommendations.append("Untracked files detected. Review before committing.")
            if "M " in status or " M" in status:
                recommendations.append("Modified files detected. Review diff before committing.")
            if "main" in branch.lower() or "master" in branch.lower():
                recommendations.append("Current branch appears to be main/master. Be extra careful before push/PR operations.")

            payload = {
                "report_type": "serena_github_safety_check",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "branch": branch,
                "status": status,
                "remotes": remotes,
                "issues": issues,
                "recommendations": recommendations,
                "remote_writes_allowed": False,
                "push_allowed": False,
                "force_push_allowed": False,
            }
            report_path = _save_json("reports", f"{key}-safety-check", payload)

            lines = [
                "Serena GitHub safety check",
                "",
                f"- Root: {key}",
                f"- Branch: {branch or 'unknown'}",
                f"- Report: {report_path}",
                "- Remote writes allowed: no",
                "- Push allowed: no",
                "- Force-push allowed: no",
                "",
                "Issues:",
            ]

            lines.extend(f"- {issue}" for issue in issues) if issues else lines.append("- none")
            lines.extend(["", "Recommendations:"])
            lines.extend(f"- {rec}" for rec in recommendations) if recommendations else lines.append("- No immediate recommendations.")
            lines.extend([
                "",
                "Safety rule:",
                "- Serena GitHub v1 may inspect and draft, but must not push, force-push, merge, delete branches, or create remote GitHub objects without explicit approval/future approval layer.",
            ])

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to run GitHub safety check: {exc}", success=False)


__all__ = [
    "SerenaGitHubStatusTool",
    "SerenaGitHubRepoInfoTool",
    "SerenaGitHubBranchesTool",
    "SerenaGitHubRemotesTool",
    "SerenaGitHubRecentCommitsTool",
    "SerenaGitHubChangesTool",
    "SerenaGitHubSafetyCheckTool",
]
