"""Tests for `jarvis science-lab` CLI command."""

from __future__ import annotations

from click.testing import CliRunner

from openjarvis.science_lab.models import ConfidenceScore, ScienceProject
from openjarvis.science_lab.store import ScienceProjectStore


def test_science_lab_command_exists():
    from openjarvis.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["science-lab", "--help"])
    assert result.exit_code == 0
    assert "science" in result.output.lower()


def test_list_empty(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "science_lab.db")
    runner = CliRunner()
    result = runner.invoke(cli, ["science-lab", "list", "--db-path", db_path])
    assert result.exit_code == 0
    assert "no saved projects" in result.output.lower()


def test_list_shows_saved_project(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "science_lab.db")
    store = ScienceProjectStore(db_path=db_path)
    store.save(
        ScienceProject(
            name="spider-fluid",
            objective="Fluido tipo teia",
            confidence=ConfidenceScore(0.5),
        )
    )
    store.close()

    runner = CliRunner()
    result = runner.invoke(cli, ["science-lab", "list", "--db-path", db_path])
    assert result.exit_code == 0
    assert "spider-fluid" in result.output


def test_show_missing_project(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "science_lab.db")
    runner = CliRunner()
    result = runner.invoke(cli, ["science-lab", "show", "nope", "--db-path", db_path])
    assert result.exit_code == 0
    assert "no project named" in result.output.lower()


def test_show_existing_project(tmp_path):
    from openjarvis.cli import cli

    db_path = str(tmp_path / "science_lab.db")
    store = ScienceProjectStore(db_path=db_path)
    store.save(
        ScienceProject(
            name="spider-fluid",
            objective="Fluido tipo teia",
            confidence=ConfidenceScore(0.5),
        )
    )
    store.close()

    runner = CliRunner()
    result = runner.invoke(
        cli, ["science-lab", "show", "spider-fluid", "--db-path", db_path]
    )
    assert result.exit_code == 0
    assert "Fluido tipo teia" in result.output
