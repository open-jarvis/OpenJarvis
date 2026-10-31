"""Apple failures must reach the release workflow's actionable diagnostics."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("response", "exit_code", "diagnostic"),
    [
        ("OK", 0, "Apple notarization preflight OK"),
        ("Invalid credentials (401)", 1, "invalid credentials (HTTP 401)"),
        (
            "Invalid or inaccessible developer team ID",
            1,
            "APPLE_ID is not a member of team APPLE_TEAM_ID",
        ),
        ("required agreement", 1, "the team has no in-effect agreement"),
        ("temporary network failure", 1, "failed after 3 attempts"),
    ],
)
def test_preflight_handles_notarytool_exit_status(
    tmp_path: Path, response: str, exit_code: int, diagnostic: str
) -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/desktop.yml").read_text())
    script = next(
        step["run"]
        for step in workflow["jobs"]["build-and-release"]["steps"]
        if step.get("name") == "Preflight Apple notarization credentials"
    )
    xcrun = tmp_path / "xcrun"
    xcrun.write_text('#!/bin/bash\nprintf "%s\\n" "$RESPONSE"\nexit "$EXIT_CODE"\n')
    xcrun.chmod(0o755)
    sleep = tmp_path / "sleep"
    sleep.write_text("#!/bin/bash\nexit 0\n")
    sleep.chmod(0o755)

    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "CERT": "test-certificate",
            "A_ID": "test-id",
            "A_PASS": "test-password",
            "A_TEAM": "test-team",
            "RESPONSE": response,
            "EXIT_CODE": str(exit_code),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == exit_code, result.stderr
    assert diagnostic in result.stdout
    if response == "temporary network failure":
        assert result.stdout.count("failed with a non-credential error") == 3
