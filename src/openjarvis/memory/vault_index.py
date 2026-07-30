"""Reconstructible SQLite/FTS5 index for a Markdown vault."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import uuid
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from openjarvis.memory.frontmatter import load_memory_note
from openjarvis.memory.vault_models import (
    ConflictState,
    IdentityKind,
    IndexReport,
    MemoryHealth,
    MemoryNote,
)

_INDEX_SCHEMA_VERSION = 1
_TEXT_EXTENSIONS = {".md", ".markdown"}
_SKIP_DIRS = {
    ".git",
    ".obsidian",
    ".trash",
    ".venv",
    "__pycache__",
    "node_modules",
}

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS memory_schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    applied_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_notes (
    note_id             TEXT PRIMARY KEY,
    identity_kind       TEXT NOT NULL,
    path                TEXT NOT NULL UNIQUE,
    title               TEXT NOT NULL,
    note_type           TEXT NOT NULL,
    status              TEXT NOT NULL,
    scope               TEXT NOT NULL,
    project             TEXT,
    source              TEXT NOT NULL,
    source_task_id      TEXT,
    source_session_id   TEXT,
    created_at          TEXT,
    updated_at          TEXT,
    content_hash        TEXT NOT NULL,
    body_hash           TEXT NOT NULL,
    frontmatter_version INTEGER,
    body                TEXT NOT NULL,
    body_start_line     INTEGER NOT NULL DEFAULT 1,
    aliases             TEXT NOT NULL DEFAULT '[]',
    tags                TEXT NOT NULL DEFAULT '[]',
    folder_relations    TEXT NOT NULL DEFAULT '[]',
    archived            INTEGER NOT NULL DEFAULT 0,
    conflict_state      TEXT NOT NULL DEFAULT 'none',
    modified_ns         INTEGER NOT NULL,
    size_bytes          INTEGER NOT NULL,
    indexed_at          TEXT NOT NULL,
    index_status        TEXT NOT NULL,
    parser_error        TEXT,
    raw_frontmatter     TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memory_notes_path
    ON memory_notes(path);
CREATE INDEX IF NOT EXISTS idx_memory_notes_filters
    ON memory_notes(status, scope, project, note_type, archived);
CREATE INDEX IF NOT EXISTS idx_memory_notes_hash
    ON memory_notes(body_hash);

CREATE TABLE IF NOT EXISTS memory_note_paths (
    note_id     TEXT NOT NULL,
    path        TEXT NOT NULL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (note_id, path)
);

CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    note_id UNINDEXED,
    title,
    aliases,
    body,
    tags,
    project,
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS memory_tags (
    note_id TEXT NOT NULL,
    tag     TEXT NOT NULL,
    PRIMARY KEY (note_id, tag),
    FOREIGN KEY (note_id) REFERENCES memory_notes(note_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS memory_links (
    link_id         TEXT PRIMARY KEY,
    source_note_id  TEXT NOT NULL,
    target_note_id  TEXT,
    raw_target      TEXT NOT NULL,
    target_title    TEXT NOT NULL,
    heading         TEXT,
    alias           TEXT,
    resolved        INTEGER NOT NULL DEFAULT 0,
    ambiguous       INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (source_note_id)
        REFERENCES memory_notes(note_id) ON DELETE CASCADE,
    FOREIGN KEY (target_note_id)
        REFERENCES memory_notes(note_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_links_source
    ON memory_links(source_note_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_target
    ON memory_links(target_note_id);

CREATE VIEW IF NOT EXISTS memory_backlinks AS
SELECT target_note_id AS note_id, source_note_id AS backlink_note_id, link_id
FROM memory_links
WHERE target_note_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS memory_relations (
    relation_id    TEXT PRIMARY KEY,
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    relation_type  TEXT NOT NULL,
    metadata       TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memory_relations_source
    ON memory_relations(source_node_id, relation_type);
CREATE INDEX IF NOT EXISTS idx_memory_relations_target
    ON memory_relations(target_node_id, relation_type);

CREATE TABLE IF NOT EXISTS memory_index_errors (
    error_id    TEXT PRIMARY KEY,
    path        TEXT NOT NULL,
    error_type  TEXT NOT NULL,
    message     TEXT NOT NULL,
    content_hash TEXT,
    run_id      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_conflicts (
    conflict_id    TEXT PRIMARY KEY,
    conflict_type  TEXT NOT NULL,
    state          TEXT NOT NULL,
    note_ids       TEXT NOT NULL,
    candidate_id   TEXT,
    summary        TEXT NOT NULL,
    winner_note_id TEXT,
    resolution     TEXT,
    metadata       TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    resolved_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_memory_conflicts_open
    ON memory_conflicts(state, updated_at);

CREATE TABLE IF NOT EXISTS memory_candidates (
    candidate_id       TEXT PRIMARY KEY,
    task_id            TEXT NOT NULL,
    session_id         TEXT NOT NULL,
    correlation_id     TEXT NOT NULL,
    note_id            TEXT NOT NULL,
    proposed_path      TEXT NOT NULL,
    note_type          TEXT NOT NULL,
    scope              TEXT NOT NULL,
    project            TEXT,
    source             TEXT NOT NULL,
    body               TEXT NOT NULL,
    planned_markdown   TEXT NOT NULL,
    planned_diff       TEXT NOT NULL,
    before_hash        TEXT,
    expected_version   TEXT,
    risk_level         INTEGER NOT NULL,
    status             TEXT NOT NULL,
    approval_id        TEXT,
    conflict_state     TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    applied_at         TEXT,
    write_operation_id TEXT,
    metadata           TEXT NOT NULL DEFAULT '{}',
    CHECK (risk_level BETWEEN 0 AND 4)
);

CREATE INDEX IF NOT EXISTS idx_memory_candidates_open
    ON memory_candidates(status, updated_at);

CREATE TABLE IF NOT EXISTS memory_write_operations (
    operation_id   TEXT PRIMARY KEY,
    candidate_id   TEXT NOT NULL,
    task_id        TEXT NOT NULL,
    path           TEXT NOT NULL,
    before_hash    TEXT,
    after_hash     TEXT,
    diff           TEXT NOT NULL,
    restore_path   TEXT,
    status         TEXT NOT NULL,
    error          TEXT,
    created_at     TEXT NOT NULL,
    completed_at   TEXT,
    FOREIGN KEY (candidate_id)
        REFERENCES memory_candidates(candidate_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS memory_sources (
    source_id        TEXT PRIMARY KEY,
    retrieval_id     TEXT NOT NULL,
    task_id          TEXT,
    session_id       TEXT,
    correlation_id   TEXT,
    thread_id        TEXT,
    turn_id          TEXT,
    note_id          TEXT NOT NULL,
    path             TEXT NOT NULL,
    title            TEXT NOT NULL,
    relevant_text    TEXT NOT NULL,
    line_start       INTEGER,
    line_end         INTEGER,
    section          TEXT,
    score            REAL NOT NULL,
    selection_reason TEXT NOT NULL,
    content_hash     TEXT NOT NULL,
    indexed_at       TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memory_sources_retrieval
    ON memory_sources(retrieval_id, score DESC);
CREATE INDEX IF NOT EXISTS idx_memory_sources_task
    ON memory_sources(task_id, created_at);

CREATE TABLE IF NOT EXISTS memory_index_runs (
    run_id             TEXT PRIMARY KEY,
    mode               TEXT NOT NULL,
    started_at         TEXT NOT NULL,
    completed_at       TEXT,
    status             TEXT NOT NULL,
    scanned            INTEGER NOT NULL DEFAULT 0,
    indexed            INTEGER NOT NULL DEFAULT 0,
    parser_errors      INTEGER NOT NULL DEFAULT 0,
    report             TEXT NOT NULL DEFAULT '{}',
    error              TEXT
);

CREATE TABLE IF NOT EXISTS memory_api_operations (
    operation_key TEXT PRIMARY KEY,
    operation     TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    result        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _body_hash(body: str) -> str:
    normalized = "\n".join(line.rstrip() for line in body.strip().splitlines())
    return hashlib.sha256(normalized.casefold().encode("utf-8")).hexdigest()


def _stable_digest(*parts: str) -> str:
    payload = "\0".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    if os.name != "nt":
        return False
    try:
        attributes = os.lstat(path).st_file_attributes
    except (AttributeError, OSError):
        return False
    return bool(attributes & 0x400)


def _link_parts(raw: str) -> tuple[str, str | None, str | None]:
    target, separator, alias = raw.partition("|")
    title, heading_separator, heading = target.partition("#")
    return (
        title.strip(),
        heading.strip() if heading_separator and heading.strip() else None,
        alias.strip() if separator and alias.strip() else None,
    )


class VaultIndex:
    """A disposable projection that can be fully rebuilt from Markdown."""

    def __init__(
        self,
        vault_root: str | Path,
        db_path: str | Path,
        *,
        mode: str = "read-only",
        embeddings_enabled: bool = False,
        busy_timeout_ms: int = 5000,
    ) -> None:
        if mode not in {"read-only", "writable-test"}:
            raise ValueError("mode must be 'read-only' or 'writable-test'")
        self.vault_root = Path(vault_root).expanduser().resolve(strict=True)
        if not self.vault_root.is_dir():
            raise ValueError("vault_root must be an existing directory")
        if _is_reparse_point(self.vault_root):
            raise ValueError("vault_root cannot be a symlink or junction")

        self.db_path = Path(db_path).expanduser()
        if str(db_path) != ":memory:":
            resolved_db = self.db_path.resolve(strict=False)
            if resolved_db == self.vault_root or self.vault_root in resolved_db.parents:
                raise ValueError("vault index must be stored outside the vault")
            resolved_db.parent.mkdir(parents=True, exist_ok=True)
            self.db_path = resolved_db
        self.mode = mode
        self.embeddings_enabled = bool(embeddings_enabled)
        self._lock = threading.RLock()
        self._closed = False
        self._last_error: str | None = None
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=max(0.1, busy_timeout_ms / 1000),
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute(f"PRAGMA busy_timeout={max(1, busy_timeout_ms)}")
        if str(db_path) != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=FULL")
        self._fts5_available = self._check_fts5()
        if not self._fts5_available:
            self._conn.close()
            raise RuntimeError("SQLite FTS5 is unavailable in this Python runtime")
        self._migrate()

    @property
    def connection(self) -> sqlite3.Connection:
        """Expose the connection to closely related service components."""

        if self._closed:
            raise RuntimeError("vault index is closed")
        return self._conn

    @property
    def fts5_available(self) -> bool:
        return self._fts5_available

    def _check_fts5(self) -> bool:
        try:
            self._conn.execute("CREATE VIRTUAL TABLE temp.fts5_probe USING fts5(x)")
            self._conn.execute("DROP TABLE temp.fts5_probe")
            return True
        except sqlite3.Error:
            return False

    def _migrate(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
            self._conn.execute(
                """
                INSERT OR IGNORE INTO memory_schema_migrations
                    (version, name, applied_at)
                VALUES (?, ?, ?)
                """,
                (_INDEX_SCHEMA_VERSION, "initial vault memory index", _now()),
            )

    def schema_version(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM memory_schema_migrations"
        ).fetchone()
        return int(row[0]) if row else 0

    def _iter_paths(self) -> Iterator[Path]:
        for path in sorted(self.vault_root.rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in _TEXT_EXTENSIONS:
                continue
            relative = path.relative_to(self.vault_root)
            if any(
                part.startswith(".") or part in _SKIP_DIRS
                for part in relative.parts[:-1]
            ):
                continue
            if _is_reparse_point(path):
                continue
            yield path

    def _scan(
        self, run_id: str
    ) -> tuple[list[MemoryNote], list[dict[str, str]], int]:
        notes: list[MemoryNote] = []
        errors: list[dict[str, str]] = []
        skipped_reparse = 0
        for path in self._iter_paths():
            try:
                note, _parsed = load_memory_note(path, self.vault_root)
            except (OSError, ValueError) as exc:
                relative = path.relative_to(self.vault_root).as_posix()
                errors.append(
                    {
                        "path": relative,
                        "type": "read_error",
                        "message": str(exc),
                        "hash": "",
                    }
                )
                continue
            note.indexed_at = _now()
            if note.parser_error:
                errors.append(
                    {
                        "path": note.path,
                        "type": "parser_error",
                        "message": note.parser_error,
                        "hash": note.content_hash,
                    }
                )
            notes.append(note)

        # rglob may omit reparse targets depending on platform. Count direct
        # entries only for an actionable, privacy-safe warning.
        for child in self.vault_root.iterdir():
            if _is_reparse_point(child):
                skipped_reparse += 1
                errors.append(
                    {
                        "path": child.name,
                        "type": "reparse_point",
                        "message": "symlink or junction was not indexed",
                        "hash": "",
                    }
                )
        return notes, errors, skipped_reparse

    def rebuild(self) -> IndexReport:
        """Fully reconstruct the index from Markdown."""

        return self._index(mode="rebuild", rebuild=True)

    def sync(self) -> IndexReport:
        """Hash-scan the vault and atomically apply incremental changes."""

        return self._index(mode="incremental", rebuild=False)

    def _index(self, *, mode: str, rebuild: bool) -> IndexReport:
        started_at = _now()
        run_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO memory_index_runs
                    (run_id, mode, started_at, status)
                VALUES (?, ?, ?, 'running')
                """,
                (run_id, mode, started_at),
            )
        try:
            scanned_notes, scan_errors, skipped_reparse = self._scan(run_id)
            prepared, duplicate_ids, duplicate_contents, conflicts = (
                self._prepare_notes(scanned_notes, scan_errors)
            )
            existing_rows = self._conn.execute(
                "SELECT note_id, path, content_hash, indexed_at FROM memory_notes"
            ).fetchall()
            existing = {row["note_id"]: row for row in existing_rows}
            current_ids = {note.note_id for note in prepared}
            created = modified = moved = unchanged = 0
            for note in prepared:
                previous = existing.get(note.note_id)
                if previous is None:
                    created += 1
                    continue
                same_path = previous["path"] == note.path
                same_hash = previous["content_hash"] == note.content_hash
                if not same_path:
                    moved += 1
                if not same_hash:
                    modified += 1
                if same_path and same_hash:
                    unchanged += 1
                    note.indexed_at = previous["indexed_at"]
            deleted_ids = set(existing) - current_ids

            self._apply_index(
                prepared,
                scan_errors,
                run_id=run_id,
                now=_now(),
                rebuild=rebuild,
                existing=existing,
                deleted_ids=deleted_ids,
            )
            completed_at = _now()
            report = IndexReport(
                run_id=run_id,
                mode=mode,
                started_at=started_at,
                completed_at=completed_at,
                scanned=len(scanned_notes),
                indexed=len(prepared),
                created=created,
                modified=modified,
                moved=moved,
                deleted=len(deleted_ids),
                unchanged=unchanged,
                parser_errors=sum(
                    1 for error in scan_errors if error["type"] == "parser_error"
                ),
                duplicate_ids=duplicate_ids,
                duplicate_contents=duplicate_contents,
                conflicts=conflicts,
                warnings=(
                    (f"{skipped_reparse} reparse point(s) skipped",)
                    if skipped_reparse
                    else ()
                ),
            )
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    UPDATE memory_index_runs
                    SET completed_at=?, status='succeeded', scanned=?, indexed=?,
                        parser_errors=?, report=?
                    WHERE run_id=?
                    """,
                    (
                        completed_at,
                        report.scanned,
                        report.indexed,
                        report.parser_errors,
                        json.dumps(_report_dict(report), sort_keys=True),
                        run_id,
                    ),
                )
            self._last_error = None
            return report
        except Exception as exc:
            self._last_error = str(exc)
            with self._lock, self._conn:
                self._conn.execute(
                    """
                    UPDATE memory_index_runs
                    SET completed_at=?, status='failed', error=?
                    WHERE run_id=?
                    """,
                    (_now(), str(exc), run_id),
                )
            raise

    def _prepare_notes(
        self,
        notes: list[MemoryNote],
        errors: list[dict[str, str]],
    ) -> tuple[list[MemoryNote], int, int, int]:
        by_id: dict[str, list[MemoryNote]] = defaultdict(list)
        for note in notes:
            by_id[note.note_id].append(note)

        prepared: list[MemoryNote] = []
        duplicate_ids = 0
        for note_id, group in sorted(by_id.items()):
            if len(group) == 1:
                prepared.append(group[0])
                continue
            duplicate_ids += 1
            canonical = sorted(group, key=lambda item: item.path)[0]
            canonical.conflict_state = ConflictState.CONFIRMED_CONFLICT
            prepared.append(canonical)
            paths = ", ".join(sorted(note.path for note in group))
            for duplicate in sorted(group, key=lambda item: item.path)[1:]:
                errors.append(
                    {
                        "path": duplicate.path,
                        "type": "duplicate_id",
                        "message": f"duplicate note_id {note_id}; also at {paths}",
                        "hash": duplicate.content_hash,
                    }
                )

        body_groups: dict[str, list[MemoryNote]] = defaultdict(list)
        for note in prepared:
            if note.body.strip():
                body_groups[_body_hash(note.body)].append(note)
        duplicate_contents = 0
        for group in body_groups.values():
            if len(group) < 2:
                continue
            duplicate_contents += 1
            for note in group:
                if note.conflict_state is ConflictState.NONE:
                    note.conflict_state = ConflictState.DUPLICATE

        conflict_groups: dict[str, list[MemoryNote]] = defaultdict(list)
        for note in prepared:
            conflict_key = str(note.raw_frontmatter.get("conflict_key") or "").strip()
            if conflict_key:
                conflict_groups[conflict_key.casefold()].append(note)
        conflicts = 0
        for group in conflict_groups.values():
            bodies = {_body_hash(note.body) for note in group}
            if len(group) > 1 and len(bodies) > 1:
                conflicts += 1
                for note in group:
                    note.conflict_state = ConflictState.CONFIRMED_CONFLICT
        return prepared, duplicate_ids, duplicate_contents, conflicts

    def _apply_index(
        self,
        notes: list[MemoryNote],
        errors: list[dict[str, str]],
        *,
        run_id: str,
        now: str,
        rebuild: bool,
        existing: Mapping[str, sqlite3.Row],
        deleted_ids: set[str],
    ) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if rebuild:
                    self._conn.execute("DELETE FROM memory_fts")
                    self._conn.execute("DELETE FROM memory_links")
                    self._conn.execute("DELETE FROM memory_tags")
                    self._conn.execute("DELETE FROM memory_relations")
                    self._conn.execute("DELETE FROM memory_notes")
                else:
                    for note_id in deleted_ids:
                        self._conn.execute(
                            "DELETE FROM memory_fts WHERE note_id=?", (note_id,)
                        )
                        self._conn.execute(
                            "DELETE FROM memory_notes WHERE note_id=?", (note_id,)
                        )

                self._conn.execute("UPDATE memory_note_paths SET active=0")
                for note in notes:
                    changed = rebuild
                    previous = existing.get(note.note_id)
                    if previous is None:
                        changed = True
                    elif (
                        previous["path"] != note.path
                        or previous["content_hash"] != note.content_hash
                    ):
                        changed = True
                    self._upsert_note(note)
                    self._conn.execute(
                        """
                        INSERT INTO memory_note_paths
                            (note_id, path, first_seen, last_seen, active)
                        VALUES (?, ?, ?, ?, 1)
                        ON CONFLICT(note_id, path) DO UPDATE SET
                            last_seen=excluded.last_seen,
                            active=1
                        """,
                        (note.note_id, note.path, now, now),
                    )
                    if changed:
                        self._conn.execute(
                            "DELETE FROM memory_fts WHERE note_id=?", (note.note_id,)
                        )
                        if not note.parser_error:
                            self._insert_fts(note)
                        self._conn.execute(
                            "DELETE FROM memory_tags WHERE note_id=?", (note.note_id,)
                        )
                        self._conn.executemany(
                            "INSERT INTO memory_tags (note_id, tag) VALUES (?, ?)",
                            [(note.note_id, tag) for tag in note.tags],
                        )

                self._conn.execute("DELETE FROM memory_links")
                self._conn.execute("DELETE FROM memory_relations")
                self._rebuild_links(notes)
                self._rebuild_relations(notes)
                self._conn.execute("DELETE FROM memory_index_errors")
                for error in errors:
                    error_id = _stable_digest(
                        error["path"], error["type"], error["message"], run_id
                    )
                    self._conn.execute(
                        """
                        INSERT INTO memory_index_errors
                            (error_id, path, error_type, message, content_hash,
                             run_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            error_id,
                            error["path"],
                            error["type"],
                            error["message"],
                            error["hash"] or None,
                            run_id,
                            now,
                        ),
                    )
                self._replace_generated_conflicts(notes, now)
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _upsert_note(self, note: MemoryNote) -> None:
        self._conn.execute(
            """
            INSERT INTO memory_notes (
                note_id, identity_kind, path, title, note_type, status, scope,
                project, source, source_task_id, source_session_id, created_at,
                updated_at, content_hash, body_hash, frontmatter_version, body,
                body_start_line, aliases, tags, folder_relations, archived,
                conflict_state, modified_ns, size_bytes, indexed_at,
                index_status, parser_error, raw_frontmatter
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(note_id) DO UPDATE SET
                identity_kind=excluded.identity_kind,
                path=excluded.path,
                title=excluded.title,
                note_type=excluded.note_type,
                status=excluded.status,
                scope=excluded.scope,
                project=excluded.project,
                source=excluded.source,
                source_task_id=excluded.source_task_id,
                source_session_id=excluded.source_session_id,
                created_at=excluded.created_at,
                updated_at=excluded.updated_at,
                content_hash=excluded.content_hash,
                body_hash=excluded.body_hash,
                frontmatter_version=excluded.frontmatter_version,
                body=excluded.body,
                body_start_line=excluded.body_start_line,
                aliases=excluded.aliases,
                tags=excluded.tags,
                folder_relations=excluded.folder_relations,
                archived=excluded.archived,
                conflict_state=excluded.conflict_state,
                modified_ns=excluded.modified_ns,
                size_bytes=excluded.size_bytes,
                indexed_at=excluded.indexed_at,
                index_status=excluded.index_status,
                parser_error=excluded.parser_error,
                raw_frontmatter=excluded.raw_frontmatter
            """,
            (
                note.note_id,
                note.identity_kind.value,
                note.path,
                note.title,
                note.note_type,
                note.status,
                note.scope,
                note.project,
                note.source,
                note.source_task_id,
                note.source_session_id,
                note.created_at,
                note.updated_at,
                note.content_hash,
                _body_hash(note.body),
                note.frontmatter_version,
                note.body,
                note.body_start_line,
                json.dumps(note.aliases, ensure_ascii=False),
                json.dumps(note.tags, ensure_ascii=False),
                json.dumps(note.folder_relations, ensure_ascii=False),
                int(note.archived),
                note.conflict_state.value,
                note.modified_ns,
                note.size_bytes,
                note.indexed_at or _now(),
                "error" if note.parser_error else "indexed",
                note.parser_error,
                json.dumps(note.raw_frontmatter, ensure_ascii=False, sort_keys=True),
            ),
        )

    def _insert_fts(self, note: MemoryNote) -> None:
        self._conn.execute(
            """
            INSERT INTO memory_fts
                (note_id, title, aliases, body, tags, project)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                note.note_id,
                note.title,
                " ".join(note.aliases),
                note.body,
                " ".join(note.tags),
                note.project or "",
            ),
        )

    def _rebuild_links(self, notes: list[MemoryNote]) -> None:
        lookup: dict[str, set[str]] = defaultdict(set)
        for note in notes:
            lookup[note.title.casefold()].add(note.note_id)
            lookup[Path(note.path).stem.casefold()].add(note.note_id)
            lookup[note.path.casefold()].add(note.note_id)
            lookup[Path(note.path).with_suffix("").as_posix().casefold()].add(
                note.note_id
            )
            for alias in note.aliases:
                lookup[alias.casefold()].add(note.note_id)

        for note in notes:
            for ordinal, raw in enumerate(note.outgoing_links):
                target_title, heading, alias = _link_parts(raw)
                matches = sorted(lookup.get(target_title.casefold(), set()))
                target_id = matches[0] if len(matches) == 1 else None
                link_id = _stable_digest(note.note_id, raw, str(ordinal))
                self._conn.execute(
                    """
                    INSERT INTO memory_links (
                        link_id, source_note_id, target_note_id, raw_target,
                        target_title, heading, alias, resolved, ambiguous
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        link_id,
                        note.note_id,
                        target_id,
                        raw,
                        target_title,
                        heading,
                        alias,
                        int(target_id is not None),
                        int(len(matches) > 1),
                    ),
                )

    def _rebuild_relations(self, notes: list[MemoryNote]) -> None:
        for note in notes:
            for folder in note.folder_relations:
                relation_id = _stable_digest(note.note_id, "folder", folder)
                self._conn.execute(
                    """
                    INSERT INTO memory_relations (
                        relation_id, source_node_id, target_node_id,
                        relation_type, metadata
                    ) VALUES (?, ?, ?, 'folder', '{}')
                    """,
                    (relation_id, note.note_id, f"folder:{folder}"),
                )
            if note.project:
                relation_id = _stable_digest(note.note_id, "project", note.project)
                self._conn.execute(
                    """
                    INSERT INTO memory_relations (
                        relation_id, source_node_id, target_node_id,
                        relation_type, metadata
                    ) VALUES (?, ?, ?, 'project', '{}')
                    """,
                    (relation_id, note.note_id, f"project:{note.project}"),
                )
            if note.source_task_id:
                relation_id = _stable_digest(
                    note.note_id, "task", note.source_task_id
                )
                self._conn.execute(
                    """
                    INSERT INTO memory_relations (
                        relation_id, source_node_id, target_node_id,
                        relation_type, metadata
                    ) VALUES (?, ?, ?, 'task_source', '{}')
                    """,
                    (relation_id, note.note_id, f"task:{note.source_task_id}"),
                )
        rows = self._conn.execute(
            """
            SELECT link_id, source_note_id, target_note_id, heading, alias
            FROM memory_links WHERE target_note_id IS NOT NULL
            """
        ).fetchall()
        for row in rows:
            self._conn.execute(
                """
                INSERT INTO memory_relations (
                    relation_id, source_node_id, target_node_id,
                    relation_type, metadata
                ) VALUES (?, ?, ?, 'wikilink', ?)
                """,
                (
                    f"link:{row['link_id']}",
                    row["source_note_id"],
                    row["target_note_id"],
                    json.dumps(
                        {"heading": row["heading"], "alias": row["alias"]},
                        ensure_ascii=False,
                    ),
                ),
            )

    def _replace_generated_conflicts(
        self, notes: list[MemoryNote], timestamp: str
    ) -> None:
        self._conn.execute(
            """
            DELETE FROM memory_conflicts
            WHERE resolution IS NULL AND conflict_type LIKE 'index.%'
            """
        )
        by_body: dict[str, list[MemoryNote]] = defaultdict(list)
        by_key: dict[str, list[MemoryNote]] = defaultdict(list)
        for note in notes:
            if note.body.strip():
                by_body[_body_hash(note.body)].append(note)
            key = str(note.raw_frontmatter.get("conflict_key") or "").strip()
            if key:
                by_key[key.casefold()].append(note)
        for body_hash, group in by_body.items():
            if len(group) > 1:
                self._insert_conflict(
                    "index.duplicate_content",
                    ConflictState.DUPLICATE,
                    group,
                    f"{len(group)} notes have identical normalized content",
                    timestamp,
                    {"body_hash": body_hash},
                )
        for key, group in by_key.items():
            if len(group) > 1 and len({_body_hash(item.body) for item in group}) > 1:
                self._insert_conflict(
                    "index.conflicting_fact",
                    ConflictState.CONFIRMED_CONFLICT,
                    group,
                    f"notes with conflict key {key!r} disagree",
                    timestamp,
                    {"conflict_key": key},
                )

    def _insert_conflict(
        self,
        conflict_type: str,
        state: ConflictState,
        notes: Iterable[MemoryNote],
        summary: str,
        timestamp: str,
        metadata: Mapping[str, Any],
    ) -> None:
        group = sorted(notes, key=lambda note: note.note_id)
        note_ids = [note.note_id for note in group]
        conflict_id = _stable_digest(conflict_type, *note_ids)
        self._conn.execute(
            """
            INSERT INTO memory_conflicts (
                conflict_id, conflict_type, state, note_ids, summary, metadata,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conflict_id) DO UPDATE SET
                state=excluded.state,
                note_ids=excluded.note_ids,
                summary=excluded.summary,
                metadata=excluded.metadata,
                updated_at=excluded.updated_at
            """,
            (
                conflict_id,
                conflict_type,
                state.value,
                json.dumps(note_ids),
                summary,
                json.dumps(metadata, sort_keys=True),
                timestamp,
                timestamp,
            ),
        )

    def get_note(self, note_id: str) -> MemoryNote | None:
        row = self._conn.execute(
            "SELECT * FROM memory_notes WHERE note_id=?", (note_id,)
        ).fetchone()
        if row is None:
            return None
        outgoing = self._conn.execute(
            """
            SELECT raw_target FROM memory_links
            WHERE source_note_id=? ORDER BY link_id
            """,
            (note_id,),
        ).fetchall()
        backlinks = self._conn.execute(
            """
            SELECT source_note_id FROM memory_links
            WHERE target_note_id=? ORDER BY source_note_id
            """,
            (note_id,),
        ).fetchall()
        note = _note_from_row(row)
        return replace(
            note,
            outgoing_links=tuple(item["raw_target"] for item in outgoing),
            backlinks=tuple(item["source_note_id"] for item in backlinks),
        )

    def get_note_by_path(self, relative_path: str) -> MemoryNote | None:
        row = self._conn.execute(
            "SELECT note_id FROM memory_notes WHERE path=?", (relative_path,)
        ).fetchone()
        return self.get_note(row["note_id"]) if row else None

    def list_notes(self, *, limit: int = 1000) -> list[MemoryNote]:
        rows = self._conn.execute(
            "SELECT note_id FROM memory_notes ORDER BY path LIMIT ?", (limit,)
        ).fetchall()
        return [
            note
            for row in rows
            if (note := self.get_note(row["note_id"])) is not None
        ]

    def list_errors(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT error_id, path, error_type, message, content_hash, run_id,
                   created_at
            FROM memory_index_errors ORDER BY path LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def note_links(self, note_id: str) -> dict[str, list[dict[str, Any]]]:
        outgoing = self._conn.execute(
            """
            SELECT link_id, source_note_id, target_note_id, raw_target,
                   target_title, heading, alias, resolved, ambiguous
            FROM memory_links WHERE source_note_id=? ORDER BY link_id
            """,
            (note_id,),
        ).fetchall()
        incoming = self._conn.execute(
            """
            SELECT l.link_id, l.source_note_id, n.path AS source_path,
                   n.title AS source_title, l.heading, l.alias
            FROM memory_links l
            JOIN memory_notes n ON n.note_id=l.source_note_id
            WHERE l.target_note_id=? ORDER BY n.path, l.link_id
            """,
            (note_id,),
        ).fetchall()
        return {
            "outgoing": [
                {
                    **dict(row),
                    "resolved": bool(row["resolved"]),
                    "ambiguous": bool(row["ambiguous"]),
                }
                for row in outgoing
            ],
            "backlinks": [dict(row) for row in incoming],
        }

    def graph(self, *, limit: int = 1000) -> dict[str, Any]:
        note_rows = self._conn.execute(
            """
            SELECT note_id, path, title, note_type, status, scope, project,
                   archived, conflict_state
            FROM memory_notes ORDER BY path LIMIT ?
            """,
            (limit,),
        ).fetchall()
        note_ids = {row["note_id"] for row in note_rows}
        relation_rows = self._conn.execute(
            """
            SELECT relation_id, source_node_id, target_node_id, relation_type,
                   metadata
            FROM memory_relations ORDER BY relation_id
            """
        ).fetchall()
        edges = [
            {
                "id": row["relation_id"],
                "source": row["source_node_id"],
                "target": row["target_node_id"],
                "type": row["relation_type"],
                "metadata": json.loads(row["metadata"]),
            }
            for row in relation_rows
            if row["source_node_id"] in note_ids
        ]
        return {
            "nodes": [
                {
                    "id": row["note_id"],
                    "path": row["path"],
                    "title": row["title"],
                    "type": row["note_type"],
                    "status": row["status"],
                    "scope": row["scope"],
                    "project": row["project"],
                    "archived": bool(row["archived"]),
                    "conflict_state": row["conflict_state"],
                }
                for row in note_rows
            ],
            "edges": edges,
        }

    def health(self) -> MemoryHealth:
        note_count = int(
            self._conn.execute("SELECT COUNT(*) FROM memory_notes").fetchone()[0]
        )
        error_count = int(
            self._conn.execute(
                "SELECT COUNT(*) FROM memory_index_errors"
            ).fetchone()[0]
        )
        last = self._conn.execute(
            """
            SELECT completed_at FROM memory_index_runs
            WHERE status='succeeded' ORDER BY completed_at DESC LIMIT 1
            """
        ).fetchone()
        candidates = int(
            self._conn.execute(
                """
                SELECT COUNT(*) FROM memory_candidates
                WHERE status IN ('pending_approval', 'approved')
                """
            ).fetchone()[0]
        )
        conflicts = int(
            self._conn.execute(
                """
                SELECT COUNT(*) FROM memory_conflicts
                WHERE resolved_at IS NULL
                """
            ).fetchone()[0]
        )
        return MemoryHealth(
            vault_configured=True,
            vault_reachable=self.vault_root.is_dir(),
            mode=self.mode,
            index_available=not self._closed,
            fts5_available=self._fts5_available,
            note_count=note_count,
            parser_error_count=error_count,
            last_successful_index=last["completed_at"] if last else None,
            last_error=self._last_error,
            embeddings_enabled=self.embeddings_enabled,
            retrieval_mode="fts5_bm25",
            open_candidates=candidates,
            open_conflicts=conflicts,
        )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __enter__(self) -> VaultIndex:
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()


def _note_from_row(row: sqlite3.Row) -> MemoryNote:
    return MemoryNote(
        note_id=row["note_id"],
        path=row["path"],
        title=row["title"],
        note_type=row["note_type"],
        status=row["status"],
        scope=row["scope"],
        project=row["project"],
        tags=tuple(json.loads(row["tags"])),
        aliases=tuple(json.loads(row["aliases"])),
        source=row["source"],
        source_task_id=row["source_task_id"],
        source_session_id=row["source_session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        content_hash=row["content_hash"],
        frontmatter_version=row["frontmatter_version"],
        body=row["body"],
        folder_relations=tuple(json.loads(row["folder_relations"])),
        archived=bool(row["archived"]),
        conflict_state=ConflictState(row["conflict_state"]),
        identity_kind=IdentityKind(row["identity_kind"]),
        indexed_at=row["indexed_at"],
        modified_ns=row["modified_ns"],
        size_bytes=row["size_bytes"],
        body_start_line=row["body_start_line"],
        raw_frontmatter=json.loads(row["raw_frontmatter"]),
        parser_error=row["parser_error"],
    )


def _report_dict(report: IndexReport) -> dict[str, Any]:
    return {
        "run_id": report.run_id,
        "mode": report.mode,
        "started_at": report.started_at,
        "completed_at": report.completed_at,
        "scanned": report.scanned,
        "indexed": report.indexed,
        "created": report.created,
        "modified": report.modified,
        "moved": report.moved,
        "deleted": report.deleted,
        "unchanged": report.unchanged,
        "parser_errors": report.parser_errors,
        "duplicate_ids": report.duplicate_ids,
        "duplicate_contents": report.duplicate_contents,
        "conflicts": report.conflicts,
        "warnings": list(report.warnings),
    }


__all__ = ["VaultIndex"]
