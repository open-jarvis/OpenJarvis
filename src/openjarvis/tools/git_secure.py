"""Narrow Git operations with task-worktree isolation and push denial."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec
from openjarvis.tools.manifest import ToolManifest, manifest_from_spec
from openjarvis.tools.safe_filesystem import SecurePathPolicy

_OUTPUT_LIMIT = 100_000
_BRANCH = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$")


class GitPolicyError(PermissionError):
    pass


def _run_git(
    cwd: Path, arguments: list[str], timeout: int = 60
) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if not git:
        raise GitPolicyError("git executable not found")
    result = subprocess.run(
        [git, *arguments],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "git command failed").strip()
        raise GitPolicyError(message[:_OUTPUT_LIMIT])
    return result


class SecureGitService:
    """Git authority limited to one integration repo and owned worktrees."""

    def __init__(
        self,
        *,
        integration_repo: str | Path,
        worktree_root: str | Path,
        artifact_root: str | Path,
        task_branch_prefix: str = "task/",
    ) -> None:
        self.integration_repo = Path(integration_repo).resolve(strict=True)
        if not (self.integration_repo / ".git").exists():
            raise ValueError("integration_repo is not a Git repository")
        self.worktree_root = Path(worktree_root).resolve(strict=False)
        self.worktree_root.mkdir(parents=True, exist_ok=True)
        self.artifact_root = Path(artifact_root).resolve(strict=False)
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.task_branch_prefix = task_branch_prefix
        self._paths = SecurePathPolicy(
            (self.integration_repo, self.worktree_root),
            self.artifact_root,
        )
        self._ownership_root = self.worktree_root / ".openjarvis-ownership"
        self._ownership_root.mkdir(exist_ok=True)

    def _repository(self, value: str | Path, *, mutation: bool = False) -> Path:
        path = self._paths.resolve(str(value), must_exist=True)
        top = Path(
            _run_git(path, ["rev-parse", "--show-toplevel"]).stdout.strip()
        ).resolve(strict=True)
        if top == self.integration_repo:
            if mutation:
                raise GitPolicyError(
                    "mutations require an owned task worktree, not integration_repo"
                )
            return top
        if not self._owned(top):
            raise GitPolicyError("repository is not an owned task worktree")
        return top

    def _ownership_file(self, worktree: Path) -> Path:
        digest = hashlib.sha256(str(worktree).casefold().encode("utf-8")).hexdigest()
        return self._ownership_root / f"{digest}.json"

    def _owned(self, worktree: Path) -> bool:
        record = self._ownership_file(worktree)
        if not record.is_file():
            return False
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return os.path.normcase(data.get("worktree", "")) == os.path.normcase(
            str(worktree)
        )

    def verify_remote_safety(self) -> dict[str, str]:
        remotes = _run_git(self.integration_repo, ["remote"]).stdout.split()
        if "upstream" not in remotes:
            return {"upstream_fetch": "not-configured", "upstream_push": "DISABLED"}
        fetch = _run_git(
            self.integration_repo,
            ["remote", "get-url", "upstream"],
        ).stdout.strip()
        push = _run_git(
            self.integration_repo,
            ["remote", "get-url", "--push", "upstream"],
        ).stdout.strip()
        if push != "DISABLED":
            raise GitPolicyError("upstream push URL must be DISABLED")
        return {"upstream_fetch": fetch, "upstream_push": push}

    @staticmethod
    def reject_push(*, remote: str, force: bool = False, tags: bool = False) -> None:
        detail = "force-push" if force else "tag push" if tags else "push"
        raise GitPolicyError(f"{detail} to {remote} is disabled in Phase 5")

    def status(self, repo: str | Path) -> str:
        root = self._repository(repo)
        return _run_git(root, ["status", "--short", "--branch"]).stdout

    def diff(self, repo: str | Path, *, staged: bool = False) -> str:
        root = self._repository(repo)
        args = ["diff", "--no-ext-diff"]
        if staged:
            args.append("--cached")
        return _run_git(root, args).stdout[:_OUTPUT_LIMIT]

    def log(self, repo: str | Path, *, count: int = 10) -> str:
        root = self._repository(repo)
        count = min(max(int(count), 1), 100)
        return _run_git(root, ["log", f"-{count}", "--oneline", "--decorate"]).stdout

    def branch(self, repo: str | Path) -> dict[str, Any]:
        root = self._repository(repo)
        name = _run_git(root, ["branch", "--show-current"]).stdout.strip()
        head = _run_git(root, ["rev-parse", "HEAD"]).stdout.strip()
        return {"branch": name, "head": head, "owned_worktree": self._owned(root)}

    def create_worktree(
        self,
        *,
        destination: str | Path,
        branch: str,
        start_point: str = "HEAD",
    ) -> dict[str, str]:
        if not _BRANCH.fullmatch(branch) or not branch.startswith(
            self.task_branch_prefix
        ):
            raise GitPolicyError(
                f"task branch must start with {self.task_branch_prefix!r}"
            )
        if _run_git(self.integration_repo, ["status", "--porcelain"]).stdout:
            raise GitPolicyError("integration repository must be clean")
        destination_path = self._paths.resolve(str(destination))
        if destination_path.exists():
            raise GitPolicyError("worktree destination already exists")
        if (
            not str(destination_path)
            .casefold()
            .startswith(str(self.worktree_root).casefold() + os.sep.casefold())
        ):
            raise GitPolicyError("worktree destination escaped worktree_root")
        _run_git(
            self.integration_repo,
            ["worktree", "add", "-b", branch, str(destination_path), start_point],
            timeout=120,
        )
        observed_branch = _run_git(
            destination_path, ["branch", "--show-current"]
        ).stdout.strip()
        if observed_branch != branch:
            raise GitPolicyError("worktree branch verification failed")
        record = {
            "worktree": str(destination_path),
            "branch": branch,
            "integration_repo": str(self.integration_repo),
        }
        self._ownership_file(destination_path).write_text(
            json.dumps(record, indent=2), encoding="utf-8"
        )
        if not self._owned(destination_path):
            raise GitPolicyError("worktree ownership verification failed")
        return {"worktree": str(destination_path), "branch": branch}

    def remove_worktree(self, worktree: str | Path) -> dict[str, str]:
        path = self._repository(worktree, mutation=True)
        status = _run_git(path, ["status", "--porcelain"]).stdout
        if status:
            raise GitPolicyError("refusing to remove a dirty task worktree")
        ownership = self._ownership_file(path)
        _run_git(
            self.integration_repo,
            ["worktree", "remove", str(path)],
            timeout=120,
        )
        if path.exists():
            raise GitPolicyError("worktree removal verification failed")
        ownership.unlink(missing_ok=True)
        return {"worktree": str(path), "removed": "true"}

    def commit(
        self,
        *,
        worktree: str | Path,
        files: list[str],
        message: str,
    ) -> dict[str, str]:
        root = self._repository(worktree, mutation=True)
        branch = self.branch(root)["branch"]
        if not branch.startswith(self.task_branch_prefix):
            raise GitPolicyError("commit branch is not an isolated task branch")
        if not files:
            raise GitPolicyError("an explicit non-empty file list is required")
        validated: list[str] = []
        for value in files:
            supplied = Path(value)
            if supplied.is_absolute() or ".." in supplied.parts or value == ".":
                raise GitPolicyError(f"unsafe commit path: {value}")
            target = (root / supplied).resolve(strict=False)
            if (
                not str(target)
                .casefold()
                .startswith(str(root).casefold() + os.sep.casefold())
            ):
                raise GitPolicyError(f"commit path escaped worktree: {value}")
            validated.append(value)
        old_head = _run_git(root, ["rev-parse", "HEAD"]).stdout.strip()
        _run_git(root, ["add", "--", *validated])
        staged_diff = self.diff(root, staged=True)
        if not staged_diff:
            raise GitPolicyError("no staged changes to commit")
        _run_git(root, ["diff", "--cached", "--check"])
        _run_git(root, ["commit", "-m", message], timeout=120)
        new_head = _run_git(root, ["rev-parse", "HEAD"]).stdout.strip()
        if new_head == old_head:
            raise GitPolicyError("commit did not advance HEAD")
        return {
            "old_head": old_head,
            "new_head": new_head,
            "branch": branch,
            "diff": staged_diff,
        }

    def restore(
        self,
        *,
        worktree: str | Path,
        files: list[str],
        artifact_name: str,
    ) -> dict[str, str]:
        root = self._repository(worktree, mutation=True)
        if not files:
            raise GitPolicyError("an explicit file list is required")
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", artifact_name):
            raise GitPolicyError("invalid restore artifact name")
        for value in files:
            if Path(value).is_absolute() or ".." in Path(value).parts or value == ".":
                raise GitPolicyError(f"unsafe restore path: {value}")
        patch = _run_git(root, ["diff", "--binary", "HEAD", "--", *files]).stdout
        artifact = self.artifact_root / f"{artifact_name}.patch"
        artifact.write_text(patch, encoding="utf-8")
        _run_git(
            root,
            ["restore", "--source", "HEAD", "--staged", "--worktree", "--", *files],
        )
        remaining = _run_git(root, ["diff", "--", *files]).stdout
        if remaining:
            raise GitPolicyError("git restore verification failed")
        return {
            "artifact": str(artifact),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "verified": "true",
        }

    def create_bundle(self, *, ref: str, artifact_name: str) -> dict[str, str]:
        if not re.fullmatch(r"[a-zA-Z0-9._-]{1,128}", artifact_name):
            raise GitPolicyError("invalid bundle artifact name")
        bundle = self.artifact_root / f"{artifact_name}.bundle"
        _run_git(
            self.integration_repo, ["bundle", "create", str(bundle), ref], timeout=120
        )
        verification = self.verify_bundle(bundle)
        verification["bundle"] = str(bundle)
        verification["sha256"] = hashlib.sha256(bundle.read_bytes()).hexdigest()
        return verification

    def verify_bundle(self, bundle: str | Path) -> dict[str, str]:
        path = Path(bundle).resolve(strict=True)
        if (
            not str(path)
            .casefold()
            .startswith(str(self.artifact_root).casefold() + os.sep.casefold())
        ):
            raise GitPolicyError("bundle escaped artifact root")
        output = _run_git(self.integration_repo, ["bundle", "verify", str(path)]).stdout
        heads = _run_git(
            self.integration_repo, ["bundle", "list-heads", str(path)]
        ).stdout
        return {"verification": output.strip(), "heads": heads.strip()}


class _GitTool(BaseTool):
    def __init__(self, service: SecureGitService) -> None:
        self.service = service

    @property
    def manifest(self) -> ToolManifest:
        return manifest_from_spec(self.tool_id, self.spec).model_copy(
            update={
                "allowed_roots": (
                    str(self.service.integration_repo),
                    str(self.service.worktree_root),
                    str(self.service.artifact_root),
                )
            }
        )

    def _result(self, operation) -> ToolResult:
        try:
            value = operation()
            content = (
                value if isinstance(value, str) else json.dumps(value, sort_keys=True)
            )
            return ToolResult(
                tool_name=self.tool_id, content=content, metadata={"result": value}
            )
        except (GitPolicyError, OSError, subprocess.SubprocessError, ValueError) as exc:
            return ToolResult(tool_name=self.tool_id, content=str(exc), success=False)


@ToolRegistry.register("git.status")
class SafeGitStatusTool(_GitTool):
    tool_id = "git.status"

    @property
    def spec(self) -> ToolSpec:
        return _git_read_spec(self.tool_id, "Read Git status.")

    def execute(self, **params: Any) -> ToolResult:
        return self._result(lambda: self.service.status(params["repo"]))


@ToolRegistry.register("git.diff")
class SafeGitDiffTool(_GitTool):
    tool_id = "git.diff"

    @property
    def spec(self) -> ToolSpec:
        spec = _git_read_spec(self.tool_id, "Read a bounded Git diff.")
        spec.parameters["properties"]["staged"] = {"type": "boolean"}
        return spec

    def execute(self, **params: Any) -> ToolResult:
        return self._result(
            lambda: self.service.diff(
                params["repo"], staged=params.get("staged", False)
            )
        )


@ToolRegistry.register("git.log")
class SafeGitLogTool(_GitTool):
    tool_id = "git.log"

    @property
    def spec(self) -> ToolSpec:
        spec = _git_read_spec(self.tool_id, "Read bounded Git history.")
        spec.parameters["properties"]["count"] = {"type": "integer"}
        return spec

    def execute(self, **params: Any) -> ToolResult:
        return self._result(
            lambda: self.service.log(params["repo"], count=params.get("count", 10))
        )


@ToolRegistry.register("git.branch")
class SafeGitBranchTool(_GitTool):
    tool_id = "git.branch"

    @property
    def spec(self) -> ToolSpec:
        return _git_read_spec(self.tool_id, "Read branch and HEAD information.")

    def execute(self, **params: Any) -> ToolResult:
        return self._result(lambda: self.service.branch(params["repo"]))


@ToolRegistry.register("git.worktree.create")
class SafeGitWorktreeCreateTool(_GitTool):
    tool_id = "git.worktree.create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create an isolated owned task worktree and task branch.",
            parameters={
                "type": "object",
                "properties": {
                    "destination": {"type": "string", "minLength": 1},
                    "branch": {"type": "string", "minLength": 1},
                    "start_point": {"type": "string", "minLength": 1},
                },
                "required": ["destination", "branch"],
            },
            category="vcs",
            required_capabilities=["file:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        return self._result(
            lambda: self.service.create_worktree(
                destination=params["destination"],
                branch=params["branch"],
                start_point=params.get("start_point", "HEAD"),
            )
        )


@ToolRegistry.register("git.worktree.remove")
class SafeGitWorktreeRemoveTool(_GitTool):
    tool_id = "git.worktree.remove"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Remove only a clean OpenJarvis-owned task worktree.",
            parameters={
                "type": "object",
                "properties": {"worktree": {"type": "string", "minLength": 1}},
                "required": ["worktree"],
            },
            category="vcs",
            requires_confirmation=True,
            required_capabilities=["file:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        return self._result(lambda: self.service.remove_worktree(params["worktree"]))


@ToolRegistry.register("git.commit")
class SafeGitCommitTool(_GitTool):
    tool_id = "git.commit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Commit explicit files only in an owned task worktree.",
            parameters={
                "type": "object",
                "properties": {
                    "worktree": {"type": "string", "minLength": 1},
                    "files": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "maxItems": 256,
                    },
                    "message": {"type": "string", "minLength": 1},
                },
                "required": ["worktree", "files", "message"],
            },
            category="vcs",
            required_capabilities=["file:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        return self._result(
            lambda: self.service.commit(
                worktree=params["worktree"],
                files=params["files"],
                message=params["message"],
            )
        )


@ToolRegistry.register("git.restore")
class SafeGitRestoreTool(_GitTool):
    tool_id = "git.restore"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description=(
                "Restore explicit task-worktree files after saving a patch artifact."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "worktree": {"type": "string", "minLength": 1},
                    "files": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "maxItems": 256,
                    },
                    "artifact_name": {"type": "string", "minLength": 1},
                },
                "required": ["worktree", "files", "artifact_name"],
            },
            category="vcs",
            requires_confirmation=True,
            required_capabilities=["file:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        return self._result(
            lambda: self.service.restore(
                worktree=params["worktree"],
                files=params["files"],
                artifact_name=params["artifact_name"],
            )
        )


@ToolRegistry.register("git.bundle.create")
class SafeGitBundleCreateTool(_GitTool):
    tool_id = "git.bundle.create"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Create and verify a bounded recovery bundle artifact.",
            parameters={
                "type": "object",
                "properties": {
                    "ref": {"type": "string", "minLength": 1},
                    "artifact_name": {"type": "string", "minLength": 1},
                },
                "required": ["ref", "artifact_name"],
            },
            category="vcs",
            required_capabilities=["file:write"],
        )

    def execute(self, **params: Any) -> ToolResult:
        return self._result(
            lambda: self.service.create_bundle(
                ref=params["ref"], artifact_name=params["artifact_name"]
            )
        )


@ToolRegistry.register("git.bundle.verify")
class SafeGitBundleVerifyTool(_GitTool):
    tool_id = "git.bundle.verify"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.tool_id,
            description="Verify one bundle from the isolated artifact root.",
            parameters={
                "type": "object",
                "properties": {"bundle": {"type": "string", "minLength": 1}},
                "required": ["bundle"],
            },
            category="vcs",
            required_capabilities=["file:read"],
        )

    def execute(self, **params: Any) -> ToolResult:
        return self._result(lambda: self.service.verify_bundle(params["bundle"]))


def _git_read_spec(name: str, description: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        parameters={
            "type": "object",
            "properties": {"repo": {"type": "string", "minLength": 1}},
            "required": ["repo"],
        },
        category="vcs",
        required_capabilities=["file:read"],
    )


__all__ = [
    "GitPolicyError",
    "SafeGitBranchTool",
    "SafeGitBundleCreateTool",
    "SafeGitBundleVerifyTool",
    "SafeGitCommitTool",
    "SafeGitDiffTool",
    "SafeGitLogTool",
    "SafeGitRestoreTool",
    "SafeGitStatusTool",
    "SafeGitWorktreeCreateTool",
    "SafeGitWorktreeRemoveTool",
    "SecureGitService",
]
