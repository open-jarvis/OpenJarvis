"""Release archives must fit the upload budget before publication."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024


def workflow_steps():
    workflow = yaml.safe_load((ROOT / ".github/workflows/pypi-publish.yml").read_text())
    return workflow["jobs"]["publish"]["steps"]


def validation_command():
    return next(
        step["run"]
        for step in workflow_steps()
        if step.get("name") == "Validate release artifacts"
    )


def run_validation(tmp_path):
    # A tag checkout may have no validation helper; only dist exists here.
    source = validation_command().split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    return subprocess.run(
        [sys.executable, "-"],
        input=source,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def distributions(tmp_path: Path) -> tuple[Path, Path]:
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "openjarvis-1.0.4-py3-none-any.whl"
    sdist = dist / "openjarvis-1.0.4.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    return wheel, sdist


def test_reports_both_artifacts_without_checkout_helpers(tmp_path):
    wheel, sdist = distributions(tmp_path)
    result = run_validation(tmp_path)
    assert result.returncode == 0, result.stderr
    output = result.stdout
    assert wheel.name in output and sdist.name in output
    assert "5 bytes" in output
    assert "MiB" in output


@pytest.mark.parametrize("artifact_index", [0, 1])
def test_rejects_oversized_wheel_or_sdist(tmp_path, artifact_index):
    archives = distributions(tmp_path)
    oversized = archives[artifact_index]
    with oversized.open("wb") as archive:
        archive.truncate(MAX_ARTIFACT_BYTES + 1)
    result = run_validation(tmp_path)
    assert result.returncode != 0
    assert oversized.name in result.stderr
    assert "exceeds the 20 MiB upload budget" in result.stderr
    assert all(artifact.name in result.stdout for artifact in archives)


def test_exact_budget_is_allowed(tmp_path):
    wheel, _ = distributions(tmp_path)
    with wheel.open("wb") as archive:
        archive.truncate(MAX_ARTIFACT_BYTES)
    result = run_validation(tmp_path)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("missing", ["wheel", "sdist", "both"])
def test_missing_distribution_is_an_error(tmp_path, missing):
    wheel, sdist = distributions(tmp_path)
    if missing in {"wheel", "both"}:
        wheel.unlink()
    if missing in {"sdist", "both"}:
        sdist.unlink()
    result = run_validation(tmp_path)
    assert result.returncode != 0
    assert "Expected at least one wheel and one" in result.stderr


def test_metadata_and_size_validation_precede_both_upload_paths():
    steps = workflow_steps()
    validation = next(
        index
        for index, step in enumerate(steps)
        if "uvx twine check --strict" in step.get("run", "")
    )
    command = steps[validation]["run"]
    assert "set -euo pipefail" in command
    assert command.index("<<'PY'") < command.index("uvx twine check --strict")
    assert "if" not in steps[validation]
    uploads = [
        index for index, step in enumerate(steps) if "uv publish" in step.get("run", "")
    ]
    assert len(uploads) == 2
    assert all(validation < index for index in uploads)
