"""Tests for discover_skills() failure diagnostics (#780).

All three discovery branches (flat *.toml files, direct skill
directories, sourced-layout skill directories) used a bare
`except Exception: continue` with no logging, so a malformed skill
vanished from the returned list with zero diagnostic output — unlike
`_read_source_metadata` and `SkillOverlayLoader.load` elsewhere in the
codebase, which both log a warning on similar failures.
"""

from __future__ import annotations

import logging
from pathlib import Path

from openjarvis.skills.loader import discover_skills


def _write_valid_toml_skill(directory: Path, name: str) -> None:
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.toml").write_text(
        f'[skill]\nname = "{name}"\ndescription = "{name}"\n'
    )


def _write_malformed_toml_skill(directory: Path, name: str) -> None:
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "skill.toml").write_text("this is not [valid toml")


class TestDiscoverSkillsLogsFailures:
    def test_malformed_flat_toml_logged(self, tmp_path, caplog):
        (tmp_path / "broken.toml").write_text("this is not [valid toml")

        with caplog.at_level(logging.WARNING):
            manifests = discover_skills(tmp_path)

        assert manifests == []
        messages = [r.message for r in caplog.records]
        assert any("broken.toml" in m for m in messages), (
            f"no warning mentioning the bad file; got: {messages}"
        )

    def test_malformed_skill_directory_logged(self, tmp_path, caplog):
        _write_malformed_toml_skill(tmp_path, "broken")

        with caplog.at_level(logging.WARNING):
            manifests = discover_skills(tmp_path)

        assert manifests == []
        assert any("broken" in r.message for r in caplog.records)

    def test_malformed_sourced_skill_logged(self, tmp_path, caplog):
        source_dir = tmp_path / "some_source"
        _write_malformed_toml_skill(source_dir, "broken")

        with caplog.at_level(logging.WARNING):
            manifests = discover_skills(tmp_path)

        assert manifests == []
        assert any("broken" in r.message for r in caplog.records)

    def test_valid_skill_alongside_malformed_still_loads(self, tmp_path, caplog):
        """A malformed skill must not prevent its valid siblings from
        loading, and its failure must still be logged."""
        _write_valid_toml_skill(tmp_path, "good")
        _write_malformed_toml_skill(tmp_path, "bad")

        with caplog.at_level(logging.WARNING):
            manifests = discover_skills(tmp_path)

        assert [m.name for m in manifests] == ["good"]
        assert any("bad" in r.message for r in caplog.records)
