"""Synthetic tests for the reconstructible Markdown vault index."""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_models import ConflictState


def _write_note(
    path: Path,
    *,
    note_id: str | None = None,
    title: str | None = None,
    body: str = "Body",
    extra: str = "",
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    actual_id = note_id or str(uuid.uuid4())
    configured_title = f"title: {title}\n" if title else ""
    path.write_text(
        "---\n"
        f"id: {actual_id}\n"
        "schema_version: 1\n"
        "type: fact\n"
        "status: active\n"
        "scope: personal\n"
        f"{configured_title}"
        f"{extra}"
        "---\n"
        f"{body.rstrip()}\n",
        encoding="utf-8",
    )
    return actual_id


@pytest.fixture()
def index_paths(tmp_path: Path) -> tuple[Path, Path]:
    vault = tmp_path / "vault"
    state = tmp_path / "state"
    vault.mkdir()
    state.mkdir()
    return vault, state / "memory.sqlite3"


def test_rebuild_enables_wal_foreign_keys_and_fts5(index_paths) -> None:
    vault, db = index_paths
    _write_note(vault / "one.md", body="Python is preferred.")

    with VaultIndex(vault, db) as index:
        report = index.rebuild()
        journal = index.connection.execute("PRAGMA journal_mode").fetchone()[0]
        foreign_keys = index.connection.execute("PRAGMA foreign_keys").fetchone()[0]

        assert report.indexed == 1
        assert journal.casefold() == "wal"
        assert foreign_keys == 1
        assert index.fts5_available is True
        assert index.schema_version() == 2


def test_legacy_and_invalid_yaml_are_read_only_indexed(index_paths) -> None:
    vault, db = index_paths
    legacy = vault / "legacy.md"
    legacy.write_text("# Legacy\n\nUnchanged\n", encoding="utf-8")
    invalid = vault / "broken.md"
    invalid.write_text("---\ntags: [one, two\n---\nBroken\n", encoding="utf-8")
    before_legacy = legacy.read_bytes()
    before_invalid = invalid.read_bytes()

    with VaultIndex(vault, db) as index:
        report = index.rebuild()
        notes = index.list_notes()

        assert report.discovered == 2
        assert report.indexed == 1
        assert report.schema_valid == 1
        assert report.rejected == 1
        assert report.parser_errors == 1
        assert any(note.note_id.startswith("provisional:") for note in notes)
        assert any(
            note.conflict_state is ConflictState.INVALID_SCHEMA for note in notes
        )
        assert index.list_errors()[0]["error_type"] == "parser_error"
    assert legacy.read_bytes() == before_legacy
    assert invalid.read_bytes() == before_invalid


def test_duplicate_ids_are_detected_without_overwriting(index_paths) -> None:
    vault, db = index_paths
    shared_id = str(uuid.uuid4())
    _write_note(vault / "a.md", note_id=shared_id, body="First")
    _write_note(vault / "b.md", note_id=shared_id, body="Second")

    with VaultIndex(vault, db) as index:
        report = index.rebuild()

        assert report.duplicate_ids == 1
        assert report.indexed == 1
        assert index.get_note(shared_id) is not None
        assert any(
            error["error_type"] == "duplicate_id" for error in index.list_errors()
        )


def test_incremental_move_preserves_stable_id(index_paths) -> None:
    vault, db = index_paths
    note_id = _write_note(vault / "inbox" / "before.md", body="Move me")
    with VaultIndex(vault, db) as index:
        index.rebuild()
        moved = vault / "projects" / "after.md"
        moved.parent.mkdir()
        shutil.move(vault / "inbox" / "before.md", moved)

        report = index.sync()
        note = index.get_note(note_id)
        history = index.connection.execute(
            """
            SELECT path, active FROM memory_note_paths
            WHERE note_id=? ORDER BY path
            """,
            (note_id,),
        ).fetchall()

        assert report.moved == 1
        assert report.created == 0
        assert report.deleted == 0
        assert note is not None
        assert note.path == "projects/after.md"
        assert {(row["path"], row["active"]) for row in history} == {
            ("inbox/before.md", 0),
            ("projects/after.md", 1),
        }


def test_incremental_create_modify_delete(index_paths) -> None:
    vault, db = index_paths
    first_id = _write_note(vault / "first.md", body="First version")
    with VaultIndex(vault, db) as index:
        index.rebuild()
        second_id = _write_note(vault / "second.md", body="Created later")
        _write_note(
            vault / "first.md",
            note_id=first_id,
            body="Modified version",
        )
        changed = index.sync()
        assert changed.created == 1
        assert changed.modified == 1
        assert index.get_note(second_id) is not None

        (vault / "first.md").unlink()
        deleted = index.sync()
        assert deleted.deleted == 1
        assert index.get_note(first_id) is None


def test_identical_bodies_are_visible_duplicates(index_paths) -> None:
    vault, db = index_paths
    _write_note(vault / "a.md", body="Exactly the same fact.")
    _write_note(vault / "b.md", body="Exactly the same fact.")

    with VaultIndex(vault, db) as index:
        report = index.rebuild()
        states = {note.conflict_state for note in index.list_notes()}

        assert report.duplicate_contents == 1
        assert states == {ConflictState.DUPLICATE}
        assert index.health().open_conflicts == 1


def test_conflict_key_marks_disagreeing_facts(index_paths) -> None:
    vault, db = index_paths
    extra = "conflict_key: residence\n"
    _write_note(vault / "graz.md", body="Ich wohne in Graz.", extra=extra)
    _write_note(vault / "wien.md", body="Ich wohne in Wien.", extra=extra)

    with VaultIndex(vault, db) as index:
        report = index.rebuild()

        assert report.conflicts == 1
        assert {note.conflict_state for note in index.list_notes()} == {
            ConflictState.CONFIRMED_CONFLICT
        }
        row = index.connection.execute(
            "SELECT conflict_type FROM memory_conflicts"
        ).fetchone()
        assert row["conflict_type"] == "index.conflicting_fact"


def test_wikilinks_backlinks_cycles_and_unresolved_links(index_paths) -> None:
    vault, db = index_paths
    alpha_id = _write_note(
        vault / "alpha.md",
        title="Alpha",
        body="[[Beta#Details|Shown]] and [[Missing]]",
    )
    beta_id = _write_note(
        vault / "beta.md",
        title="Beta",
        body="[[Alpha]]",
    )

    with VaultIndex(vault, db) as index:
        index.rebuild()
        alpha_links = index.note_links(alpha_id)
        beta_links = index.note_links(beta_id)

        resolved = next(
            item for item in alpha_links["outgoing"] if item["target_title"] == "Beta"
        )
        missing = next(
            item
            for item in alpha_links["outgoing"]
            if item["target_title"] == "Missing"
        )
        assert resolved["target_note_id"] == beta_id
        assert resolved["heading"] == "Details"
        assert resolved["alias"] == "Shown"
        assert missing["resolved"] is False
        assert beta_links["backlinks"][0]["source_note_id"] == alpha_id
        assert alpha_links["backlinks"][0]["source_note_id"] == beta_id


def test_same_titles_make_wikilink_ambiguous(index_paths) -> None:
    vault, db = index_paths
    _write_note(vault / "one" / "same.md", title="Same", body="One")
    _write_note(vault / "two" / "same.md", title="Same", body="Two")
    source_id = _write_note(vault / "source.md", body="[[Same]]")

    with VaultIndex(vault, db) as index:
        index.rebuild()
        link = index.note_links(source_id)["outgoing"][0]

        assert link["ambiguous"] is True
        assert link["resolved"] is False
        assert link["target_note_id"] is None


def test_alias_link_resolves_to_stable_note_id(index_paths) -> None:
    vault, db = index_paths
    target_id = _write_note(
        vault / "target.md",
        title="Canonical",
        body="Target",
        extra="aliases: [Friendly Name]\n",
    )
    source_id = _write_note(vault / "source.md", body="[[Friendly Name]]")

    with VaultIndex(vault, db) as index:
        index.rebuild()

        assert index.note_links(source_id)["outgoing"][0]["target_note_id"] == target_id


def test_graph_contains_note_folder_project_and_wikilink_edges(index_paths) -> None:
    vault, db = index_paths
    target_id = _write_note(vault / "projects" / "target.md", body="Target")
    source_id = _write_note(
        vault / "projects" / "source.md",
        body="[[target]]",
        extra="project: Apollo\n",
    )

    with VaultIndex(vault, db) as index:
        index.rebuild()
        graph = index.graph()

        assert {node["id"] for node in graph["nodes"]} == {source_id, target_id}
        edge_types = {edge["type"] for edge in graph["edges"]}
        assert {"folder", "project", "wikilink"} <= edge_types
        wikilink = next(edge for edge in graph["edges"] if edge["type"] == "wikilink")
        assert wikilink["source"] == source_id
        assert wikilink["target"] == target_id


def test_archived_notes_are_indexed_and_marked(index_paths) -> None:
    vault, db = index_paths
    note_id = _write_note(vault / "archive" / "old.md", body="Old")

    with VaultIndex(vault, db) as index:
        index.rebuild()
        note = index.get_note(note_id)

        assert note is not None
        assert note.archived is True


def test_unicode_large_note_and_windows_style_name(index_paths) -> None:
    vault, db = index_paths
    body = ("Grüße aus Wien — مرحبا\n" * 5000).rstrip()
    note_id = _write_note(vault / "Ordner" / "Notiz Ä.md", body=body)

    with VaultIndex(vault, db) as index:
        report = index.rebuild()
        note = index.get_note(note_id)

        assert report.indexed == 1
        assert note is not None
        assert "مرحبا" in note.body
        assert note.path == "Ordner/Notiz Ä.md"


def test_restart_recovers_index_without_touching_markdown(index_paths) -> None:
    vault, db = index_paths
    note_id = _write_note(vault / "persist.md", body="Persisted projection")
    original = (vault / "persist.md").read_bytes()
    with VaultIndex(vault, db) as first:
        first.rebuild()

    with VaultIndex(vault, db) as reopened:
        note = reopened.get_note(note_id)
        report = reopened.sync()

        assert note is not None
        assert report.unchanged == 1
        assert reopened.health().last_successful_index is not None
    assert (vault / "persist.md").read_bytes() == original


def test_index_must_live_outside_vault(index_paths) -> None:
    vault, _db = index_paths

    with pytest.raises(ValueError, match="outside"):
        VaultIndex(vault, vault / ".index" / "memory.sqlite3")


def test_symlink_or_junction_is_not_indexed(index_paths) -> None:
    vault, db = index_paths
    outside = vault.parent / "outside"
    outside.mkdir()
    _write_note(outside / "secret.md", body="Must not cross boundary")
    link = vault / "linked"
    try:
        if os.name == "nt":
            os.symlink(outside, link, target_is_directory=True)
        else:
            link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable for this test account")

    with VaultIndex(vault, db) as index:
        report = index.rebuild()

        assert report.indexed == 0
        assert any(
            item["error_type"] == "reparse_point" for item in index.list_errors()
        )


def test_database_can_be_rebuilt_after_manual_index_loss(index_paths) -> None:
    vault, db = index_paths
    note_id = _write_note(vault / "source.md", body="Markdown remains truth")
    with VaultIndex(vault, db) as index:
        index.rebuild()
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{db}{suffix}")
        if candidate.exists():
            candidate.unlink()

    with VaultIndex(vault, db) as rebuilt:
        report = rebuilt.rebuild()

        assert report.indexed == 1
        assert rebuilt.get_note(note_id) is not None
        assert isinstance(rebuilt.connection, sqlite3.Connection)
