"""Regression tests for the session-wide test-home lifecycle."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode", ["collect-only", "collection-error"])
def test_non_running_sessions_restore_environment_and_remove_test_home(
    mode: str,
) -> None:
    """Cleanup must run when fixtures never start or collection aborts."""
    repo_root = Path(__file__).resolve().parents[1]
    script = r"""
import os
import pathlib
import sys
import tempfile

import pytest

created = []
real_mkdtemp = tempfile.mkdtemp

def recording_mkdtemp(*args, **kwargs):
    path = real_mkdtemp(*args, **kwargs)
    if kwargs.get("prefix") == "openjarvis-test-home-":
        created.append(path)
    return path

tempfile.mkdtemp = recording_mkdtemp
os.environ["OPENJARVIS_HOME"] = "/tmp/openjarvis-original-home-sentinel"
os.environ["OPENJARVIS_CONFIG"] = "/tmp/openjarvis-original-config-sentinel"

bad_test = pathlib.Path("tests") / f"test_bad_collection_{os.getpid()}.py"
try:
    if sys.argv[1] == "collect-only":
        result = pytest.main(
            ["--collect-only", "-q", "tests/core/test_config_paths.py"]
        )
        assert result == pytest.ExitCode.OK, result
    else:
        bad_test.write_text("def broken(:\n", encoding="utf-8")
        result = pytest.main(["--collect-only", "-q", str(bad_test)])
        assert result != pytest.ExitCode.OK, result
finally:
    bad_test.unlink(missing_ok=True)

assert os.environ["OPENJARVIS_HOME"] == "/tmp/openjarvis-original-home-sentinel"
assert os.environ["OPENJARVIS_CONFIG"] == "/tmp/openjarvis-original-config-sentinel"
assert len(created) == 1, created
assert not pathlib.Path(created[0]).exists(), created[0]
"""
    result = subprocess.run(
        [sys.executable, "-c", script, mode],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
