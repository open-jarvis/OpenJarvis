from __future__ import annotations

from pathlib import Path

import pytest

from openjarvis.codex import (
    ApprovalMode,
    CodexModelConfig,
    CodexPolicyError,
    CodexRunContext,
    SandboxMode,
)


def _context(
    cwd: Path,
    *,
    approval_mode: ApprovalMode = ApprovalMode.DENY_ALL,
    sandbox: SandboxMode = SandboxMode.READ_ONLY,
    isolated_workspace: Path | None = None,
) -> CodexRunContext:
    return CodexRunContext(
        task_id="task-1",
        session_id="session-1",
        correlation_id="correlation-1",
        cwd=cwd,
        sandbox=sandbox,
        approval_mode=approval_mode,
        model=CodexModelConfig(model=None, effort=None, service_tier=None),
        timeout_seconds=30,
        step_limit=10,
        token_limit=None,
        developer_instructions=None,
        isolated_workspace=isolated_workspace,
    )


def test_read_only_is_safe_analysis_policy(tmp_path: Path) -> None:
    context = _context(tmp_path)

    assert context.validated() is context
    assert context.approval_mode is ApprovalMode.DENY_ALL
    assert context.sandbox is SandboxMode.READ_ONLY


def test_non_deny_all_approval_mode_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CodexPolicyError, match="deny_all"):
        _context(
            tmp_path,
            approval_mode=ApprovalMode.AUTO_REVIEW,
        ).validated()


def test_full_access_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(CodexPolicyError, match="full_access"):
        _context(tmp_path, sandbox=SandboxMode.FULL_ACCESS).validated()


def test_workspace_write_requires_isolated_workspace(tmp_path: Path) -> None:
    with pytest.raises(CodexPolicyError, match="isolated workspace"):
        _context(tmp_path, sandbox=SandboxMode.WORKSPACE_WRITE).validated()


def test_workspace_write_must_remain_under_isolated_root(tmp_path: Path) -> None:
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(CodexPolicyError, match="inside"):
        _context(
            outside,
            sandbox=SandboxMode.WORKSPACE_WRITE,
            isolated_workspace=isolated,
        ).validated()


def test_workspace_write_accepts_verified_task_workspace(tmp_path: Path) -> None:
    isolated = tmp_path / "isolated"
    workspace = isolated / "task"
    workspace.mkdir(parents=True)

    context = _context(
        workspace,
        sandbox=SandboxMode.WORKSPACE_WRITE,
        isolated_workspace=isolated,
    )

    assert context.validated() is context


def test_security_sensitive_context_fields_have_no_constructor_defaults() -> None:
    with pytest.raises(TypeError):
        CodexRunContext()  # type: ignore[call-arg]
