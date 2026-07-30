"""Round-trip YAML frontmatter and stable note identity."""

from __future__ import annotations

import copy
import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError

from openjarvis.memory.vault_models import (
    NOTE_TYPES,
    ConflictState,
    IdentityKind,
    MemoryNote,
)

_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]\n]+)\]\]")
_H1_RE = re.compile(r"^\s*#\s+(.+?)\s*$", re.MULTILINE)


def _yaml() -> YAML:
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    parser.allow_duplicate_keys = False
    parser.default_flow_style = False
    parser.width = 4096
    parser.indent(mapping=2, sequence=4, offset=2)
    return parser


@dataclass(slots=True)
class ParsedMarkdown:
    """A parsed Markdown file whose YAML can be rendered round-trip."""

    metadata: CommentedMap
    body: str
    raw_text: str
    raw_frontmatter: str
    has_frontmatter: bool
    body_start_line: int
    newline: str
    error: str | None = None


class FrontmatterError(ValueError):
    """Raised when a write would require invalid or lossy frontmatter."""


def parse_markdown(text: str) -> ParsedMarkdown:
    """Parse a Markdown document without silently correcting invalid YAML."""

    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].lstrip("\ufeff").strip() != "---":
        return ParsedMarkdown(
            metadata=CommentedMap(),
            body=text,
            raw_text=text,
            raw_frontmatter="",
            has_frontmatter=False,
            body_start_line=1,
            newline=newline,
        )

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            closing_index = index
            break
    if closing_index is None:
        return ParsedMarkdown(
            metadata=CommentedMap(),
            body=text,
            raw_text=text,
            raw_frontmatter="",
            has_frontmatter=True,
            body_start_line=1,
            newline=newline,
            error="frontmatter has no closing delimiter",
        )

    raw_frontmatter = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1 :])
    try:
        loaded = _yaml().load(raw_frontmatter)
    except YAMLError as exc:
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        return ParsedMarkdown(
            metadata=CommentedMap(),
            body=body,
            raw_text=text,
            raw_frontmatter=raw_frontmatter,
            has_frontmatter=True,
            body_start_line=closing_index + 2,
            newline=newline,
            error=f"invalid YAML frontmatter: {problem}",
        )
    if loaded is None:
        loaded = CommentedMap()
    if not isinstance(loaded, Mapping):
        return ParsedMarkdown(
            metadata=CommentedMap(),
            body=body,
            raw_text=text,
            raw_frontmatter=raw_frontmatter,
            has_frontmatter=True,
            body_start_line=closing_index + 2,
            newline=newline,
            error="frontmatter root must be a YAML mapping",
        )
    if not isinstance(loaded, CommentedMap):
        loaded = CommentedMap(loaded)
    return ParsedMarkdown(
        metadata=loaded,
        body=body,
        raw_text=text,
        raw_frontmatter=raw_frontmatter,
        has_frontmatter=True,
        body_start_line=closing_index + 2,
        newline=newline,
    )


def read_markdown(path: Path) -> tuple[ParsedMarkdown, str, int]:
    """Read one UTF-8 Markdown file and return parse, SHA-256, and byte size."""

    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        parsed = ParsedMarkdown(
            metadata=CommentedMap(),
            body="",
            raw_text="",
            raw_frontmatter="",
            has_frontmatter=False,
            body_start_line=1,
            newline="\n",
            error=f"invalid UTF-8 at byte {exc.start}",
        )
        return parsed, digest, len(payload)
    return parse_markdown(text), digest, len(payload)


def extract_wikilinks(body: str) -> tuple[str, ...]:
    """Return raw, ordered Wikilink targets without embeds."""

    return tuple(match.group(1).strip() for match in _WIKILINK_RE.finditer(body))


def provisional_note_id(relative_path: str, content_hash: str) -> str:
    """Create a clearly non-UUID, deterministic identity for read-only legacy."""

    seed = f"{relative_path.casefold()}\0{content_hash}".encode("utf-8")
    return f"provisional:{hashlib.sha256(seed).hexdigest()[:40]}"


def _string_list(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, Iterable) or isinstance(value, Mapping):
        return (str(value),)
    output: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item).strip()
        if text and text.casefold() not in seen:
            seen.add(text.casefold())
            output.append(text)
    return tuple(output)


def _iso_value(value: Any) -> tuple[str | None, str | None]:
    if value in (None, ""):
        return None, None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    else:
        text = str(value).strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text, f"invalid ISO-8601 datetime: {text}"
    if parsed.tzinfo is None:
        return parsed.isoformat(), f"datetime lacks timezone: {parsed.isoformat()}"
    return parsed.isoformat(), None


def _title(metadata: Mapping[str, Any], body: str, path: Path) -> str:
    configured = str(metadata.get("title") or "").strip()
    if configured:
        return configured
    heading = _H1_RE.search(body)
    if heading:
        return heading.group(1).strip()
    return path.stem


def _folders(relative_path: Path) -> tuple[str, ...]:
    parents: list[str] = []
    current = relative_path.parent
    while current != Path("."):
        parents.append(current.as_posix())
        current = current.parent
    return tuple(reversed(parents))


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def load_memory_note(path: Path, vault_root: Path) -> tuple[MemoryNote, ParsedMarkdown]:
    """Load one note while preserving legacy files and invalid YAML read-only."""

    root = vault_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise FrontmatterError("note is outside the configured vault root") from exc

    parsed, content_hash, size_bytes = read_markdown(resolved)
    stat = resolved.stat()
    metadata = parsed.metadata
    raw_id = str(metadata.get("id") or "").strip()
    identity_kind = IdentityKind.STABLE if raw_id else IdentityKind.PROVISIONAL
    note_id = raw_id or provisional_note_id(relative.as_posix(), content_hash)

    validation_errors: list[str] = []
    conflict_state = ConflictState.NONE
    if parsed.error:
        validation_errors.append(parsed.error)
        conflict_state = ConflictState.INVALID_SCHEMA
    if raw_id:
        try:
            uuid.UUID(raw_id)
        except ValueError:
            validation_errors.append("frontmatter id is not a valid UUID")
            conflict_state = ConflictState.INVALID_SCHEMA

    raw_version = metadata.get("schema_version")
    version: int | None = None
    if raw_version not in (None, ""):
        try:
            version = int(raw_version)
        except (TypeError, ValueError):
            validation_errors.append("schema_version must be an integer")
            conflict_state = ConflictState.INVALID_SCHEMA

    note_type = str(metadata.get("type") or "capture").strip().lower()
    if note_type not in NOTE_TYPES:
        validation_errors.append(f"unsupported note type: {note_type}")
        conflict_state = ConflictState.INVALID_SCHEMA

    created_at, created_error = _iso_value(metadata.get("created_at"))
    updated_at, updated_error = _iso_value(metadata.get("updated_at"))
    for error in (created_error, updated_error):
        if error:
            validation_errors.append(error)
            if identity_kind is IdentityKind.STABLE:
                conflict_state = ConflictState.INVALID_SCHEMA

    status = str(metadata.get("status") or "active").strip().lower()
    relative_parts = {part.casefold() for part in relative.parts[:-1]}
    archived = bool(metadata.get("archived", False)) or status == "archived"
    archived = archived or bool(relative_parts & {"archive", "archived", "archiv"})

    body = parsed.body if not parsed.error else parsed.body or parsed.raw_text
    parser_error = "; ".join(validation_errors) or None
    note = MemoryNote(
        note_id=note_id,
        path=relative.as_posix(),
        title=_title(metadata, body, relative),
        note_type=note_type,
        status=status,
        scope=str(metadata.get("scope") or "personal").strip().lower(),
        project=(
            str(metadata.get("project")).strip()
            if metadata.get("project") not in (None, "")
            else None
        ),
        tags=_string_list(metadata.get("tags")),
        aliases=_string_list(metadata.get("aliases")),
        source=str(metadata.get("source") or "legacy").strip().lower(),
        source_task_id=(
            str(metadata.get("source_task_id")).strip()
            if metadata.get("source_task_id") not in (None, "")
            else None
        ),
        source_session_id=(
            str(metadata.get("source_session_id")).strip()
            if metadata.get("source_session_id") not in (None, "")
            else None
        ),
        created_at=created_at,
        updated_at=updated_at,
        content_hash=content_hash,
        frontmatter_version=version,
        body=body,
        outgoing_links=extract_wikilinks(body),
        folder_relations=_folders(relative),
        archived=archived,
        conflict_state=conflict_state,
        identity_kind=identity_kind,
        modified_ns=stat.st_mtime_ns,
        size_bytes=size_bytes,
        raw_frontmatter=_json_safe(metadata),
        parser_error=parser_error,
        body_start_line=parsed.body_start_line,
    )
    return note, parsed


def render_with_updates(
    parsed: ParsedMarkdown,
    updates: Mapping[str, Any],
    *,
    body: str | None = None,
) -> str:
    """Render updates while retaining unknown keys and YAML comments."""

    if parsed.error:
        raise FrontmatterError(parsed.error)
    metadata = copy.deepcopy(parsed.metadata)
    for key, value in updates.items():
        metadata[key] = value
    buffer = io.StringIO()
    _yaml().dump(metadata, buffer)
    rendered = f"---\n{buffer.getvalue()}---\n{parsed.body if body is None else body}"
    if parsed.newline != "\n":
        rendered = rendered.replace("\n", parsed.newline)
    return rendered


def render_canonical_markdown(
    *,
    note_id: str,
    note_type: str,
    status: str = "active",
    scope: str = "personal",
    project: str | None = None,
    tags: Iterable[str] = (),
    aliases: Iterable[str] = (),
    source: str = "user",
    source_task_id: str | None = None,
    source_session_id: str | None = None,
    created_at: str,
    updated_at: str,
    body: str,
) -> str:
    """Render a new schema-v1 note in a deterministic field order."""

    if note_type not in NOTE_TYPES:
        raise FrontmatterError(f"unsupported note type: {note_type}")
    try:
        uuid.UUID(note_id)
    except ValueError as exc:
        raise FrontmatterError("note_id must be a UUID") from exc
    metadata = CommentedMap(
        [
            ("id", note_id),
            ("schema_version", 1),
            ("type", note_type),
            ("status", status),
            ("scope", scope),
            ("project", project),
            ("tags", list(tags)),
            ("aliases", list(aliases)),
            ("source", source),
            ("source_task_id", source_task_id),
            ("source_session_id", source_session_id),
            ("created_at", created_at),
            ("updated_at", updated_at),
        ]
    )
    buffer = io.StringIO()
    _yaml().dump(metadata, buffer)
    normalized_body = body.rstrip() + "\n"
    return f"---\n{buffer.getvalue()}---\n{normalized_body}"


__all__ = [
    "FrontmatterError",
    "ParsedMarkdown",
    "extract_wikilinks",
    "load_memory_note",
    "parse_markdown",
    "provisional_note_id",
    "read_markdown",
    "render_canonical_markdown",
    "render_with_updates",
]
