
"""Serena VS Code developer/operator CLI."""

from __future__ import annotations

import click
from rich.console import Console

from openjarvis.tools.serena_vscode import (
    SerenaVSCodeEditFileTool,
    SerenaVSCodeInspectRootTool,
    SerenaVSCodeMkdirTool,
    SerenaVSCodeOpenRootTool,
    SerenaVSCodeProjectReportTool,
    SerenaVSCodeReadTool,
    SerenaVSCodeRootInfoTool,
    SerenaVSCodeRootsTool,
    SerenaVSCodeRunCheckTool,
    SerenaVSCodeSearchTool,
    SerenaVSCodeSnapshotTool,
    SerenaVSCodeStatusTool,
    SerenaVSCodeWriteFileTool,
    SerenaVSCodeTestReportTool,
    SerenaVSCodeSafeCommandTool,
    SerenaVSCodeFinalCheckTool,
    SerenaVSCodeFixSmallTool,
    SerenaVSCodeBugfixPlanTool,
    SerenaVSCodeRefactorPlanTool,
    SerenaVSCodeInspectFileTool,
    SerenaVSCodeFindErrorsTool,
    SerenaVSCodeFindTodosTool,
    SerenaVSCodeChangeSummaryTool,
    SerenaVSCodeUpdateDocTool,
    SerenaVSCodeCreateTestTool,
    SerenaVSCodeCreateComponentTool,
    SerenaVSCodeScriptsTool,
    SerenaVSCodeCommandPolicyTool,
    SerenaVSCodeImplementPlanTool,
    SerenaVSCodeTaskPlanTool,
    SerenaVSCodeRestoreSnapshotTool,
    SerenaVSCodeListSnapshotsTool,
    SerenaVSCodeDiffFileTool,
)


@click.group()
def vscode() -> None:
    """Native Serena VS Code developer/operator tools."""


@vscode.command("status")
def status() -> None:
    """Show Serena VS Code operator status."""
    console = Console()
    result = SerenaVSCodeStatusTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("roots")
def roots() -> None:
    """List approved VS Code roots."""
    console = Console()
    result = SerenaVSCodeRootsTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("root-info")
@click.option("--root", required=True, help="Approved root alias.")
def root_info(root: str) -> None:
    """Show VS Code/project info for one approved root."""
    console = Console()
    result = SerenaVSCodeRootInfoTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("open-root")
@click.option("--root", required=True, help="Approved root alias.")
def open_root(root: str) -> None:
    """Open VS Code on an approved root."""
    console = Console()
    result = SerenaVSCodeOpenRootTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("inspect-root")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--limit", default=300, type=int, help="Maximum files to inspect.")
def inspect_root(root: str, limit: int) -> None:
    """Inspect an approved root like a developer."""
    console = Console()
    result = SerenaVSCodeInspectRootTool().execute(root=root, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("project-report")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--limit", default=300, type=int, help="Maximum files to inspect.")
def project_report(root: str, limit: int) -> None:
    """Create a project developer report."""
    console = Console()
    result = SerenaVSCodeProjectReportTool().execute(root=root, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("search")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--query", required=True, help="Search query.")
@click.option("--content/--name-only", default=False, help="Search safe file contents too.")
@click.option("--limit", default=100, type=int, help="Maximum matches.")
def search(root: str, query: str, content: bool, limit: int) -> None:
    """Search an approved project root."""
    console = Console()
    result = SerenaVSCodeSearchTool().execute(root=root, query=query, content=content, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("read")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--preview-chars", default=6000, type=int, help="Preview character count.")
def read(root: str, file_path: str, preview_chars: int) -> None:
    """Read a safe text file from an approved root."""
    console = Console()
    result = SerenaVSCodeReadTool().execute(root=root, path=file_path, preview_chars=preview_chars)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("snapshot")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--reason", default="manual-snapshot", help="Snapshot reason.")
def snapshot(root: str, file_path: str, reason: str) -> None:
    """Snapshot a file from an approved root."""
    console = Console()
    result = SerenaVSCodeSnapshotTool().execute(root=root, path=file_path, reason=reason)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("mkdir")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "folder_path", required=True, help="Relative folder path inside root.")
def mkdir(root: str, folder_path: str) -> None:
    """Create a folder inside an approved root."""
    console = Console()
    result = SerenaVSCodeMkdirTool().execute(root=root, path=folder_path)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("write-file")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--content", required=True, help="File content.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing file after snapshot.")
def write_file(root: str, file_path: str, content: str, overwrite: bool) -> None:
    """Create or overwrite a file inside an approved root."""
    console = Console()
    result = SerenaVSCodeWriteFileTool().execute(root=root, path=file_path, content=content, overwrite=overwrite)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("edit-file")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--old", required=True, help="Old text to replace.")
@click.option("--new", required=True, help="New text.")
@click.option("--replace-all", is_flag=True, help="Replace all matches.")
def edit_file(root: str, file_path: str, old: str, new: str, replace_all: bool) -> None:
    """Edit a safe text file by replacing text with snapshot first."""
    console = Console()
    result = SerenaVSCodeEditFileTool().execute(
        root=root,
        path=file_path,
        old=old,
        new=new,
        replace_all=replace_all,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("run-check")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--check", required=True, help="Safe check name.")
@click.option("--module", default="", help="Module for python-import check.")
def run_check(root: str, check: str, module: str) -> None:
    """Run an approved safe local project check."""
    console = Console()
    result = SerenaVSCodeRunCheckTool().execute(root=root, check=check, module=module)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("diff-file")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--max-lines", default=200, type=int, help="Maximum diff lines.")
def diff_file(root: str, file_path: str, max_lines: int) -> None:
    """Diff current file against latest Serena VS Code snapshot."""
    console = Console()
    result = SerenaVSCodeDiffFileTool().execute(root=root, path=file_path, max_lines=max_lines)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("list-snapshots")
@click.option("--limit", default=50, type=int, help="Maximum snapshots to show.")
@click.option("--path", "path_filter", default="", help="Optional path filter.")
def list_snapshots(limit: int, path_filter: str) -> None:
    """List Serena VS Code snapshots."""
    console = Console()
    result = SerenaVSCodeListSnapshotsTool().execute(limit=limit, path=path_filter)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("restore-snapshot")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--snapshot", default="", help="Optional snapshot file path. Defaults to latest for file.")
@click.option("--approved", is_flag=True, help="Required to restore snapshot.")
def restore_snapshot(root: str, file_path: str, snapshot: str, approved: bool) -> None:
    """Restore a file from a Serena VS Code snapshot with approval."""
    console = Console()
    result = SerenaVSCodeRestoreSnapshotTool().execute(
        root=root,
        path=file_path,
        snapshot=snapshot,
        approved=approved,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("task-plan")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--task", required=True, help="Developer task description.")
@click.option("--limit", default=300, type=int, help="Maximum files to scan.")
def task_plan(root: str, task: str, limit: int) -> None:
    """Create a developer task plan without changing files."""
    console = Console()
    result = SerenaVSCodeTaskPlanTool().execute(root=root, task=task, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("implement-plan")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--operations-json", default="", help="JSON list of write/replace/mkdir operations.")
@click.option("--operations-file", default="", help="Path to a JSON file containing write/replace/mkdir operations.")
def implement_plan(root: str, operations_json: str, operations_file: str) -> None:
    """Apply a small explicit implementation plan."""
    console = Console()
    result = SerenaVSCodeImplementPlanTool().execute(
        root=root,
        operations_json=operations_json,
        operations_file=operations_file,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("test-report")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--checks", default="git-status", help="Comma-separated safe checks.")
@click.option("--module", default="", help="Module for python-import check.")
def test_report(root: str, checks: str, module: str) -> None:
    """Run safe checks and create a developer test report."""
    console = Console()
    result = SerenaVSCodeTestReportTool().execute(root=root, checks=checks, module=module)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("command-policy")
def command_policy() -> None:
    """Show Serena VS Code safe command policy."""
    console = Console()
    result = SerenaVSCodeCommandPolicyTool().execute()
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("scripts")
@click.option("--root", required=True, help="Approved root alias.")
def scripts(root: str) -> None:
    """Detect available project scripts/checks."""
    console = Console()
    result = SerenaVSCodeScriptsTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("safe-command")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--command", required=True, help="Safe allowlisted command to run.")
@click.option("--timeout", default=180, type=int, help="Timeout in seconds.")
def safe_command(root: str, command: str, timeout: int) -> None:
    """Run a safe allowlisted developer command."""
    console = Console()
    result = SerenaVSCodeSafeCommandTool().execute(root=root, command=command, timeout=timeout)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("create-component")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--name", required=True, help="Component/function name.")
@click.option("--kind", default="python", help="Component kind: python, typescript, react, markdown.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing file after snapshot.")
def create_component(root: str, file_path: str, name: str, kind: str, overwrite: bool) -> None:
    """Create a developer component/source file."""
    console = Console()
    result = SerenaVSCodeCreateComponentTool().execute(
        root=root,
        path=file_path,
        name=name,
        kind=kind,
        overwrite=overwrite,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("create-test")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--name", required=True, help="Test name.")
@click.option("--kind", default="python", help="Test kind: python, typescript, markdown.")
@click.option("--overwrite", is_flag=True, help="Overwrite existing file after snapshot.")
def create_test(root: str, file_path: str, name: str, kind: str, overwrite: bool) -> None:
    """Create a developer test file."""
    console = Console()
    result = SerenaVSCodeCreateTestTool().execute(
        root=root,
        path=file_path,
        name=name,
        kind=kind,
        overwrite=overwrite,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("update-doc")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative doc path inside root.")
@click.option("--heading", required=True, help="Markdown heading.")
@click.option("--content", required=True, help="Markdown content.")
@click.option("--mode", default="append", help="append or replace-section.")
def update_doc(root: str, file_path: str, heading: str, content: str, mode: str) -> None:
    """Append or replace a documentation section."""
    console = Console()
    result = SerenaVSCodeUpdateDocTool().execute(
        root=root,
        path=file_path,
        heading=heading,
        content=content,
        mode=mode,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("change-summary")
@click.option("--root", required=True, help="Approved root alias.")
def change_summary(root: str) -> None:
    """Create a local developer change summary."""
    console = Console()
    result = SerenaVSCodeChangeSummaryTool().execute(root=root)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("final-check")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--module", default="openjarvis.tools.serena_vscode", help="Module import to check.")
def final_check(root: str, module: str) -> None:
    """Run Serena's final local developer check."""
    console = Console()
    result = SerenaVSCodeFinalCheckTool().execute(root=root, module=module)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("find-todos")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--limit", default=500, type=int, help="Maximum files to scan.")
def find_todos(root: str, limit: int) -> None:
    """Find TODO/FIXME/HACK/BUG markers."""
    console = Console()
    result = SerenaVSCodeFindTodosTool().execute(root=root, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("find-errors")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--limit", default=500, type=int, help="Maximum files to scan.")
def find_errors(root: str, limit: int) -> None:
    """Find common error/exception patterns."""
    console = Console()
    result = SerenaVSCodeFindErrorsTool().execute(root=root, limit=limit)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("inspect-file")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--preview-chars", default=2000, type=int, help="Preview character count.")
def inspect_file(root: str, file_path: str, preview_chars: int) -> None:
    """Inspect one project file."""
    console = Console()
    result = SerenaVSCodeInspectFileTool().execute(root=root, path=file_path, preview_chars=preview_chars)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("refactor-plan")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--goal", required=True, help="Refactor goal.")
def refactor_plan(root: str, file_path: str, goal: str) -> None:
    """Create a conservative refactor plan."""
    console = Console()
    result = SerenaVSCodeRefactorPlanTool().execute(root=root, path=file_path, goal=goal)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("bugfix-plan")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", default="", help="Optional relative file path inside root.")
@click.option("--issue", required=True, help="Bug/issue description.")
def bugfix_plan(root: str, file_path: str, issue: str) -> None:
    """Create a conservative bugfix plan."""
    console = Console()
    result = SerenaVSCodeBugfixPlanTool().execute(root=root, path=file_path, issue=issue)
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


@vscode.command("fix-small")
@click.option("--root", required=True, help="Approved root alias.")
@click.option("--path", "file_path", required=True, help="Relative file path inside root.")
@click.option("--old", required=True, help="Old text.")
@click.option("--new", required=True, help="New text.")
@click.option("--replace-all", is_flag=True, help="Replace all matches.")
def fix_small(root: str, file_path: str, old: str, new: str, replace_all: bool) -> None:
    """Apply one small explicit text replacement fix."""
    console = Console()
    result = SerenaVSCodeFixSmallTool().execute(
        root=root,
        path=file_path,
        old=old,
        new=new,
        replace_all=replace_all,
    )
    console.print(result.content if result.success else f"[red]{result.content}[/red]")


__all__ = ["vscode"]
