"""Deterministic, isolated Phase 8B Vault schema-conversion pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import unicodedata
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from openjarvis.memory.frontmatter import parse_markdown
from openjarvis.memory.vault_index import VaultIndex
from openjarvis.migration.backup import load_manifest, verify_manifest


class VaultSchemaPilotError(RuntimeError):
    """Raised when the isolated schema pilot cannot satisfy a safety invariant."""


MAPPING_VERSION = "openjarvis-vault-schema-migration-v1"
NAMESPACE_UUID = uuid.UUID("4898f42f-c416-5ea1-9e0e-1bafd4d2e206")
MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
KNOWN_ID_REFERENCE_FIELDS = frozenset(
    {
        "candidate_id",
        "conflict_id",
        "conflicts_with",
        "depends_on",
        "memory_id",
        "note_id",
        "note_ids",
        "parent_id",
        "related_ids",
        "replaces",
        "source_id",
        "source_refs",
        "target_id",
    }
)
_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*)[ \t]*:")
_WIKILINK_RE = re.compile(r"(?<!!)\[\[([^\]\r\n]+)\]\]")
_MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]\r\n]*\]\(([^)\r\n]+)\)")
_CODE_BLOCK_RE = re.compile(r"(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$")


@dataclass(frozen=True, slots=True)
class FileManifestEntry:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class MappingEntry:
    mapping_version: str
    namespace_uuid: str
    relative_path: str
    before_sha256: str
    source_id_state: str
    old_id: str | None
    new_uuid: str
    legacy_id_written: bool
    schema_version_written: bool
    detected_reference_count: int
    mapping_hash: str


@dataclass(frozen=True, slots=True)
class MappingTable:
    mapping_version: str
    namespace_uuid: str
    entries: tuple[MappingEntry, ...]
    mapping_sha256: str


@dataclass(frozen=True, slots=True)
class ReferenceFileReport:
    path: str
    structured_id_references: int
    unknown_frontmatter_references: int
    wikilink_references: int
    markdown_link_references: int
    free_text_references: int
    code_block_references: int
    body_sha256: str


@dataclass(frozen=True, slots=True)
class PatchResult:
    path: str
    before_sha256: str
    after_sha256: str
    before_size: int
    after_size: int
    body_sha256: str
    id_changed: bool
    legacy_id_written: bool
    schema_version_written: bool
    structured_references_updated: int
    payload: bytes


@dataclass(frozen=True, slots=True)
class ApplyResult:
    changed: int
    unchanged: int
    after_hashes: Mapping[str, str]


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def _canonical_jsonl(values: Iterable[Any]) -> bytes:
    chunks: list[bytes] = []
    for value in values:
        payload = asdict(value) if hasattr(value, "__dataclass_fields__") else value
        chunks.append(_canonical_json(payload))
    return b"".join(chunks)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _safe_relative(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value)
    relative = PurePosixPath(normalized)
    if (
        not normalized
        or normalized == "."
        or "\\" in normalized
        or relative.as_posix() != normalized
        or relative.is_absolute()
        or any(part in {"", ".", ".."} or ":" in part for part in relative.parts)
    ):
        raise VaultSchemaPilotError("mapping path must be canonical and relative")
    return relative.as_posix()


def normalize_legacy_id(value: str) -> str:
    """Normalize a legacy ID exactly as approved for the UUIDv5 seed."""

    normalized = unicodedata.normalize("NFC", value.strip())
    if not normalized:
        raise VaultSchemaPilotError("legacy ID is empty after normalization")
    if "\r" in normalized or "\n" in normalized:
        raise VaultSchemaPilotError("legacy ID must not contain line breaks")
    return normalized


def uuid_for_legacy_id(value: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE_UUID, f"legacy-id:{normalize_legacy_id(value)}")


def uuid_for_missing_id(relative_path: str, before_sha256: str) -> uuid.UUID:
    relative = _safe_relative(relative_path)
    if not re.fullmatch(r"[0-9a-f]{64}", before_sha256):
        raise VaultSchemaPilotError("before SHA-256 is invalid")
    return uuid.uuid5(
        NAMESPACE_UUID,
        f"missing-id:{relative}:{before_sha256}",
    )


def _is_reparse(path: Path) -> bool:
    metadata = os.lstat(path)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & reparse_flag
    )


def _safe_tree(root: Path) -> None:
    if not root.is_dir() or _is_reparse(root):
        raise VaultSchemaPilotError("pilot root must be an existing real directory")
    pending = [root]
    while pending:
        current = pending.pop()
        with os.scandir(current) as iterator:
            for child in iterator:
                path = Path(child.path)
                if _is_reparse(path):
                    raise VaultSchemaPilotError("pilot tree contains a reparse point")
                if child.is_dir(follow_symlinks=False):
                    pending.append(path)
                elif not child.is_file(follow_symlinks=False):
                    raise VaultSchemaPilotError("pilot tree contains a special file")


def build_manifest(root: Path) -> tuple[tuple[FileManifestEntry, ...], str]:
    """Hash every file in a safe tree using canonical relative paths."""

    _safe_tree(root)
    entries: list[FileManifestEntry] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = _safe_relative(path.relative_to(root).as_posix())
        payload = path.read_bytes()
        entries.append(
            FileManifestEntry(
                path=relative,
                size=len(payload),
                sha256=_sha256(payload),
            )
        )
    ordered = tuple(sorted(entries, key=lambda item: item.path))
    return ordered, _sha256(_canonical_jsonl(ordered))


def _decode_markdown(payload: bytes) -> tuple[str, bool]:
    has_bom = payload.startswith(b"\xef\xbb\xbf")
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise VaultSchemaPilotError("Markdown is not valid UTF-8") from error
    return text, has_bom


def _body_bytes(payload: bytes) -> bytes:
    raw = payload[3:] if payload.startswith(b"\xef\xbb\xbf") else payload
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != b"---":
        return raw
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {b"---", b"..."}:
            return b"".join(lines[index + 1 :])
    raise VaultSchemaPilotError("frontmatter has no closing delimiter")


def _markdown_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.casefold() in MARKDOWN_SUFFIXES
        )
    )


def _valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value.strip())
    except (ValueError, AttributeError):
        return False
    return True


def _iter_scalar_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from _iter_scalar_strings(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _iter_scalar_strings(item)


def _structured_reference_counts(
    root: Path,
    old_ids: set[str],
) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in _markdown_files(root):
        text, _bom = _decode_markdown(path.read_bytes())
        parsed = parse_markdown(text)
        if parsed.error:
            raise VaultSchemaPilotError(parsed.error)
        for key, value in parsed.metadata.items():
            if str(key).casefold() not in KNOWN_ID_REFERENCE_FIELDS:
                continue
            for item in _iter_scalar_strings(value):
                if item in old_ids:
                    counts[item] += 1
    return counts


def _entry_hash_payload(entry: MappingEntry | Mapping[str, Any]) -> dict[str, Any]:
    payload = asdict(entry) if isinstance(entry, MappingEntry) else dict(entry)
    payload.pop("mapping_hash", None)
    return payload


def _with_mapping_hash(payload: dict[str, Any]) -> MappingEntry:
    mapping_hash = _sha256(_canonical_json(payload))
    return MappingEntry(**payload, mapping_hash=mapping_hash)


def build_mapping(root: Path) -> MappingTable:
    """Build the immutable deterministic mapping without modifying *root*."""

    _safe_tree(root)
    preliminary: list[dict[str, Any]] = []
    existing_valid: set[str] = set()
    normalized_legacy_inputs: dict[str, str] = {}
    for path in _markdown_files(root):
        relative = _safe_relative(path.relative_to(root).as_posix())
        payload = path.read_bytes()
        before_sha256 = _sha256(payload)
        text, _bom = _decode_markdown(payload)
        parsed = parse_markdown(text)
        if parsed.error:
            raise VaultSchemaPilotError(f"invalid frontmatter at {relative}")
        metadata = parsed.metadata
        raw_id_value = metadata.get("id")
        old_id = str(raw_id_value) if raw_id_value not in (None, "") else None
        schema = metadata.get("schema_version")
        if schema is not None and schema != 1:
            raise VaultSchemaPilotError(
                f"conflicting schema_version at relative path: {relative}"
            )
        if old_id is not None and _valid_uuid(old_id):
            existing_valid.add(str(uuid.UUID(old_id.strip())))
            continue
        if old_id is not None:
            normalized = normalize_legacy_id(old_id)
            previous = normalized_legacy_inputs.get(normalized)
            if previous is not None and previous != old_id:
                raise VaultSchemaPilotError(
                    "distinct legacy IDs collapse under NFC normalization"
                )
            normalized_legacy_inputs[normalized] = old_id
            new_uuid = str(uuid_for_legacy_id(old_id))
            existing_legacy = metadata.get("legacy_id")
            if existing_legacy is not None and str(existing_legacy) != old_id:
                raise VaultSchemaPilotError(
                    f"conflicting legacy_id at relative path: {relative}"
                )
            state = "invalid_existing"
            legacy_written = existing_legacy is None
        else:
            new_uuid = str(uuid_for_missing_id(relative, before_sha256))
            state = "missing"
            legacy_written = False
        preliminary.append(
            {
                "mapping_version": MAPPING_VERSION,
                "namespace_uuid": str(NAMESPACE_UUID),
                "relative_path": relative,
                "before_sha256": before_sha256,
                "source_id_state": state,
                "old_id": old_id,
                "new_uuid": new_uuid,
                "legacy_id_written": legacy_written,
                "schema_version_written": schema is None,
                "detected_reference_count": 0,
            }
        )

    new_values = [item["new_uuid"] for item in preliminary]
    if len(new_values) != len(set(new_values)):
        raise VaultSchemaPilotError("deterministic UUID collision detected")
    if set(new_values) & existing_valid:
        raise VaultSchemaPilotError("new UUID overlaps an existing valid UUID")
    old_ids = {
        str(item["old_id"]) for item in preliminary if item["old_id"] is not None
    }
    reference_counts = _structured_reference_counts(root, old_ids)
    entries = tuple(
        sorted(
            (
                _with_mapping_hash(
                    {
                        **item,
                        "detected_reference_count": reference_counts.get(
                            str(item["old_id"]), 0
                        ),
                    }
                )
                for item in preliminary
            ),
            key=lambda item: item.relative_path,
        )
    )
    if any(
        entry.mapping_hash != _sha256(_canonical_json(_entry_hash_payload(entry)))
        for entry in entries
    ):
        raise VaultSchemaPilotError("mapping entry hash failed self-verification")
    table_payload = {
        "entries": [asdict(entry) for entry in entries],
        "mapping_version": MAPPING_VERSION,
        "namespace_uuid": str(NAMESPACE_UUID),
    }
    return MappingTable(
        mapping_version=MAPPING_VERSION,
        namespace_uuid=str(NAMESPACE_UUID),
        entries=entries,
        mapping_sha256=_sha256(_canonical_json(table_payload)),
    )


def mapping_to_bytes(table: MappingTable) -> bytes:
    return (
        json.dumps(
            {
                "entries": [asdict(entry) for entry in table.entries],
                "mapping_sha256": table.mapping_sha256,
                "mapping_version": table.mapping_version,
                "namespace_uuid": table.namespace_uuid,
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def _scalar_style(token: str) -> str:
    stripped = token.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] == "'":
        return "single"
    if len(stripped) >= 2 and stripped[0] == stripped[-1] == '"':
        return "double"
    return "plain"


def _render_scalar(value: str, style: str = "plain") -> str:
    if "\r" in value or "\n" in value:
        raise VaultSchemaPilotError("frontmatter scalar contains a line break")
    if style == "single":
        return "'" + value.replace("'", "''") + "'"
    if style == "double":
        return json.dumps(value, ensure_ascii=False)
    unsafe = (
        not value
        or value != value.strip()
        or value[0] in "-?:,[]{}#&*!|>'\"%@`"
        or ": " in value
        or " #" in value
    )
    return json.dumps(value, ensure_ascii=False) if unsafe else value


def _split_inline_comment(value: str) -> tuple[str, str]:
    quote: str | None = None
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if quote == '"' and character == "\\":
            escaped = True
            continue
        if quote is not None:
            if character == quote:
                quote = None
            continue
        if character in {"'", '"'}:
            quote = character
            continue
        if character == "#" and (index == 0 or value[index - 1].isspace()):
            start = index
            while start > 0 and value[start - 1] in " \t":
                start -= 1
            return value[:start], value[start:]
    return value, ""


def _replace_top_level_scalar(line: str, key: str, new_value: str) -> str:
    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    core = line[: -len(newline)] if newline else line
    match = re.match(rf"^({re.escape(key)}[ \t]*:[ \t]*)(.*)$", core)
    if not match:
        raise VaultSchemaPilotError(f"cannot minimally patch frontmatter field: {key}")
    token, comment = _split_inline_comment(match.group(2))
    style = _scalar_style(token)
    trailing = token[len(token.rstrip(" \t")) :]
    return (
        match.group(1) + _render_scalar(new_value, style) + trailing + comment + newline
    )


def _replace_reference_tokens(
    line: str, replacements: Mapping[str, str]
) -> tuple[str, int]:
    newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    core = line[: -len(newline)] if newline else line
    content, comment = _split_inline_comment(core)
    changed = 0
    for old, new in replacements.items():
        single = "'" + old.replace("'", "''") + "'"
        double = json.dumps(old, ensure_ascii=False)
        if single in content:
            count = content.count(single)
            content = content.replace(single, _render_scalar(new, "single"))
            changed += count
        if double in content:
            count = content.count(double)
            content = content.replace(double, _render_scalar(new, "double"))
            changed += count
        pattern = re.compile(
            rf"(?P<prefix>(?:^|[:\[,\-])[ \t]*){re.escape(old)}"
            rf"(?P<suffix>[ \t]*(?=$|[,\]]))"
        )
        content, count = pattern.subn(
            lambda match: (
                match.group("prefix") + _render_scalar(new) + match.group("suffix")
            ),
            content,
        )
        changed += count
    return content + comment + newline, changed


def _frontmatter_lines(payload: bytes) -> tuple[bool, bool, str, list[str], bytes]:
    text, has_bom = _decode_markdown(payload)
    newline = "\r\n" if "\r\n" in text else "\n"
    raw = payload[3:] if has_bom else payload
    raw_lines = raw.splitlines(keepends=True)
    if not raw_lines or raw_lines[0].strip() != b"---":
        return has_bom, False, newline, [], raw
    closing: int | None = None
    for index, line in enumerate(raw_lines[1:], start=1):
        if line.strip() in {b"---", b"..."}:
            closing = index
            break
    if closing is None:
        raise VaultSchemaPilotError("frontmatter has no closing delimiter")
    try:
        lines = [line.decode("utf-8") for line in raw_lines[1:closing]]
    except UnicodeDecodeError as error:
        raise VaultSchemaPilotError("frontmatter is not valid UTF-8") from error
    body = b"".join(raw_lines[closing + 1 :])
    return has_bom, True, newline, lines, body


def _known_reference_replacements(
    metadata: Mapping[str, Any], replacements: Mapping[str, str]
) -> int:
    count = 0
    for key, value in metadata.items():
        if str(key).casefold() not in KNOWN_ID_REFERENCE_FIELDS:
            continue
        count += sum(item in replacements for item in _iter_scalar_strings(value))
    return count


def patch_markdown(
    payload: bytes,
    entry: MappingEntry,
    replacements: Mapping[str, str],
) -> PatchResult:
    """Create a minimal frontmatter-only patch while preserving body bytes."""

    before_hash = _sha256(payload)
    text, has_bom = _decode_markdown(payload)
    parsed = parse_markdown(text)
    if parsed.error:
        raise VaultSchemaPilotError(parsed.error)
    metadata = parsed.metadata
    current_id = str(metadata.get("id") or "")
    schema = metadata.get("schema_version")
    current_legacy = metadata.get("legacy_id")
    already_applied = current_id == entry.new_uuid and schema == 1
    if entry.old_id is not None and already_applied:
        if str(current_legacy) != entry.old_id:
            raise VaultSchemaPilotError(
                "already-applied note has conflicting legacy_id"
            )
    if not already_applied and before_hash != entry.before_sha256:
        raise VaultSchemaPilotError(
            f"compare-and-swap before hash failed: {entry.relative_path}"
        )
    if schema is not None and schema != 1:
        raise VaultSchemaPilotError("conflicting schema_version")
    if entry.old_id is not None and current_legacy is not None:
        if str(current_legacy) != entry.old_id:
            raise VaultSchemaPilotError("conflicting legacy_id")

    bom, has_frontmatter, newline, lines, body = _frontmatter_lines(payload)
    bom_bytes = b"\xef\xbb\xbf" if bom else b""
    if not has_frontmatter:
        if entry.source_id_state != "missing":
            raise VaultSchemaPilotError("invalid existing ID requires frontmatter")
        block = (
            f"---{newline}"
            f"id: {entry.new_uuid}{newline}"
            f"schema_version: 1{newline}"
            f"---{newline}"
        ).encode("utf-8")
        after = bom_bytes + block + body
        return PatchResult(
            path=entry.relative_path,
            before_sha256=before_hash,
            after_sha256=_sha256(after),
            before_size=len(payload),
            after_size=len(after),
            body_sha256=_sha256(body),
            id_changed=True,
            legacy_id_written=False,
            schema_version_written=True,
            structured_references_updated=0,
            payload=after,
        )

    key_indexes: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = _TOP_LEVEL_KEY_RE.match(line)
        if match:
            key_indexes[match.group(1).casefold()] = index
    if "id" not in key_indexes:
        insertion = 0
        lines.insert(insertion, f"id: {entry.new_uuid}{newline}")
        lines.insert(insertion + 1, f"schema_version: 1{newline}")
        id_changed = True
        legacy_written = False
        schema_written = True
    else:
        id_index = key_indexes["id"]
        if not already_applied:
            lines[id_index] = _replace_top_level_scalar(
                lines[id_index], "id", entry.new_uuid
            )
        insertion = id_index + 1
        legacy_written = False
        if entry.old_id is not None and "legacy_id" not in key_indexes:
            style = _scalar_style(lines[id_index].split(":", 1)[1])
            lines.insert(
                insertion,
                f"legacy_id: {_render_scalar(entry.old_id, style)}{newline}",
            )
            insertion += 1
            legacy_written = True
        schema_written = False
        if "schema_version" not in key_indexes:
            lines.insert(insertion, f"schema_version: 1{newline}")
            schema_written = True
        id_changed = not already_applied

    structured_expected = _known_reference_replacements(metadata, replacements)
    structured_updated = 0
    active_known_field = False
    for index, line in enumerate(lines):
        key_match = _TOP_LEVEL_KEY_RE.match(line)
        if key_match:
            key = key_match.group(1).casefold()
            active_known_field = key in KNOWN_ID_REFERENCE_FIELDS
        if active_known_field:
            lines[index], count = _replace_reference_tokens(lines[index], replacements)
            structured_updated += count
    if not already_applied and structured_updated != structured_expected:
        raise VaultSchemaPilotError(
            f"structured reference patch count mismatch: {entry.relative_path}"
        )

    after = (
        bom_bytes
        + f"---{newline}".encode("utf-8")
        + "".join(lines).encode("utf-8")
        + f"---{newline}".encode("utf-8")
        + body
    )
    after_text, after_bom = _decode_markdown(after)
    after_parsed = parse_markdown(after_text)
    if after_parsed.error:
        raise VaultSchemaPilotError("patched frontmatter is invalid")
    if str(after_parsed.metadata.get("id")) != entry.new_uuid:
        raise VaultSchemaPilotError("patched ID does not match the mapping")
    if after_parsed.metadata.get("schema_version") != 1:
        raise VaultSchemaPilotError("patched schema_version is not 1")
    if (
        entry.old_id is not None
        and str(after_parsed.metadata.get("legacy_id")) != entry.old_id
    ):
        raise VaultSchemaPilotError("patched legacy_id is not exact")
    if after_bom != has_bom or _body_bytes(after) != _body_bytes(payload):
        raise VaultSchemaPilotError("encoding marker or Markdown body changed")
    return PatchResult(
        path=entry.relative_path,
        before_sha256=before_hash,
        after_sha256=_sha256(after),
        before_size=len(payload),
        after_size=len(after),
        body_sha256=_sha256(body),
        id_changed=id_changed,
        legacy_id_written=legacy_written,
        schema_version_written=schema_written,
        structured_references_updated=structured_updated,
        payload=after,
    )


def _find_reference_counts(
    body: str,
    legacy_ids: set[str],
) -> tuple[int, int, int, int]:
    code_blocks = _CODE_BLOCK_RE.findall(body)
    code_spans = [match.group(0) for match in _CODE_BLOCK_RE.finditer(body)]
    code_count = sum(span.count(old) for span in code_spans for old in legacy_ids)
    without_code = _CODE_BLOCK_RE.sub("", body)
    wikilinks = [match.group(1) for match in _WIKILINK_RE.finditer(without_code)]
    markdown_links = [
        match.group(1) for match in _MARKDOWN_LINK_RE.finditer(without_code)
    ]
    wiki_count = sum(value.count(old) for value in wikilinks for old in legacy_ids)
    markdown_count = sum(
        value.count(old) for value in markdown_links for old in legacy_ids
    )
    free = _WIKILINK_RE.sub("", without_code)
    free = _MARKDOWN_LINK_RE.sub("", free)
    free_count = sum(free.count(old) for old in legacy_ids)
    del code_blocks
    return wiki_count, markdown_count, free_count, code_count


def analyze_references(root: Path, table: MappingTable) -> dict[str, Any]:
    """Classify references without changing content or reporting note bodies."""

    old_ids = {entry.old_id for entry in table.entries if entry.old_id is not None}
    reports: list[ReferenceFileReport] = []
    totals: Counter[str] = Counter()
    for path in _markdown_files(root):
        relative = _safe_relative(path.relative_to(root).as_posix())
        payload = path.read_bytes()
        text, _bom = _decode_markdown(payload)
        parsed = parse_markdown(text)
        if parsed.error:
            raise VaultSchemaPilotError(parsed.error)
        structured = 0
        unknown = 0
        for key, value in parsed.metadata.items():
            if str(key).casefold() in {"id", "legacy_id"}:
                continue
            count = sum(item in old_ids for item in _iter_scalar_strings(value))
            if str(key).casefold() in KNOWN_ID_REFERENCE_FIELDS:
                structured += count
            else:
                unknown += count
        wiki, markdown, free, code = _find_reference_counts(parsed.body, old_ids)
        report = ReferenceFileReport(
            path=relative,
            structured_id_references=structured,
            unknown_frontmatter_references=unknown,
            wikilink_references=wiki,
            markdown_link_references=markdown,
            free_text_references=free,
            code_block_references=code,
            body_sha256=_sha256(_body_bytes(payload)),
        )
        reports.append(report)
        for field, value in asdict(report).items():
            if field not in {"path", "body_sha256"}:
                totals[field] += int(value)
    return {
        "files": [asdict(item) for item in sorted(reports, key=lambda item: item.path)],
        "free_text_or_code_modified": False,
        "markdown_links_modified": False,
        "totals": dict(sorted(totals.items())),
        "wikilinks_modified": False,
    }


def plan_patches(root: Path, table: MappingTable) -> tuple[PatchResult, ...]:
    replacements = {
        entry.old_id: entry.new_uuid
        for entry in table.entries
        if entry.old_id is not None
    }
    planned: list[PatchResult] = []
    for entry in table.entries:
        path = root.joinpath(*PurePosixPath(entry.relative_path).parts)
        planned.append(patch_markdown(path.read_bytes(), entry, replacements))
    return tuple(sorted(planned, key=lambda item: item.path))


def _atomic_replace(path: Path, payload: bytes) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def apply_mapping(
    root: Path,
    table: MappingTable,
    *,
    fail_after: int | None = None,
) -> ApplyResult:
    """Apply the immutable table to a disposable pilot with per-file CAS."""

    replacements = {
        entry.old_id: entry.new_uuid
        for entry in table.entries
        if entry.old_id is not None
    }
    changed = 0
    unchanged = 0
    after_hashes: dict[str, str] = {}
    for position, entry in enumerate(table.entries):
        path = root.joinpath(*PurePosixPath(entry.relative_path).parts)
        current = path.read_bytes()
        patch = patch_markdown(current, entry, replacements)
        if patch.payload == current:
            unchanged += 1
        else:
            if _sha256(current) != entry.before_sha256:
                raise VaultSchemaPilotError(
                    f"compare-and-swap before hash failed: {entry.relative_path}"
                )
            _atomic_replace(path, patch.payload)
            if _sha256(path.read_bytes()) != patch.after_sha256:
                raise VaultSchemaPilotError("post-replace hash verification failed")
            changed += 1
        after_hashes[entry.relative_path] = _sha256(path.read_bytes())
        if fail_after is not None and position + 1 >= fail_after:
            raise VaultSchemaPilotError("synthetic partial apply failure")
    return ApplyResult(changed=changed, unchanged=unchanged, after_hashes=after_hashes)


def _validate_after(
    root: Path,
    table: MappingTable,
    before_manifest: tuple[FileManifestEntry, ...],
    after_manifest: tuple[FileManifestEntry, ...],
    planned: tuple[PatchResult, ...],
) -> dict[str, Any]:
    before_paths = {entry.path for entry in before_manifest}
    after_paths = {entry.path for entry in after_manifest}
    mapping_by_path = {entry.relative_path: entry for entry in table.entries}
    planned_by_path = {entry.path: entry for entry in planned}
    ids: list[str] = []
    valid_ids = missing_ids = parser_shape_errors = 0
    exact_legacy = schema_v1 = body_violations = 0
    for path in _markdown_files(root):
        relative = path.relative_to(root).as_posix()
        payload = path.read_bytes()
        text, _bom = _decode_markdown(payload)
        parsed = parse_markdown(text)
        if parsed.error:
            parser_shape_errors += 1
            continue
        raw_id = str(parsed.metadata.get("id") or "")
        if raw_id:
            ids.append(raw_id)
            valid_ids += int(_valid_uuid(raw_id))
        else:
            missing_ids += 1
        schema_v1 += int(parsed.metadata.get("schema_version") == 1)
        mapped = mapping_by_path.get(relative)
        if mapped is not None and mapped.old_id is not None:
            exact_legacy += int(str(parsed.metadata.get("legacy_id")) == mapped.old_id)
        planned_patch = planned_by_path.get(relative)
        if planned_patch is not None:
            body_violations += int(
                _sha256(_body_bytes(payload)) != planned_patch.body_sha256
            )
    return {
        "body_violations": body_violations,
        "duplicate_ids": len(ids) - len(set(ids)),
        "exact_legacy_ids": exact_legacy,
        "extra_paths": sorted(after_paths - before_paths),
        "file_count_after": len(after_manifest),
        "file_count_before": len(before_manifest),
        "missing_ids": missing_ids,
        "missing_paths": sorted(before_paths - after_paths),
        "parser_shape_errors": parser_shape_errors,
        "schema_v1": schema_v1,
        "valid_ids": valid_ids,
    }


def _write(path: Path, payload: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _write_json(path: Path, value: Any) -> None:
    _write(
        path,
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True).encode("utf-8")
        + b"\n",
    )


def _copy_verified(source: Path, destination: Path) -> None:
    _safe_tree(source)
    shutil.copytree(source, destination, copy_function=shutil.copy2)
    source_manifest, source_hash = build_manifest(source)
    copied_manifest, copied_hash = build_manifest(destination)
    if source_manifest != copied_manifest or source_hash != copied_hash:
        raise VaultSchemaPilotError("pilot copy differs from verified backup data")


def _remove_tree(path: Path) -> None:
    def writable(function: Any, target: str, _error: Any) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if path.exists():
        shutil.rmtree(path, onerror=writable)


def _parser_report(pilot: Path, state: Path) -> dict[str, Any]:
    database = state / "memory.sqlite3"
    with VaultIndex(
        pilot,
        database,
        mode="read-only",
        embeddings_enabled=False,
    ) as index:
        first = index.rebuild()
        errors = index.list_errors(limit=10_000)
        error_types = Counter(str(item["error_type"]) for item in errors)
        unsupported = sum(
            "unsupported note type" in str(item.get("message", "")) for item in errors
        )
        health = index.health()
    with VaultIndex(
        pilot,
        database,
        mode="read-only",
        embeddings_enabled=False,
    ) as reopened:
        readback = reopened.sync()
        readback_health = reopened.health()
    return {
        "duplicate_contents": first.duplicate_contents,
        "duplicate_ids": first.duplicate_ids,
        "error_type_counts": dict(sorted(error_types.items())),
        "fts5_available": health.fts5_available,
        "indexed": first.indexed,
        "parser_errors": first.parser_errors,
        "process_restart_readback_indexed": readback_health.note_count,
        "process_restart_sync_unchanged": readback.unchanged,
        "scanned": first.scanned,
        "unsupported_note_type_errors": unsupported,
    }


def _diff_manifest(planned: tuple[PatchResult, ...]) -> list[dict[str, Any]]:
    return [
        {
            "after_sha256": item.after_sha256,
            "after_size": item.after_size,
            "before_sha256": item.before_sha256,
            "before_size": item.before_size,
            "body_sha256": item.body_sha256,
            "id_changed": item.id_changed,
            "legacy_id_written": item.legacy_id_written,
            "path": item.path,
            "schema_version_written": item.schema_version_written,
            "structured_references_updated": item.structured_references_updated,
        }
        for item in planned
    ]


def run_isolated_pilot(
    vault_backup: Path,
    output: Path,
    *,
    expected_source_manifest_sha256: str,
    established_vault_backup_tree_sha256: str,
) -> dict[str, Any]:
    """Run the full pilot from backup data and always remove disposable copies."""

    vault_backup = vault_backup.absolute()
    output = output.absolute()
    if output.exists():
        raise VaultSchemaPilotError("pilot review output must not already exist")
    data = vault_backup / "data"
    manifests = vault_backup / "manifests"
    summary = json.loads((manifests / "summary.json").read_text(encoding="utf-8"))
    if summary.get("manifest_sha256") != expected_source_manifest_sha256:
        raise VaultSchemaPilotError("Vault source manifest hash is not approved")
    expected = load_manifest(manifests / "source-before.jsonl")
    if not verify_manifest(data, expected):
        raise VaultSchemaPilotError("Vault backup does not match its verified manifest")
    backup_before, backup_before_hash = build_manifest(data)

    work = output.parent / f".phase8b-vault-work-{uuid.uuid4().hex}.tmp"
    review = output.parent / f".phase8b-vault-review-{uuid.uuid4().hex}.tmp"
    work.mkdir(parents=True)
    review.mkdir()
    pilot = work / "pilot"
    restore_source = work / "restore-source"
    rollback = work / "rollback"
    state = work / "state"
    result: dict[str, Any] | None = None
    try:
        _copy_verified(data, pilot)
        _copy_verified(data, restore_source)
        before, before_hash = build_manifest(pilot)
        restore_manifest, restore_hash = build_manifest(restore_source)
        if before != restore_manifest or before_hash != restore_hash:
            raise VaultSchemaPilotError("immutable restore copy differs from before")

        mapping_first = build_mapping(pilot)
        mapping_second = build_mapping(pilot)
        if mapping_first != mapping_second:
            raise VaultSchemaPilotError("mapping is not deterministic on repetition")
        table = mapping_first
        reference_before = analyze_references(pilot, table)
        planned = plan_patches(pilot, table)
        mapping_bytes = mapping_to_bytes(table)
        _write(review / "mapping.json", mapping_bytes)
        _write(review / "mapping.sha256", (table.mapping_sha256 + "\n").encode())
        _write(review / "before-manifest.jsonl", _canonical_jsonl(before))

        first_apply = apply_mapping(pilot, table)
        second_apply = apply_mapping(pilot, table)
        after, after_hash = build_manifest(pilot)
        validation = _validate_after(pilot, table, before, after, planned)
        reference_after = analyze_references(pilot, table)
        reference_report = {
            "after": reference_after,
            "before": reference_before,
            "body_hashes_unchanged": all(
                before_item["body_sha256"] == after_item["body_sha256"]
                for before_item, after_item in zip(
                    reference_before["files"], reference_after["files"], strict=True
                )
            ),
            "structured_references_consistent": (
                reference_after["totals"].get("structured_id_references", 0) == 0
            ),
            "unknown_integrity_dependency_count": sum(
                reference_after["totals"].get(key, 0)
                for key in (
                    "code_block_references",
                    "free_text_references",
                    "markdown_link_references",
                    "unknown_frontmatter_references",
                    "wikilink_references",
                )
            ),
        }
        parser = _parser_report(pilot, state)

        _copy_verified(restore_source, rollback)
        rollback_manifest, rollback_hash = build_manifest(rollback)
        rollback_ok = rollback_manifest == before and rollback_hash == before_hash
        _remove_tree(rollback)
        if not rollback_ok:
            raise VaultSchemaPilotError("rollback probe differs from before manifest")

        backup_after, backup_after_hash = build_manifest(data)
        if backup_after != backup_before or backup_after_hash != backup_before_hash:
            raise VaultSchemaPilotError("verified Vault backup changed during pilot")
        gates = {
            "after_file_count_unchanged": len(after) == len(before),
            "all_46_have_schema_v1": validation["schema_v1"] == 46,
            "all_46_have_valid_uuid": validation["valid_ids"] == 46,
            "body_bytes_unchanged": validation["body_violations"] == 0,
            "exact_41_legacy_ids": validation["exact_legacy_ids"] == 41,
            "fts5_indexed_46": parser["fts5_available"] and parser["indexed"] == 46,
            "mapping_repeat_identical": mapping_first == mapping_second,
            "no_duplicate_ids": validation["duplicate_ids"] == 0,
            "no_extra_or_missing_paths": not validation["extra_paths"]
            and not validation["missing_paths"],
            "no_missing_ids": validation["missing_ids"] == 0,
            "no_parser_errors": parser["parser_errors"] == 0,
            "process_restart_readback_46": (
                parser["process_restart_readback_indexed"] == 46
            ),
            "rollback_byte_exact": rollback_ok,
            "second_apply_noop": second_apply.changed == 0
            and second_apply.unchanged == 46,
            "structured_references_consistent": reference_report[
                "structured_references_consistent"
            ],
            "wikilinks_and_markdown_bodies_unchanged": reference_report[
                "body_hashes_unchanged"
            ],
        }
        status = "passed" if all(gates.values()) else "failed_gates"
        result = {
            "after_manifest_sha256": after_hash,
            "before_manifest_sha256": before_hash,
            "changed_files": first_apply.changed,
            "established_vault_backup_tree_sha256": (
                established_vault_backup_tree_sha256
            ),
            "gates": gates,
            "mapping_entries": len(table.entries),
            "mapping_sha256": table.mapping_sha256,
            "missing_id_mappings": sum(
                entry.source_id_state == "missing" for entry in table.entries
            ),
            "namespace_uuid": str(NAMESPACE_UUID),
            "parser": parser,
            "pilot_copy_removed": False,
            "reference_integrity_blockers": reference_report[
                "unknown_integrity_dependency_count"
            ],
            "restore_copy_removed": False,
            "rollback_probe_removed": not rollback.exists(),
            "second_apply_changed": second_apply.changed,
            "status": status,
            "unchanged_files": len(before) - first_apply.changed,
            "valid_legacy_id_mappings": sum(
                entry.source_id_state == "invalid_existing" for entry in table.entries
            ),
            "vault_backup_unchanged": True,
            "vault_source_manifest_sha256": expected_source_manifest_sha256,
        }
        _write(review / "after-manifest.jsonl", _canonical_jsonl(after))
        _write(
            review / "diff-manifest.jsonl", _canonical_jsonl(_diff_manifest(planned))
        )
        _write_json(review / "reference-report.json", reference_report)
        _write_json(review / "parser-report.json", parser)
        rollback_text = (
            "Phase 8B isolated rollback proof\n"
            f"before_manifest_sha256: {before_hash}\n"
            f"rollback_manifest_sha256: {rollback_hash}\n"
            f"file_count: {len(before)}\n"
            f"byte_exact: {str(rollback_ok).lower()}\n"
            "rollback_target_removed: true\n"
            "restore_source: verified-vault-backup-copy\n"
        )
        _write(review / "rollback-proof.txt", rollback_text.encode("utf-8"))
    finally:
        _remove_tree(work)
        if result is not None:
            result["pilot_copy_removed"] = not work.exists()
            result["restore_copy_removed"] = not work.exists()
            _write_json(review / "pilot-summary.json", result)
            _write_json(
                review / "cleanup-proof.json",
                {
                    "pilot_copy_removed": result["pilot_copy_removed"],
                    "restore_copy_removed": result["restore_copy_removed"],
                    "rollback_probe_removed": result["rollback_probe_removed"],
                    "sqlite_index_removed": not work.exists(),
                },
            )
            os.replace(review, output)
        else:
            _remove_tree(review)
    if result is None:
        raise VaultSchemaPilotError("pilot ended without a result")
    return result


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault-backup", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-source-manifest-sha256", required=True)
    parser.add_argument("--established-vault-backup-tree-sha256", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = run_isolated_pilot(
        args.vault_backup,
        args.output,
        expected_source_manifest_sha256=args.expected_source_manifest_sha256,
        established_vault_backup_tree_sha256=(
            args.established_vault_backup_tree_sha256
        ),
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
