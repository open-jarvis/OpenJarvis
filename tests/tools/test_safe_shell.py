"""Structured Windows-compatible shell security tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from openjarvis.tools.safe_filesystem import SecurePathPolicy
from openjarvis.tools.safe_shell import SafeShellTool, StructuredCommandPolicy


@pytest.fixture
def shell(tmp_path: Path) -> tuple[SafeShellTool, Path]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path_policy = SecurePathPolicy((workspace,), tmp_path / "restore")
    policy = StructuredCommandPolicy(
        allowed_executables=(sys.executable,),
        path_policy=path_policy,
        allowed_environment=frozenset({"PHASE5_VALUE"}),
    )
    return SafeShellTool(policy), workspace


def test_structured_arguments_do_not_invoke_a_shell(shell) -> None:
    tool, workspace = shell
    argument = "hello; echo INJECTED"
    original = subprocess.Popen

    def guarded(*args, **kwargs):
        assert kwargs["shell"] is False
        return original(*args, **kwargs)

    with patch("openjarvis.tools.safe_shell.subprocess.Popen", side_effect=guarded):
        result = tool.execute(
            executable=sys.executable,
            arguments=["-c", "import sys; print(sys.argv[1])", argument],
            working_dir=str(workspace),
        )
    assert result.success
    assert result.content.strip() == argument
    assert result.metadata["shell"] is False


def test_environment_allowlist_and_value_redaction(shell) -> None:
    tool, workspace = shell
    result = tool.execute(
        executable=sys.executable,
        arguments=["-c", "import os; print(os.environ['PHASE5_VALUE'])"],
        working_dir=str(workspace),
        environment=[{"name": "PHASE5_VALUE", "value": "sensitive-test-value"}],
    )
    assert result.success
    assert "sensitive-test-value" not in result.content
    assert "[REDACTED]" in result.content


def test_secret_environment_name_is_blocked(shell) -> None:
    tool, workspace = shell
    result = tool.execute(
        executable=sys.executable,
        arguments=["-c", "print('never')"],
        working_dir=str(workspace),
        environment=[{"name": "API_TOKEN", "value": "abc"}],
    )
    assert result.success is False
    assert "not allowed" in result.content or "secret-bearing" in result.content


def test_timeout_terminates_owned_process(shell) -> None:
    tool, workspace = shell
    result = tool.execute(
        executable=sys.executable,
        arguments=["-c", "import time; time.sleep(30)"],
        working_dir=str(workspace),
        timeout=1,
    )
    assert result.success is False
    assert result.metadata["timed_out"] is True
    assert result.metadata["process_tree_terminated"] is True


def test_owner_stop_terminates_active_shell_process(shell) -> None:
    tool, workspace = shell
    holder = []
    worker = threading.Thread(
        target=lambda: holder.append(
            tool.execute(
                executable=sys.executable,
                arguments=["-c", "import time; time.sleep(30)"],
                working_dir=str(workspace),
                timeout=30,
            )
        )
    )
    worker.start()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        with tool._process_lock:
            if tool._active_processes:
                break
        time.sleep(0.01)

    assert tool.interrupt() == 1
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert holder[0].success is False
    assert holder[0].metadata["interrupted"] is True


def _process_is_running(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def test_timeout_terminates_child_process_tree(shell) -> None:
    tool, workspace = shell
    code = (
        "import subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
        "print(p.pid, flush=True); time.sleep(30)"
    )
    result = tool.execute(
        executable=sys.executable,
        arguments=["-c", code],
        working_dir=str(workspace),
        timeout=1,
    )
    child_pid = int(result.content.splitlines()[-1])
    assert result.metadata["process_tree_terminated"] is True
    assert _process_is_running(child_pid) is False


def test_unapproved_executable_and_cwd_are_blocked(shell, tmp_path: Path) -> None:
    tool, workspace = shell
    foreign = shutil.which("git")
    if foreign:
        result = tool.execute(
            executable=foreign,
            arguments=["status"],
            working_dir=str(workspace),
        )
        assert result.success is False
        assert "not allowlisted" in result.content
    result = tool.execute(
        executable=sys.executable,
        arguments=["-c", "print('never')"],
        working_dir=str(tmp_path / "outside"),
    )
    assert result.success is False


def test_git_push_force_reset_and_clean_are_blocked(tmp_path: Path) -> None:
    git = shutil.which("git")
    if not git:
        pytest.skip("git unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path_policy = SecurePathPolicy((workspace,), tmp_path / "restore")
    tool = SafeShellTool(
        StructuredCommandPolicy(
            allowed_executables=(git,),
            path_policy=path_policy,
        )
    )
    for arguments in (["push", "upstream"], ["reset", "--hard"], ["clean", "-fdx"]):
        result = tool.execute(
            executable=git,
            arguments=arguments,
            working_dir=str(workspace),
        )
        assert result.success is False
        assert "blocked" in result.content


def test_flow_full_machine_policy_allows_executable_and_foreign_cwd(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    if not git:
        pytest.skip("git unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "owner-selected"
    outside.mkdir()
    path_policy = SecurePathPolicy(
        (workspace,),
        tmp_path / "restore",
        full_machine=True,
    )
    tool = SafeShellTool(
        StructuredCommandPolicy(
            allowed_executables=(),
            path_policy=path_policy,
            full_machine=True,
        )
    )

    result = tool.execute(
        executable=git,
        arguments=["--version"],
        working_dir=str(outside),
    )

    assert result.success is True
    assert "git version" in result.content.lower()


def test_flow_full_machine_policy_allows_local_git_commit_and_push(
    tmp_path: Path,
) -> None:
    git = shutil.which("git")
    if not git:
        pytest.skip("git unavailable")
    remote = tmp_path / "owner-remote.git"
    checkout = tmp_path / "owner-checkout"
    checkout.mkdir()
    tool = SafeShellTool(
        StructuredCommandPolicy(
            allowed_executables=(),
            path_policy=SecurePathPolicy(
                (tmp_path,),
                tmp_path / "restore",
                full_machine=True,
            ),
            full_machine=True,
        )
    )

    commands = (
        (["init", "--bare", str(remote)], tmp_path),
        (["init"], checkout),
        (["config", "user.name", "OpenJarvis Flow Test"], checkout),
        (["config", "user.email", "flow-test@localhost"], checkout),
    )
    for arguments, cwd in commands:
        result = tool.execute(
            executable=git,
            arguments=arguments,
            working_dir=str(cwd),
        )
        assert result.success, result.content

    (checkout / "flow-proof.txt").write_text(
        "owner-authorized Flow commit\n",
        encoding="utf-8",
    )
    for arguments in (
        ["add", "flow-proof.txt"],
        ["commit", "-m", "test: prove Flow git write"],
        ["remote", "add", "origin", str(remote)],
        ["push", "-u", "origin", "HEAD:main"],
    ):
        result = tool.execute(
            executable=git,
            arguments=arguments,
            working_dir=str(checkout),
        )
        assert result.success, result.content

    verified = tool.execute(
        executable=git,
        arguments=["--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        working_dir=str(tmp_path),
    )
    assert verified.success
    assert len(verified.content.strip()) == 40


def test_output_is_bounded(shell) -> None:
    tool, workspace = shell
    result = tool.execute(
        executable=sys.executable,
        arguments=["-c", "print('x' * 120000)"],
        working_dir=str(workspace),
    )
    assert result.success
    assert result.metadata["stdout_truncated"] is True
    assert len(result.content) <= 102_400


def test_foreign_process_is_not_terminated(shell) -> None:
    tool, workspace = shell
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    foreign = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        creationflags=flags,
    )
    try:
        result = tool.execute(
            executable=sys.executable,
            arguments=["-c", "import time; time.sleep(10)"],
            working_dir=str(workspace),
            timeout=1,
        )
        assert result.metadata["process_tree_terminated"] is True
        assert foreign.poll() is None
    finally:
        foreign.terminate()
        foreign.wait(timeout=5)
