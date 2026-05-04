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


def _draft_text(kind: str, name: str, content: str) -> Path:
    root = _github_root()
    folder = root / "drafts"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{_timestamp()}-{_safe_slug(name)}-{kind}.md"
    path.write_text(content, encoding="utf-8")
    return path


def _changes_summary(root_key: str, root_path: Path) -> dict[str, Any]:
    status = _run_git(root_path, ["status", "--short", "--branch"])
    diff_stat = _run_git(root_path, ["diff", "--stat"])
    diff_name_only = _run_git(root_path, ["diff", "--name-only"])
    staged_stat = _run_git(root_path, ["diff", "--cached", "--stat"])
    staged_name_only = _run_git(root_path, ["diff", "--cached", "--name-only"])
    recent = _run_git(root_path, ["log", "--oneline", "-n", "8"])
    branch = _run_git(root_path, ["branch", "--show-current"])

    return {
        "root": root_key,
        "path": str(root_path),
        "branch": branch["output"],
        "status": status["output"],
        "diff_stat": diff_stat["output"],
        "diff_name_only": diff_name_only["output"],
        "staged_stat": staged_stat["output"],
        "staged_name_only": staged_name_only["output"],
        "recent_commits": recent["output"],
    }


def _infer_commit_subject(summary: dict[str, Any], fallback: str = "Update Serena project") -> str:
    changed = summary.get("diff_name_only") or summary.get("staged_name_only") or ""
    status = summary.get("status") or ""

    lower = (changed + "\n" + status).lower()

    if "serena_github" in lower or "github_cmd" in lower:
        return "Add Serena GitHub operator workflow"
    if "vscode_builder" in lower:
        return "Update Serena VS Code Builder operator"
    if "serena_vscode" in lower:
        return "Update Serena VS Code operator"
    if "serena_documents" in lower:
        return "Update Serena documents operator"
    if "serena_files" in lower:
        return "Update Serena files operator"
    if "serena_wordpress" in lower:
        return "Update Serena WordPress operator"
    if "conversion_registry" in lower:
        return "Update Serena capability registry"
    if "skill.md" in lower:
        return "Update Serena skill documentation"

    return fallback


@ToolRegistry.register("serena_github_commit_plan")
class SerenaGitHubCommitPlanTool(_GitHubBaseTool):
    tool_id = "serena_github_commit_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a local commit plan from current Git changes without committing or pushing.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "goal": {"type": "string"},
                },
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            goal = str(params.get("goal") or "Prepare local changes for review").strip()

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            summary = _changes_summary(key, path)
            subject = _infer_commit_subject(summary)

            plan = {
                "report_type": "serena_github_commit_plan",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "goal": goal,
                "suggested_commit_subject": subject,
                "changes": summary,
                "steps": [
                    "Review git status.",
                    "Review changed files and diff stat.",
                    "Run relevant local checks.",
                    "Stage only intended files.",
                    "Commit locally with a clear message.",
                    "Do not push without explicit approval.",
                ],
                "remote_writes_performed": False,
                "push_performed": False,
            }

            report_path = _save_json("plans", f"{key}-commit-plan", plan)

            return self._result(
                "Serena GitHub commit plan\n\n"
                f"- Root: {key}\n"
                f"- Branch: {summary.get('branch') or 'unknown'}\n"
                f"- Goal: {goal}\n"
                f"- Suggested subject: {subject}\n"
                f"- Plan: {report_path}\n"
                "- Commit performed: no\n"
                "- Push performed: no\n\n"
                "Status:\n"
                f"{summary.get('status') or 'clean'}\n\n"
                "Diff stat:\n"
                f"{summary.get('diff_stat') or 'no unstaged diff'}\n\n"
                "Steps:\n"
                + "\n".join(f"- {step}" for step in plan["steps"]),
                metadata={**plan, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to create GitHub commit plan: {exc}", success=False)


@ToolRegistry.register("serena_github_commit_message")
class SerenaGitHubCommitMessageTool(_GitHubBaseTool):
    tool_id = "serena_github_commit_message"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Draft a commit message from local Git changes without committing.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "style": {"type": "string"},
                },
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            style = str(params.get("style") or "standard").strip()

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            summary = _changes_summary(key, path)
            subject = _infer_commit_subject(summary)

            changed_files = summary.get("diff_name_only") or summary.get("staged_name_only") or ""
            file_lines = [line.strip() for line in changed_files.splitlines() if line.strip()]

            body_lines = [
                subject,
                "",
                "Summary:",
                "- Update local Serena project files.",
                "- Preserve approval-gated GitHub remote workflow.",
                "- No push performed.",
            ]

            if file_lines:
                body_lines.extend(["", "Changed files:"])
                body_lines.extend(f"- {item}" for item in file_lines[:40])

            content = "\n".join(body_lines).strip() + "\n"
            draft_path = _draft_text("commit-message", subject, content)

            payload = {
                "report_type": "serena_github_commit_message",
                "created_at": _timestamp(),
                "root": key,
                "style": style,
                "subject": subject,
                "draft_path": str(draft_path),
                "changes": summary,
                "commit_performed": False,
                "push_performed": False,
            }
            report_path = _save_json("drafts", f"{key}-commit-message", payload)

            return self._result(
                "Serena GitHub commit message drafted\n\n"
                f"- Root: {key}\n"
                f"- Branch: {summary.get('branch') or 'unknown'}\n"
                f"- Subject: {subject}\n"
                f"- Draft: {draft_path}\n"
                f"- Report: {report_path}\n"
                "- Commit performed: no\n"
                "- Push performed: no\n\n"
                "Draft:\n"
                f"{content}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to draft commit message: {exc}", success=False)


@ToolRegistry.register("serena_github_pr_summary")
class SerenaGitHubPRSummaryTool(_GitHubBaseTool):
    tool_id = "serena_github_pr_summary"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Draft a pull request summary from local changes without creating a PR.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "title": {"type": "string"},
                },
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            title = str(params.get("title") or "").strip()

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            summary = _changes_summary(key, path)
            subject = title or _infer_commit_subject(summary, "Serena project updates")
            changed = summary.get("diff_name_only") or summary.get("staged_name_only") or ""
            changed_files = [line.strip() for line in changed.splitlines() if line.strip()]

            content_lines = [
                f"# {subject}",
                "",
                "## Summary",
                "",
                "- Prepared local Serena project updates.",
                "- Generated this PR summary as a draft only.",
                "- No remote PR was created.",
                "",
                "## Changed files",
                "",
            ]

            content_lines.extend(f"- `{item}`" for item in changed_files[:80]) if changed_files else content_lines.append("- No changed files detected.")

            content_lines.extend([
                "",
                "## Safety",
                "",
                "- Push performed: no",
                "- PR created: no",
                "- Merge performed: no",
                "- Remote writes require explicit approval/future approval-gated layer.",
                "",
                "## Suggested checks",
                "",
                "- Run Serena VS Code final-check.",
                "- Review diff stat.",
                "- Confirm only intended files are included.",
            ])

            content = "\n".join(content_lines) + "\n"
            draft_path = _draft_text("pr-summary", subject, content)

            payload = {
                "report_type": "serena_github_pr_summary",
                "created_at": _timestamp(),
                "root": key,
                "title": subject,
                "draft_path": str(draft_path),
                "changes": summary,
                "pr_created": False,
                "push_performed": False,
                "merge_performed": False,
            }
            report_path = _save_json("drafts", f"{key}-pr-summary", payload)

            return self._result(
                "Serena GitHub PR summary drafted\n\n"
                f"- Root: {key}\n"
                f"- Title: {subject}\n"
                f"- Draft: {draft_path}\n"
                f"- Report: {report_path}\n"
                "- PR created: no\n"
                "- Push performed: no\n\n"
                "Preview:\n"
                f"{content[:3000]}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to draft PR summary: {exc}", success=False)


@ToolRegistry.register("serena_github_issue_draft")
class SerenaGitHubIssueDraftTool(_GitHubBaseTool):
    tool_id = "serena_github_issue_draft"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Draft a GitHub issue locally without creating it remotely.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "required": ["root", "title", "body"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            title = str(params.get("title") or "").strip()
            body = str(params.get("body") or "").strip()
            kind = str(params.get("kind") or "issue").strip()

            if not title or not body:
                return self._result("Title and body are required.", success=False)

            content = (
                f"# {title}\n\n"
                f"Type: {kind}\n\n"
                "## Description\n\n"
                f"{body}\n\n"
                "## Safety\n\n"
                "- GitHub issue created remotely: no\n"
                "- Remote writes require explicit approval/future approval-gated layer.\n"
            )

            draft_path = _draft_text("issue-draft", title, content)

            payload = {
                "report_type": "serena_github_issue_draft",
                "created_at": _timestamp(),
                "root": key,
                "title": title,
                "kind": kind,
                "draft_path": str(draft_path),
                "remote_issue_created": False,
            }
            report_path = _save_json("drafts", f"{key}-issue-draft", payload)

            return self._result(
                "Serena GitHub issue draft created\n\n"
                f"- Root: {key}\n"
                f"- Type: {kind}\n"
                f"- Title: {title}\n"
                f"- Draft: {draft_path}\n"
                f"- Report: {report_path}\n"
                "- Remote issue created: no\n\n"
                "Preview:\n"
                f"{content[:2500]}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to create GitHub issue draft: {exc}", success=False)


@ToolRegistry.register("serena_github_bug_report")
class SerenaGitHubBugReportTool(_GitHubBaseTool):
    tool_id = "serena_github_bug_report"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Draft a GitHub bug report locally without creating it remotely.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "title": {"type": "string"},
                    "problem": {"type": "string"},
                    "steps": {"type": "string"},
                    "expected": {"type": "string"},
                    "actual": {"type": "string"},
                },
                "required": ["root", "title", "problem"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            title = str(params.get("title") or "").strip()
            problem = str(params.get("problem") or "").strip()
            steps = str(params.get("steps") or "Not provided.").strip()
            expected = str(params.get("expected") or "Not provided.").strip()
            actual = str(params.get("actual") or "Not provided.").strip()

            body = (
                f"## Problem\n\n{problem}\n\n"
                f"## Steps to reproduce\n\n{steps}\n\n"
                f"## Expected behavior\n\n{expected}\n\n"
                f"## Actual behavior\n\n{actual}\n"
            )

            return SerenaGitHubIssueDraftTool().execute(
                root=str(params.get("root") or ""),
                title=f"[BUG] {title}",
                body=body,
                kind="bug",
            )
        except Exception as exc:
            return self._result(f"Failed to draft bug report: {exc}", success=False)


@ToolRegistry.register("serena_github_feature_request")
class SerenaGitHubFeatureRequestTool(_GitHubBaseTool):
    tool_id = "serena_github_feature_request"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Draft a GitHub feature request locally without creating it remotely.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "value": {"type": "string"},
                    "acceptance": {"type": "string"},
                },
                "required": ["root", "title", "summary"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            title = str(params.get("title") or "").strip()
            summary = str(params.get("summary") or "").strip()
            value = str(params.get("value") or "Not provided.").strip()
            acceptance = str(params.get("acceptance") or "Not provided.").strip()

            body = (
                f"## Summary\n\n{summary}\n\n"
                f"## Value\n\n{value}\n\n"
                f"## Acceptance criteria\n\n{acceptance}\n"
            )

            return SerenaGitHubIssueDraftTool().execute(
                root=str(params.get("root") or ""),
                title=f"[FEATURE] {title}",
                body=body,
                kind="feature",
            )
        except Exception as exc:
            return self._result(f"Failed to draft feature request: {exc}", success=False)


@ToolRegistry.register("serena_github_release_notes")
class SerenaGitHubReleaseNotesTool(_GitHubBaseTool):
    tool_id = "serena_github_release_notes"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Draft release notes from recent commits and local changes without publishing a release.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "title": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            title = str(params.get("title") or "Serena local release notes draft").strip()
            limit = int(params.get("limit") or 20)

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            commits = _run_git(path, ["log", "--oneline", "-n", str(limit)])
            summary = _changes_summary(key, path)

            content = (
                f"# {title}\n\n"
                "## Recent commits\n\n"
                + (commits["output"] or "No recent commits found.")
                + "\n\n## Local changes\n\n"
                + (summary.get("status") or "clean")
                + "\n\n## Safety\n\n"
                "- Release published: no\n"
                "- Tag created: no\n"
                "- Push performed: no\n"
                "- Remote release actions require explicit approval/future approval-gated layer.\n"
            )

            draft_path = _draft_text("release-notes", title, content)

            payload = {
                "report_type": "serena_github_release_notes",
                "created_at": _timestamp(),
                "root": key,
                "title": title,
                "limit": limit,
                "draft_path": str(draft_path),
                "release_published": False,
                "tag_created": False,
                "push_performed": False,
            }
            report_path = _save_json("drafts", f"{key}-release-notes", payload)

            return self._result(
                "Serena GitHub release notes drafted\n\n"
                f"- Root: {key}\n"
                f"- Title: {title}\n"
                f"- Draft: {draft_path}\n"
                f"- Report: {report_path}\n"
                "- Release published: no\n"
                "- Tag created: no\n"
                "- Push performed: no\n\n"
                "Preview:\n"
                f"{content[:3000]}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to draft release notes: {exc}", success=False)


@ToolRegistry.register("serena_github_final_check")
class SerenaGitHubFinalCheckTool(_GitHubBaseTool):
    tool_id = "serena_github_final_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Run final Serena GitHub local safety check before commit/PR/push review.",
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

            safety = SerenaGitHubSafetyCheckTool().execute(root=key)
            changes = SerenaGitHubChangesTool().execute(root=key)
            branch = _run_git(path, ["branch", "--show-current"])

            payload = {
                "report_type": "serena_github_final_check",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "branch": branch["output"],
                "safety_success": safety.success,
                "changes_success": changes.success,
                "remote_writes_performed": False,
                "push_performed": False,
                "force_push_performed": False,
                "pr_created": False,
                "issue_created": False,
                "release_published": False,
            }
            report_path = _save_json("reports", f"{key}-final-check", payload)

            return self._result(
                "Serena GitHub final check\n\n"
                f"- Root: {key}\n"
                f"- Branch: {branch['output'] or 'unknown'}\n"
                f"- Safety check success: {safety.success}\n"
                f"- Changes check success: {changes.success}\n"
                f"- Report: {report_path}\n"
                "- Remote writes performed: no\n"
                "- Push performed: no\n"
                "- Force-push performed: no\n"
                "- PR created: no\n"
                "- Issue created: no\n"
                "- Release published: no\n\n"
                "Safety summary:\n"
                f"{safety.content[:3000]}",
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to run GitHub final check: {exc}", success=False)


def _parse_file_list(raw: str) -> list[str]:
    items: list[str] = []
    for part in str(raw or "").replace("\n", ",").split(","):
        item = part.strip().strip('"').strip("'")
        if item:
            items.append(item)
    return items


def _validate_git_relative_file(path: str) -> str:
    value = str(path or "").replace("\\", "/").strip()
    if not value:
        raise RuntimeError("Empty file path is not allowed.")
    if value.startswith("/") or value.startswith("../") or "/../" in value or value == "..":
        raise RuntimeError(f"Unsafe file path: {path}")
    lowered = value.lower()
    blocked = [".env", "secret", "secrets", "credential", "credentials", "password", "token"]
    if any(item in lowered for item in blocked):
        raise RuntimeError(f"Refusing to stage sensitive-looking file path: {path}")
    return value


@ToolRegistry.register("serena_github_stage_plan")
class SerenaGitHubStagePlanTool(_GitHubBaseTool):
    tool_id = "serena_github_stage_plan"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create a staging plan without staging files.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "files": {"type": "string"},
                },
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            files_raw = str(params.get("files") or "").strip()

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            summary = _changes_summary(key, path)

            if files_raw:
                requested_files = [_validate_git_relative_file(item) for item in _parse_file_list(files_raw)]
            else:
                combined = []
                for source in [summary.get("diff_name_only") or "", summary.get("staged_name_only") or ""]:
                    combined.extend(line.strip() for line in source.splitlines() if line.strip())

                # Include untracked paths from git status short.
                for line in (summary.get("status") or "").splitlines():
                    if line.startswith("?? "):
                        combined.append(line[3:].strip())

                requested_files = sorted(set(_validate_git_relative_file(item) for item in combined if item.strip()))

            payload = {
                "report_type": "serena_github_stage_plan",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "branch": summary.get("branch"),
                "requested_files": requested_files,
                "status": summary.get("status"),
                "diff_stat": summary.get("diff_stat"),
                "stage_performed": False,
                "commit_performed": False,
                "push_performed": False,
            }
            report_path = _save_json("plans", f"{key}-stage-plan", payload)

            return self._result(
                "Serena GitHub stage plan\n\n"
                f"- Root: {key}\n"
                f"- Branch: {summary.get('branch') or 'unknown'}\n"
                f"- Files proposed for staging: {len(requested_files)}\n"
                f"- Report: {report_path}\n"
                "- Stage performed: no\n"
                "- Commit performed: no\n"
                "- Push performed: no\n\n"
                "Proposed files:\n"
                + ("\n".join(f"- {item}" for item in requested_files) if requested_files else "- none")
                + "\n\nStatus:\n"
                + (summary.get("status") or "clean"),
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to create stage plan: {exc}", success=False)


@ToolRegistry.register("serena_github_commit_local")
class SerenaGitHubCommitLocalTool(_GitHubBaseTool):
    tool_id = "serena_github_commit_local"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Stage selected files and create a local commit only when explicitly approved. Does not push.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "message": {"type": "string"},
                    "files": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["root", "message"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            message = str(params.get("message") or "").strip()
            files_raw = str(params.get("files") or "").strip()
            approved = bool(params.get("approved", False))

            if not approved:
                return self._result(
                    "Local commit blocked. Creating a commit changes repository history and requires --approved.\n\n"
                    "- Stage performed: no\n"
                    "- Commit performed: no\n"
                    "- Push performed: no",
                    success=False,
                    metadata={
                        "root": key,
                        "approved": False,
                        "stage_performed": False,
                        "commit_performed": False,
                        "push_performed": False,
                    },
                )

            if not message:
                return self._result("Commit blocked. Commit message is required.", success=False)

            if not _is_git_repo(path):
                return self._result(f"Approved root is not a Git repository: {path}", success=False)

            if files_raw:
                files = [_validate_git_relative_file(item) for item in _parse_file_list(files_raw)]
            else:
                summary = _changes_summary(key, path)
                files = []
                for source in [summary.get("diff_name_only") or "", summary.get("staged_name_only") or ""]:
                    files.extend(line.strip() for line in source.splitlines() if line.strip())
                for line in (summary.get("status") or "").splitlines():
                    if line.startswith("?? "):
                        files.append(line[3:].strip())
                files = sorted(set(_validate_git_relative_file(item) for item in files if item.strip()))

            if not files:
                return self._result("Commit blocked. No files selected for staging.", success=False)

            safety = SerenaGitHubSafetyCheckTool().execute(root=key)
            if not safety.success:
                return self._result("Commit blocked. Safety check failed.\n\n" + safety.content, success=False)

            stage_result = _run_git(path, ["add", "--"] + files)
            if stage_result["returncode"] != 0:
                return self._result(
                    "Commit blocked. git add failed.\n\n"
                    f"{stage_result['output']}",
                    success=False,
                    metadata={"stage_result": stage_result, "files": files},
                )

            commit_result = _run_git(path, ["commit", "-m", message], timeout=120)
            commit_success = commit_result["returncode"] == 0

            after_summary = _changes_summary(key, path)

            payload = {
                "report_type": "serena_github_commit_local",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "message": message,
                "files": files,
                "approved": approved,
                "stage_result": stage_result,
                "commit_result": commit_result,
                "commit_success": commit_success,
                "after_summary": after_summary,
                "stage_performed": True,
                "commit_performed": commit_success,
                "push_performed": False,
                "remote_writes_performed": False,
            }
            report_path = _save_json("reports", f"{key}-commit-local", payload)

            if commit_success:
                return self._result(
                    "Serena GitHub local commit created\n\n"
                    f"- Root: {key}\n"
                    f"- Message: {message}\n"
                    f"- Files staged: {len(files)}\n"
                    f"- Report: {report_path}\n"
                    "- Stage performed: yes\n"
                    "- Commit performed: yes\n"
                    "- Push performed: no\n"
                    "- Remote writes performed: no\n\n"
                    "Commit output:\n"
                    f"{commit_result['output']}",
                    metadata={**payload, "report_path": str(report_path)},
                )

            return self._result(
                "Serena GitHub local commit failed\n\n"
                f"- Root: {key}\n"
                f"- Files staged: {len(files)}\n"
                f"- Report: {report_path}\n"
                "- Stage performed: yes\n"
                "- Commit performed: no\n"
                "- Push performed: no\n\n"
                "Git output:\n"
                f"{commit_result['output']}",
                success=False,
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to create local Git commit: {exc}", success=False)


@ToolRegistry.register("serena_github_push_check")
class SerenaGitHubPushCheckTool(_GitHubBaseTool):
    tool_id = "serena_github_push_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Check push readiness without pushing.",
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

            branch = _run_git(path, ["branch", "--show-current"])
            remotes = _run_git(path, ["remote", "-v"])
            status = _run_git(path, ["status", "--short", "--branch"])
            upstream = _run_git(path, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])

            issues: list[str] = []
            recommendations: list[str] = []

            if not branch["output"]:
                issues.append("Current branch could not be detected.")
            if not remotes["output"]:
                issues.append("No remotes detected.")
            if status["output"] and "\n" in status["output"]:
                recommendations.append("Local changes are present. Commit or intentionally leave them before pushing.")
            if upstream["returncode"] != 0:
                recommendations.append("No upstream tracking branch detected or upstream could not be resolved.")

            payload = {
                "report_type": "serena_github_push_check",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "branch": branch["output"],
                "remotes": remotes["output"],
                "status": status["output"],
                "upstream": upstream["output"],
                "issues": issues,
                "recommendations": recommendations,
                "push_performed": False,
                "push_allowed_v1": False,
            }
            report_path = _save_json("reports", f"{key}-push-check", payload)

            lines = [
                "Serena GitHub push check",
                "",
                f"- Root: {key}",
                f"- Branch: {branch['output'] or 'unknown'}",
                f"- Upstream: {upstream['output'] or 'unknown'}",
                f"- Report: {report_path}",
                "- Push performed: no",
                "- Push allowed in v1: no",
                "",
                "Issues:",
            ]
            lines.extend(f"- {issue}" for issue in issues) if issues else lines.append("- none")
            lines.extend(["", "Recommendations:"])
            lines.extend(f"- {rec}" for rec in recommendations) if recommendations else lines.append("- No immediate recommendations.")
            lines.extend([
                "",
                "Policy:",
                "- Serena GitHub v1 can inspect, plan, draft, and create local commits.",
                "- Remote push is deferred to a future explicit approval-gated GitHub v2 layer.",
            ])

            return self._result("\n".join(lines), metadata={**payload, "report_path": str(report_path)})
        except Exception as exc:
            return self._result(f"Failed to run push check: {exc}", success=False)


@ToolRegistry.register("serena_github_push_approved")
class SerenaGitHubPushApprovedTool(_GitHubBaseTool):
    tool_id = "serena_github_push_approved"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Deliberately blocked push command for GitHub v1.",
            parameters={
                "type": "object",
                "properties": {
                    "root": {"type": "string"},
                    "approved": {"type": "boolean"},
                },
                "required": ["root"],
            },
            category="serena_github",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            key, root, path = _resolve_root(str(params.get("root") or ""))
            approved = bool(params.get("approved", False))

            payload = {
                "report_type": "serena_github_push_approved_blocked",
                "created_at": _timestamp(),
                "root": key,
                "path": str(path),
                "approved_flag_received": approved,
                "push_performed": False,
                "remote_writes_performed": False,
                "blocked_reason": "GitHub v1 deliberately blocks remote pushes. Use future GitHub v2 approval-gated remote layer.",
            }
            report_path = _save_json("reports", f"{key}-push-blocked", payload)

            return self._result(
                "GitHub push blocked by Serena GitHub v1 policy\n\n"
                f"- Root: {key}\n"
                f"- Approved flag received: {'yes' if approved else 'no'}\n"
                f"- Report: {report_path}\n"
                "- Push performed: no\n"
                "- Remote writes performed: no\n\n"
                "Reason:\n"
                "- Serena GitHub v1 is allowed to inspect, plan, draft, and create local commits only.\n"
                "- Remote push is intentionally deferred to a future explicit approval-gated GitHub v2 layer.",
                success=False,
                metadata={**payload, "report_path": str(report_path)},
            )
        except Exception as exc:
            return self._result(f"Failed to evaluate push approval: {exc}", success=False)


__all__ = [
    "SerenaGitHubStatusTool",
    "SerenaGitHubRepoInfoTool",
    "SerenaGitHubBranchesTool",
    "SerenaGitHubRemotesTool",
    "SerenaGitHubRecentCommitsTool",
    "SerenaGitHubChangesTool",
    "SerenaGitHubSafetyCheckTool",
    "SerenaGitHubFinalCheckTool",
    "SerenaGitHubPushApprovedTool",
    "SerenaGitHubPushCheckTool",
    "SerenaGitHubCommitLocalTool",
    "SerenaGitHubStagePlanTool",
    "SerenaGitHubReleaseNotesTool",
    "SerenaGitHubFeatureRequestTool",
    "SerenaGitHubBugReportTool",
    "SerenaGitHubIssueDraftTool",
    "SerenaGitHubPRSummaryTool",
    "SerenaGitHubCommitMessageTool",
    "SerenaGitHubCommitPlanTool",
]
