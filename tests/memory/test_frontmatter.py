"""Synthetic-vault tests for round-trip frontmatter and note identity."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from openjarvis.memory.frontmatter import (
    FrontmatterError,
    extract_wikilinks,
    load_memory_note,
    parse_markdown,
    render_canonical_markdown,
    render_with_updates,
)
from openjarvis.memory.vault_models import ConflictState, IdentityKind


def test_parses_full_yaml_frontmatter() -> None:
    parsed = parse_markdown(
        "---\n"
        "title: \"Komplexe Notiz\"\n"
        "tags:\n"
        "  - deutsch\n"
        "  - \"بحث\"\n"
        "nested:\n"
        "  owner:\n"
        "    name: Ada\n"
        "description: |\n"
        "  first line\n"
        "  second line\n"
        "---\n"
        "# Inhalt\n"
    )

    assert parsed.error is None
    assert parsed.metadata["nested"]["owner"]["name"] == "Ada"
    assert parsed.metadata["tags"] == ["deutsch", "بحث"]
    assert parsed.metadata["description"] == "first line\nsecond line\n"
    assert parsed.body == "# Inhalt\n"


def test_invalid_yaml_is_reported_without_repair() -> None:
    text = "---\ntags: [one, two\n---\nBody remains\n"

    parsed = parse_markdown(text)

    assert parsed.error is not None
    assert "invalid YAML frontmatter" in parsed.error
    assert parsed.body == "Body remains\n"
    assert parsed.raw_text == text


def test_unknown_fields_and_comments_survive_round_trip() -> None:
    parsed = parse_markdown(
        "---\n"
        "# keep this comment\n"
        "id: 3b241101-e2bb-4255-8caf-4136c566a962\n"
        "unknown_field: \"keep me\" # inline stays\n"
        "nested:\n"
        "  enabled: true\n"
        "---\n"
        "Original body\n"
    )

    rendered = render_with_updates(parsed, {"status": "active"})

    assert "# keep this comment" in rendered
    assert 'unknown_field: "keep me" # inline stays' in rendered
    assert "nested:" in rendered
    assert "Original body\n" in rendered


def test_stable_frontmatter_id_survives_move(tmp_path: Path) -> None:
    note_id = str(uuid.uuid4())
    first = tmp_path / "inbox" / "note.md"
    first.parent.mkdir()
    first.write_text(
        f"---\nid: {note_id}\nschema_version: 1\ntype: fact\n---\nBody\n",
        encoding="utf-8",
    )
    before, _ = load_memory_note(first, tmp_path)
    moved = tmp_path / "projects" / "renamed.md"
    moved.parent.mkdir()
    shutil.move(first, moved)

    after, _ = load_memory_note(moved, tmp_path)

    assert before.note_id == after.note_id == note_id
    assert before.path != after.path
    assert after.identity_kind is IdentityKind.STABLE


def test_legacy_note_without_id_is_read_only_indexable(tmp_path: Path) -> None:
    note = tmp_path / "legacy.md"
    original = "# Legacy\n\nNo frontmatter, no mutation.\n"
    note.write_text(original, encoding="utf-8")

    loaded, _ = load_memory_note(note, tmp_path)

    assert loaded.note_id.startswith("provisional:")
    assert loaded.identity_kind is IdentityKind.PROVISIONAL
    assert loaded.note_type == "capture"
    assert note.read_text(encoding="utf-8") == original


def test_provisional_identity_is_deterministic(tmp_path: Path) -> None:
    note = tmp_path / "legacy.md"
    note.write_text("same legacy content\n", encoding="utf-8")

    first, _ = load_memory_note(note, tmp_path)
    second, _ = load_memory_note(note, tmp_path)

    assert first.note_id == second.note_id
    with pytest.raises(ValueError):
        uuid.UUID(first.note_id)


def test_invalid_existing_id_is_preserved_and_marked(tmp_path: Path) -> None:
    note = tmp_path / "bad-id.md"
    note.write_text("---\nid: not-a-uuid\ntype: fact\n---\nBody\n", encoding="utf-8")

    loaded, _ = load_memory_note(note, tmp_path)

    assert loaded.note_id == "not-a-uuid"
    assert loaded.conflict_state is ConflictState.INVALID_SCHEMA
    assert "not a valid UUID" in (loaded.parser_error or "")


def test_wikilinks_cover_aliases_headings_and_ignore_embeds() -> None:
    body = (
        "[[Plain]] [[Target#Heading|Shown]] ![[image.png]] "
        "[[Deutsch ÄÖÜ]] [[بحث]]"
    )

    assert extract_wikilinks(body) == (
        "Plain",
        "Target#Heading|Shown",
        "Deutsch ÄÖÜ",
        "بحث",
    )


def test_canonical_renderer_requires_uuid() -> None:
    with pytest.raises(FrontmatterError, match="UUID"):
        render_canonical_markdown(
            note_id="provisional:123",
            note_type="fact",
            created_at="2026-07-30T10:00:00+00:00",
            updated_at="2026-07-30T10:00:00+00:00",
            body="Fact",
        )


def test_canonical_renderer_writes_versioned_schema() -> None:
    note_id = str(uuid.uuid4())

    rendered = render_canonical_markdown(
        note_id=note_id,
        note_type="preference",
        tags=("python",),
        aliases=("Coding preference",),
        source="user_correction",
        source_task_id="task-1",
        source_session_id="session-1",
        created_at="2026-07-30T10:00:00+00:00",
        updated_at="2026-07-30T10:00:00+00:00",
        body="Ich bevorzuge Python.",
    )
    parsed = parse_markdown(rendered)

    assert parsed.error is None
    assert parsed.metadata["id"] == note_id
    assert parsed.metadata["schema_version"] == 1
    assert parsed.metadata["type"] == "preference"
    assert parsed.metadata["source"] == "user_correction"
    assert parsed.body == "Ich bevorzuge Python.\n"
