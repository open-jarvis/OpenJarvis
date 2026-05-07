"""Model-callable tools wrapping the GitHub REST client."""

from __future__ import annotations

import json
from typing import Any, Optional

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.integrations.github import (
    GitHubClient,
    GitHubUnavailableError,
    get_default_client,
)
from openjarvis.tools._stubs import BaseTool, ToolSpec


def _ok(name: str, payload: Any) -> ToolResult:
    if not isinstance(payload, str):
        try:
            payload = json.dumps(payload, default=str, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            payload = str(payload)
    return ToolResult(tool_name=name, content=payload, success=True)


def _err(name: str, exc: Exception) -> ToolResult:
    return ToolResult(tool_name=name, content=f"GitHub error: {exc}", success=False)


class _GHToolBase(BaseTool):
    is_local = False

    def __init__(self, client: Optional[GitHubClient] = None) -> None:
        self._client = client or get_default_client()


@ToolRegistry.register("gh_list_repos")
class GHListReposTool(_GHToolBase):
    tool_id = "gh_list_repos"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gh_list_repos",
            description="List repos accessible to the authenticated user.",
            parameters={
                "type": "object",
                "properties": {"per_page": {"type": "integer", "default": 30}},
            },
            category="dev",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.list_repos(per_page=int(params.get("per_page", 30))),
            )
        except GitHubUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("gh_get_repo")
class GHGetRepoTool(_GHToolBase):
    tool_id = "gh_get_repo"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gh_get_repo",
            description="Fetch repo metadata (description, default branch, languages).",
            parameters={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                },
                "required": ["owner", "repo"],
            },
            category="dev",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.get_repo(params["owner"], params["repo"]),
            )
        except GitHubUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("gh_list_issues")
class GHListIssuesTool(_GHToolBase):
    tool_id = "gh_list_issues"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gh_list_issues",
            description="List issues in a repo. Default state=open.",
            parameters={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": ["open", "closed", "all"],
                        "default": "open",
                    },
                    "per_page": {"type": "integer", "default": 30},
                },
                "required": ["owner", "repo"],
            },
            category="dev",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.list_issues(
                    params["owner"],
                    params["repo"],
                    state=params.get("state", "open"),
                    per_page=int(params.get("per_page", 30)),
                ),
            )
        except GitHubUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("gh_create_issue")
class GHCreateIssueTool(_GHToolBase):
    tool_id = "gh_create_issue"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gh_create_issue",
            description="Open a new issue in a repo.",
            parameters={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string", "default": ""},
                    "labels": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["owner", "repo", "title"],
            },
            category="dev",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.create_issue(
                    params["owner"],
                    params["repo"],
                    title=params["title"],
                    body=params.get("body", ""),
                    labels=params.get("labels"),
                ),
            )
        except GitHubUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("gh_list_prs")
class GHListPRsTool(_GHToolBase):
    tool_id = "gh_list_prs"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gh_list_prs",
            description="List pull requests in a repo.",
            parameters={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "state": {
                        "type": "string",
                        "enum": ["open", "closed", "all"],
                        "default": "open",
                    },
                    "per_page": {"type": "integer", "default": 30},
                },
                "required": ["owner", "repo"],
            },
            category="dev",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.list_pulls(
                    params["owner"],
                    params["repo"],
                    state=params.get("state", "open"),
                    per_page=int(params.get("per_page", 30)),
                ),
            )
        except GitHubUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("gh_get_pr")
class GHGetPRTool(_GHToolBase):
    tool_id = "gh_get_pr"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gh_get_pr",
            description="Fetch full PR metadata by number.",
            parameters={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "number": {"type": "integer"},
                },
                "required": ["owner", "repo", "number"],
            },
            category="dev",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.get_pull(
                    params["owner"], params["repo"], int(params["number"])
                ),
            )
        except GitHubUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("gh_comment_pr")
class GHCommentPRTool(_GHToolBase):
    tool_id = "gh_comment_pr"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gh_comment_pr",
            description="Post a comment on a pull request.",
            parameters={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "number": {"type": "integer"},
                    "body": {"type": "string"},
                },
                "required": ["owner", "repo", "number", "body"],
            },
            category="dev",
            requires_confirmation=True,
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.comment_pull(
                    params["owner"],
                    params["repo"],
                    int(params["number"]),
                    params["body"],
                ),
            )
        except GitHubUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("gh_get_file")
class GHGetFileTool(_GHToolBase):
    tool_id = "gh_get_file"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gh_get_file",
            description="Read a file from a repo at a given ref (branch/tag/sha).",
            parameters={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "path": {"type": "string"},
                    "ref": {
                        "type": "string",
                        "description": "Branch / tag / commit sha (default: default branch).",
                    },
                },
                "required": ["owner", "repo", "path"],
            },
            category="dev",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.get_file(
                    params["owner"],
                    params["repo"],
                    params["path"],
                    ref=params.get("ref"),
                ),
            )
        except GitHubUnavailableError as exc:
            return _err(self.spec.name, exc)


@ToolRegistry.register("gh_list_actions_runs")
class GHListActionsRunsTool(_GHToolBase):
    tool_id = "gh_list_actions_runs"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="gh_list_actions_runs",
            description="List recent GitHub Actions workflow runs in a repo.",
            parameters={
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                    "per_page": {"type": "integer", "default": 20},
                },
                "required": ["owner", "repo"],
            },
            category="dev",
        )

    def execute(self, **params: Any) -> ToolResult:
        try:
            return _ok(
                self.spec.name,
                self._client.list_actions_runs(
                    params["owner"],
                    params["repo"],
                    per_page=int(params.get("per_page", 20)),
                ),
            )
        except GitHubUnavailableError as exc:
            return _err(self.spec.name, exc)


__all__ = [
    "GHCommentPRTool",
    "GHCreateIssueTool",
    "GHGetFileTool",
    "GHGetPRTool",
    "GHGetRepoTool",
    "GHListActionsRunsTool",
    "GHListIssuesTool",
    "GHListPRsTool",
    "GHListReposTool",
]
