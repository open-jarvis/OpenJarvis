"""Retrieval invariants using only synthetic Markdown and local FTS5."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx
import pytest

from openjarvis.memory.vault_index import VaultIndex
from openjarvis.memory.vault_models import EvidenceStatus
from openjarvis.memory.vault_retrieval import VaultRetriever, normalize_query


def _note(
    path: Path,
    *,
    title: str,
    body: str,
    aliases: tuple[str, ...] = (),
    tags: tuple[str, ...] = (),
    scope: str = "personal",
    project: str | None = None,
    status: str = "active",
    source: str = "manual",
    created_at: str = "2026-07-01T10:00:00+00:00",
    updated_at: str = "2026-07-01T10:00:00+00:00",
    extra: str = "",
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    note_id = str(uuid.uuid4())
    project_yaml = f"project: {project}\n" if project else "project: null\n"
    path.write_text(
        "---\n"
        f"id: {note_id}\n"
        "schema_version: 1\n"
        "type: fact\n"
        f"status: {status}\n"
        f"scope: {scope}\n"
        f"{project_yaml}"
        f"tags: [{', '.join(tags)}]\n"
        f"aliases: [{', '.join(aliases)}]\n"
        f"source: {source}\n"
        f"created_at: {created_at}\n"
        f"updated_at: {updated_at}\n"
        f"title: {title}\n"
        f"{extra}"
        "---\n"
        f"{body.rstrip()}\n",
        encoding="utf-8",
    )
    return note_id


@pytest.fixture()
def retrieval(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    index = VaultIndex(vault, tmp_path / "state" / "memory.sqlite3")
    yield vault, index, VaultRetriever(index)
    index.close()


def test_query_normalization_preserves_german_and_arabic() -> None:
    assert normalize_query("  GRÜSSE   مرحبا  ") == "grüsse مرحبا"


def test_fts5_retrieval_does_not_call_ollama(retrieval, monkeypatch) -> None:
    vault, index, retriever = retrieval
    _note(vault / "python.md", title="Python", body="Python is preferred.")
    index.rebuild()

    def fail_network(*_args, **_kwargs):
        raise AssertionError("disabled embeddings attempted an HTTP request")

    monkeypatch.setattr(httpx, "post", fail_network)
    result = retriever.search("Python")

    assert result.evidence_status is EvidenceStatus.SUFFICIENT
    assert result.retrieval_method == "fts5_bm25"
    assert index.health().embeddings_enabled is False


def test_title_is_weighted_above_body_only_match(retrieval) -> None:
    vault, index, retriever = retrieval
    title_id = _note(
        vault / "title.md",
        title="Python Packaging",
        body="A short build note.",
    )
    _note(
        vault / "body.md",
        title="General Notes",
        body="Python packaging Python packaging appears in the body.",
    )
    index.rebuild()

    result = retriever.search("Python Packaging", top_k=2)

    assert result.selected_sources[0].note_id == title_id
    assert "title" in result.selected_sources[0].selection_reason


def test_alias_search_returns_canonical_note(retrieval) -> None:
    vault, index, retriever = retrieval
    note_id = _note(
        vault / "alias.md",
        title="Canonical Title",
        aliases=("Friendly Shortcut",),
        body="Alias-backed content.",
    )
    index.rebuild()

    result = retriever.search("Friendly Shortcut")

    assert result.selected_sources[0].note_id == note_id
    assert "alias match" in result.selected_sources[0].selection_reason


def test_tag_scope_project_and_time_filters(retrieval) -> None:
    vault, index, retriever = retrieval
    expected = _note(
        vault / "apollo" / "current.md",
        title="Current Apollo",
        body="The launch checklist uses Python.",
        tags=("launch",),
        scope="work",
        project="Apollo",
        updated_at="2026-07-20T10:00:00+00:00",
    )
    _note(
        vault / "apollo" / "old.md",
        title="Old Apollo",
        body="The launch checklist uses Python.",
        tags=("launch",),
        scope="work",
        project="Apollo",
        updated_at="2026-06-01T10:00:00+00:00",
    )
    _note(
        vault / "personal.md",
        title="Personal",
        body="The launch checklist uses Python.",
        tags=("launch",),
        scope="personal",
        project="Apollo",
        updated_at="2026-07-20T10:00:00+00:00",
    )
    index.rebuild()

    result = retriever.search(
        "launch Python",
        filters={
            "tags": ["launch"],
            "scope": "work",
            "project": "Apollo",
            "since": "2026-07-01T00:00:00+00:00",
        },
    )

    assert [source.note_id for source in result.selected_sources] == [expected]


def test_archived_notes_are_excluded_unless_requested(retrieval) -> None:
    vault, index, retriever = retrieval
    archived_id = _note(
        vault / "archive" / "old.md",
        title="Archived Python",
        body="Archived Python detail.",
        status="archived",
    )
    index.rebuild()

    hidden = retriever.search("Archived Python")
    visible = retriever.search(
        "Archived Python",
        filters={"status": "archived", "include_archived": True},
    )

    assert hidden.evidence_status is EvidenceStatus.INSUFFICIENT
    assert visible.selected_sources[0].note_id == archived_id


def test_duplicate_content_is_returned_only_once(retrieval) -> None:
    vault, index, retriever = retrieval
    _note(vault / "one.md", title="One", body="Shared Python preference.")
    _note(vault / "two.md", title="Two", body="Shared Python preference.")
    index.rebuild()

    result = retriever.search("Python preference", top_k=5)

    assert len(result.selected_sources) == 1
    assert len(result.candidates) == 1


def test_user_correction_wins_duplicate_source_priority(retrieval) -> None:
    vault, index, retriever = retrieval
    _note(
        vault / "inferred.md",
        title="Inferred",
        body="The user prefers concise answers.",
        source="inferred",
    )
    correction_id = _note(
        vault / "correction.md",
        title="Correction",
        body="The user prefers concise answers.",
        source="user_correction",
    )
    index.rebuild()

    result = retriever.search("prefers concise answers")

    assert result.selected_sources[0].note_id == correction_id


def test_conflicting_sources_produce_conflicting_evidence(retrieval) -> None:
    vault, index, retriever = retrieval
    extra = "conflict_key: residence\n"
    _note(
        vault / "graz.md",
        title="Residence Graz",
        body="Ich wohne in Graz.",
        extra=extra,
    )
    _note(
        vault / "wien.md",
        title="Residence Wien",
        body="Ich wohne in Wien.",
        source="user_correction",
        extra=extra,
    )
    index.rebuild()

    result = retriever.search("Ich wohne", top_k=5)

    assert result.evidence_status is EvidenceStatus.CONFLICTING
    assert len(result.selected_sources) == 2
    assert "conflict" in result.warnings[0]


def test_missing_result_reports_insufficient_evidence(retrieval) -> None:
    vault, index, retriever = retrieval
    _note(vault / "known.md", title="Known", body="Only Python is discussed.")
    index.rebuild()

    result = retriever.search("quantum entanglement")

    assert result.evidence_status is EvidenceStatus.INSUFFICIENT
    assert result.evidence_code == "insufficient_evidence"
    assert result.selected_sources == ()


def test_partial_query_does_not_overstate_evidence(retrieval) -> None:
    vault, index, retriever = retrieval
    _note(vault / "python.md", title="Python", body="Python is known.")
    index.rebuild()

    result = retriever.search("Python quantum banana")

    assert result.evidence_status in {
        EvidenceStatus.INSUFFICIENT,
        EvidenceStatus.PARTIAL,
    }
    assert result.evidence_status is not EvidenceStatus.SUFFICIENT


def test_only_selected_sources_are_persisted(retrieval) -> None:
    vault, index, retriever = retrieval
    for number in range(3):
        _note(
            vault / f"folder-{number}" / "note.md",
            title=f"Python {number}",
            body=f"Python source number {number}.",
        )
    index.rebuild()

    result = retriever.search(
        "Python source",
        top_k=1,
        task_id="task-1",
        session_id="session-1",
        correlation_id="correlation-1",
        thread_id="thread-1",
        turn_id="turn-1",
    )
    rows = index.connection.execute(
        "SELECT * FROM memory_sources WHERE retrieval_id=?",
        (result.retrieval_id,),
    ).fetchall()

    assert len(result.candidates) == 3
    assert len(result.selected_sources) == 1
    assert len(rows) == 1
    assert rows[0]["note_id"] == result.selected_sources[0].note_id
    assert rows[0]["task_id"] == "task-1"
    assert rows[0]["turn_id"] == "turn-1"


def test_large_note_source_is_bounded_and_line_referenced(retrieval) -> None:
    vault, index, retriever = retrieval
    body = (
        "# Intro\n"
        + ("filler line\n" * 1000)
        + "# Decision\n"
        + "The selected database is SQLite for reliable local retrieval.\n"
        + ("more filler\n" * 1000)
    )
    _note(vault / "large.md", title="Architecture", body=body)
    index.rebuild()

    source = retriever.search("selected database SQLite").selected_sources[0]

    assert len(source.relevant_text) <= 601
    assert "selected database" in source.relevant_text
    assert source.section == "Decision"
    assert source.line_start is not None
    assert source.line_end is not None
    assert len(source.relevant_text) < len(body)


def test_arabic_and_german_unicode_retrieval(retrieval) -> None:
    vault, index, retriever = retrieval
    german_id = _note(
        vault / "deutsch.md",
        title="Grüße",
        body="Grüße aus Österreich.",
    )
    arabic_id = _note(
        vault / "arabisch.md",
        title="مرحبا",
        body="مرحبا بالعالم",
    )
    index.rebuild()

    assert retriever.search("GRÜSSE").selected_sources[0].note_id == german_id
    assert retriever.search("مرحبا").selected_sources[0].note_id == arabic_id


def test_closed_index_returns_unavailable_instead_of_claiming_sources(
    retrieval,
) -> None:
    vault, index, retriever = retrieval
    _note(vault / "note.md", title="Python", body="Python source.")
    index.rebuild()
    index.close()

    result = retriever.search("Python")

    assert result.evidence_status is EvidenceStatus.UNAVAILABLE
    assert result.selected_sources == ()
