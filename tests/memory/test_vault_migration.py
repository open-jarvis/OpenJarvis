from __future__ import annotations

import hashlib
import json
from pathlib import Path

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.memory.migration import analyze_vault_migration


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.md"))
    }


def _synthetic_legacy_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "synthetic-legacy-vault"
    (vault / "old").mkdir(parents=True)
    (vault / "parallel").mkdir()
    (vault / "old" / "missing.md").write_text(
        "---\n"
        "type: preference\n"
        "custom: keep-me\n"
        "---\n"
        "User prefers Python.\n",
        encoding="utf-8",
    )
    duplicate_id = "11111111-1111-4111-8111-111111111111"
    for folder, name in (("old", "one.md"), ("parallel", "two.md")):
        (vault / folder / name).write_text(
            f"---\nid: {duplicate_id}\nconflict_key: city\n---\n"
            + ("Graz\n" if name == "one.md" else "Wien\n"),
            encoding="utf-8",
        )
    (vault / "parallel" / "copy.md").write_text(
        "User prefers Python.\n",
        encoding="utf-8",
    )
    (vault / "invalid.md").write_text(
        "---\ntags: [broken\n---\nBody\n",
        encoding="utf-8",
    )
    return vault


def test_migration_dry_run_reports_schema_identity_and_conflicts(
    tmp_path: Path,
) -> None:
    vault = _synthetic_legacy_vault(tmp_path)
    before = _hashes(vault)

    report = analyze_vault_migration(vault)

    assert report.dry_run is True
    assert report.markdown_files == 5
    assert report.missing_ids == 2
    assert report.invalid_yaml == 1
    assert report.duplicate_ids == 1
    assert report.possible_conflicts == 1
    assert set(report.parallel_folder_schemas) == {"(root)", "old", "parallel"}
    assert report.planned_changes
    assert "<generate-uuid-during-approved-migration>" in "\n".join(
        change.diff for change in report.planned_changes
    )
    assert report.source_hashes_unchanged is True
    assert _hashes(vault) == before


def test_duplicate_bodies_are_reported_without_content_in_findings(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    for name in ("one.md", "two.md"):
        (vault / name).write_text("Same synthetic body.\n", encoding="utf-8")

    report = analyze_vault_migration(vault)

    assert report.possible_duplicate_groups == 1
    assert sum(item.kind == "possible_duplicate" for item in report.findings) == 2


def test_memory_migration_cli_is_json_and_read_only(tmp_path: Path) -> None:
    vault = _synthetic_legacy_vault(tmp_path)
    before = _hashes(vault)

    result = CliRunner().invoke(
        cli,
        ["memory", "migration", "--dry-run", "--vault", str(vault)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["source_hashes_unchanged"] is True
    assert _hashes(vault) == before


def test_memory_migration_cli_has_no_apply_mode(tmp_path: Path) -> None:
    vault = _synthetic_legacy_vault(tmp_path)
    before = _hashes(vault)

    result = CliRunner().invoke(
        cli,
        ["memory", "migration", "--apply", "--vault", str(vault)],
    )

    assert result.exit_code != 0
    assert "No such option: --apply" in result.output
    assert _hashes(vault) == before
