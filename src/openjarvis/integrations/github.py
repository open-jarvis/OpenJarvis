"""GitHub REST API client.

Auth uses ``GITHUB_PAT`` (canonical). The env-alias pass populates it
from ``GITHUB_TOKEN`` if only the latter is set. Bearer-token auth on
``api.github.com`` with ``X-GitHub-Api-Version: 2022-11-28``.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"


class GitHubUnavailableError(RuntimeError):
    """Raised when GITHUB_PAT/GITHUB_TOKEN are missing or a call fails."""


class GitHubClient:
    def __init__(
        self,
        token: Optional[str] = None,
        *,
        timeout: float = 15.0,
    ) -> None:
        self._token = (
            token
            or os.environ.get("GITHUB_PAT")
            or os.environ.get("GITHUB_TOKEN", "")
        )
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        if not self.configured:
            raise GitHubUnavailableError(
                "GitHub not configured — set GITHUB_PAT (or GITHUB_TOKEN)"
            )
        url = f"{API_BASE}{path}"
        try:
            with httpx.Client(timeout=self._timeout) as c:
                resp = c.request(
                    method,
                    url,
                    headers=self._headers(),
                    params=params,
                    json=json_body,
                )
                resp.raise_for_status()
                return resp.json() if resp.content else None
        except httpx.HTTPError as exc:
            raise GitHubUnavailableError(f"GitHub {method} {path} failed: {exc}") from exc

    # -- Read -----------------------------------------------------------

    def me(self) -> Any:
        return self._request("GET", "/user")

    def list_repos(self, *, per_page: int = 30) -> Any:
        return self._request("GET", "/user/repos", params={"per_page": per_page})

    def get_repo(self, owner: str, repo: str) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}")

    def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        per_page: int = 30,
    ) -> Any:
        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params={"state": state, "per_page": per_page},
        )

    def list_pulls(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        per_page: int = 30,
    ) -> Any:
        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={"state": state, "per_page": per_page},
        )

    def get_pull(self, owner: str, repo: str, number: int) -> Any:
        return self._request("GET", f"/repos/{owner}/{repo}/pulls/{number}")

    def get_file(
        self,
        owner: str,
        repo: str,
        path: str,
        *,
        ref: Optional[str] = None,
    ) -> Any:
        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path}",
            params={"ref": ref} if ref else None,
        )

    def list_actions_runs(
        self,
        owner: str,
        repo: str,
        *,
        per_page: int = 20,
    ) -> Any:
        return self._request(
            "GET",
            f"/repos/{owner}/{repo}/actions/runs",
            params={"per_page": per_page},
        )

    # -- Write ----------------------------------------------------------

    def create_issue(
        self,
        owner: str,
        repo: str,
        *,
        title: str,
        body: str = "",
        labels: Optional[list[str]] = None,
    ) -> Any:
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return self._request(
            "POST", f"/repos/{owner}/{repo}/issues", json_body=payload
        )

    def comment_pull(
        self,
        owner: str,
        repo: str,
        number: int,
        body: str,
    ) -> Any:
        return self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            json_body={"body": body},
        )


_default: Optional[GitHubClient] = None


def get_default_client() -> GitHubClient:
    global _default
    if _default is None:
        _default = GitHubClient()
    return _default


__all__ = ["GitHubClient", "GitHubUnavailableError", "get_default_client"]
