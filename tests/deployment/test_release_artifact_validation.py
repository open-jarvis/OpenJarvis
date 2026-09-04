"""Release archives must fit the upload budget before publication."""

from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "validate_pypi_artifacts.py"
_VALIDATOR = runpy.run_path(str(SCRIPT))
validate_artifacts = _VALIDATOR["validate_artifacts"]
MAX_ARTIFACT_BYTES = _VALIDATOR["MAX_ARTIFACT_BYTES"]


def distributions(tmp_path: Path) -> tuple[Path, Path]:
    wheel = tmp_path / "openjarvis-1.0.4-py3-none-any.whl"
    sdist = tmp_path / "openjarvis-1.0.4.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")
    return wheel, sdist


def test_reports_both_artifacts_within_budget(tmp_path, capsys):
    wheel, sdist = distributions(tmp_path)
    validate_artifacts(tmp_path)
    output = capsys.readouterr().out
    assert wheel.name in output and sdist.name in output
    assert "5 bytes" in output
    assert "MiB" in output


@pytest.mark.parametrize("artifact_index", [0, 1])
def test_rejects_oversized_wheel_or_sdist(tmp_path, artifact_index, capsys):
    archives = distributions(tmp_path)
    oversized = archives[artifact_index]
    with oversized.open("wb") as archive:
        archive.truncate(MAX_ARTIFACT_BYTES + 1)
    with pytest.raises(ValueError, match=oversized.name):
        validate_artifacts(tmp_path)
    output = capsys.readouterr().out
    assert all(artifact.name in output for artifact in archives)


def test_exact_budget_is_allowed(tmp_path):
    wheel, _ = distributions(tmp_path)
    with wheel.open("wb") as archive:
        archive.truncate(MAX_ARTIFACT_BYTES)
    validate_artifacts(tmp_path)


@pytest.mark.parametrize("missing", ["wheel", "sdist", "both"])
def test_missing_distribution_is_an_error(tmp_path, missing):
    wheel, sdist = distributions(tmp_path)
    if missing in {"wheel", "both"}:
        wheel.unlink()
    if missing in {"sdist", "both"}:
        sdist.unlink()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "Expected at least one wheel and one" in result.stderr


def test_metadata_and_size_validation_precede_both_upload_paths():
    workflow = yaml.safe_load((ROOT / ".github/workflows/pypi-publish.yml").read_text())
    steps = workflow["jobs"]["publish"]["steps"]
    validation = next(
        index
        for index, step in enumerate(steps)
        if "uvx twine check --strict" in step.get("run", "")
    )
    assert "validate_pypi_artifacts.py" in steps[validation]["run"]
    assert "if" not in steps[validation]
    uploads = [
        index for index, step in enumerate(steps) if "uv publish" in step.get("run", "")
    ]
    assert len(uploads) == 2
    assert all(validation < index for index in uploads)
