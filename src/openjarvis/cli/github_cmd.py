
"""Serena GitHub/Git operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_github import (
    SerenaGitHubBranchesTool,
    SerenaGitHubChangesTool,
    SerenaGitHubRecentCommitsTool,
    SerenaGitHubRemotesTool,
    SerenaGitHubRepoInfoTool,
    SerenaGitHubSafetyCheckTool,
    SerenaGitHubStatusTool,
    SerenaGitHubFinalCheckTool,
    SerenaGitHubReleaseNotesTool,
    SerenaGitHubFeatureRequestTool,
    SerenaGitHubBugReportTool,
    SerenaGitHubIssueDraftTool,
    SerenaGitHubPRSummaryTool,
    SerenaGitHubCommitMessageTool,
    SerenaGitHubCommitPlanTool,
)


@click.group()
def github() -> None:
    """Native Serena GitHub/Git operator tools."""


@github.command("status")
def status() -> None:
    """Show Serena GitHub operator status."""
    console = Console()
    result = SerenaGitHubStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("repo-info")
@click.option("--root", required=True, help="Approved root alias.")
def repo_info(root: str) -> None:
    """Inspect repository information."""
    console = Console()
    result = SerenaGitHubRepoInfoTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("branches")
@click.option("--root", required=True, help="Approved root alias.")
def branches(root: str) -> None:
    """List local and remote branches."""
    console = Console()
    result = SerenaGitHubBranchesTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("remotes")
@click.option("--root", required=True, help="Approved root alias.")
def remotes(root: str) -> None:
    """List Git remotes."""
    console = Console()
    result = SerenaGitHubRemotesTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("recent-commits")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--limit", default=10, type=int, help="Maximum commits to show.")
def recent_commits(root: str, limit: int) -> None:
    """Show recent commits."""
    console = Console()
    result = SerenaGitHubRecentCommitsTool().execute(root=root, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("changes")
@click.option("--root", required=True, help="Approved root alias.")
def changes(root: str) -> None:
    """Inspect local Git changes."""
    console = Console()
    result = SerenaGitHubChangesTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("safety-check")
@click.option("--root", required=True, help="Approved root alias.")
def safety_check(root: str) -> None:
    """Run Serena GitHub safety check."""
    console = Console()
    result = SerenaGitHubSafetyCheckTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("commit-plan")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--goal", default="Prepare local changes for review.", help="Commit goal.")
def commit_plan(root: str, goal: str) -> None:
    """Create a local commit plan without committing or pushing."""
    console = Console()
    result = SerenaGitHubCommitPlanTool().execute(root=root, goal=goal)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("commit-message")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--style", default="standard", help="Commit message style.")
def commit_message(root: str, style: str) -> None:
    """Draft a commit message without committing."""
    console = Console()
    result = SerenaGitHubCommitMessageTool().execute(root=root, style=style)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("pr-summary")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--title", default="", help="Optional PR title.")
def pr_summary(root: str, title: str) -> None:
    """Draft a PR summary without creating a PR."""
    console = Console()
    result = SerenaGitHubPRSummaryTool().execute(root=root, title=title)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("issue-draft")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--title", required=True, help="Issue title.")
@click.option("--body", required=True, help="Issue body.")
@click.option("--kind", default="issue", help="Issue kind.")
def issue_draft(root: str, title: str, body: str, kind: str) -> None:
    """Draft a GitHub issue without creating it remotely."""
    console = Console()
    result = SerenaGitHubIssueDraftTool().execute(root=root, title=title, body=body, kind=kind)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("bug-report")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--title", required=True, help="Bug report title.")
@click.option("--problem", required=True, help="Problem description.")
@click.option("--steps", default="Not provided.", help="Steps to reproduce.")
@click.option("--expected", default="Not provided.", help="Expected behavior.")
@click.option("--actual", default="Not provided.", help="Actual behavior.")
def bug_report(root: str, title: str, problem: str, steps: str, expected: str, actual: str) -> None:
    """Draft a GitHub bug report without creating it remotely."""
    console = Console()
    result = SerenaGitHubBugReportTool().execute(
        root=root,
        title=title,
        problem=problem,
        steps=steps,
        expected=expected,
        actual=actual,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("feature-request")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--title", required=True, help="Feature request title.")
@click.option("--summary", required=True, help="Feature summary.")
@click.option("--value", default="Not provided.", help="Feature value.")
@click.option("--acceptance", default="Not provided.", help="Acceptance criteria.")
def feature_request(root: str, title: str, summary: str, value: str, acceptance: str) -> None:
    """Draft a GitHub feature request without creating it remotely."""
    console = Console()
    result = SerenaGitHubFeatureRequestTool().execute(
        root=root,
        title=title,
        summary=summary,
        value=value,
        acceptance=acceptance,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("release-notes")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--title", default="Serena local release notes draft", help="Release notes title.")
@click.option("--limit", default=20, type=int, help="Commit limit.")
def release_notes(root: str, title: str, limit: int) -> None:
    """Draft release notes without publishing a release."""
    console = Console()
    result = SerenaGitHubReleaseNotesTool().execute(root=root, title=title, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@github.command("final-check")
@click.option("--root", required=True, help="Approved root alias.")
def final_check(root: str) -> None:
    """Run final Serena GitHub local safety check."""
    console = Console()
    result = SerenaGitHubFinalCheckTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["github"]
