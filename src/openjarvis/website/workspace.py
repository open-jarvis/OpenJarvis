"""Root-confined workspace and static verification for website staging."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from openjarvis.website.models import (
    WebsiteFileProposal,
    WebsiteFileState,
    canonical_json,
    safe_relative_path,
    sha256_payload,
)


class WebsiteStagingError(RuntimeError):
    """Raised before an unsafe or unverifiable staging effect is accepted."""


MEDIA_TYPES = {
    ".css": "text/css",
    ".gif": "image/gif",
    ".html": "text/html",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".js": "text/javascript",
    ".json": "application/json",
    ".md": "text/markdown",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webp": "image/webp",
}
TEXT_EXTENSIONS = frozenset({".css", ".html", ".js", ".json", ".md", ".svg"})
_REPARSE_ATTRIBUTE = 0x400
_EXTERNAL_SCHEMES = frozenset({"http", "https"})
_LOCAL_IGNORED_SCHEMES = frozenset({"mailto", "tel"})
_RESOURCE_TAGS = frozenset(
    {"audio", "embed", "iframe", "img", "link", "object", "script", "source", "video"}
)
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)"
        r"\s*[:=]\s*['\"]?[A-Za-z0-9._~+/=-]{12,}"
    ),
)
_DANGEROUS_SCRIPT_PATTERNS = (
    ("eval", re.compile(r"\beval\s*\(")),
    ("new Function", re.compile(r"\bnew\s+Function\s*\(")),
    (
        "shell bridge",
        re.compile(r"\b(?:child_process|powershell|cmd\.exe|bash\s+-c)\b", re.I),
    ),
    (
        "native bridge",
        re.compile(r"\b(?:process\.binding|Deno\.|Bun\.|window\.__TAURI__)\b"),
    ),
    (
        "credential access",
        re.compile(r"\b(?:document\.cookie|localStorage|sessionStorage)\b"),
    ),
)
_SHELL_TEXT = re.compile(
    r"(?im)^\s*(?:#!.*(?:sh|python|powershell)|(?:sudo\s+)?(?:rm|del|curl|wget)\s+)"
)
_CSS_URL = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)


def _is_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise WebsiteStagingError("workspace entry could not be inspected") from exc
    attributes = int(getattr(info, "st_file_attributes", 0))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & _REPARSE_ATTRIBUTE)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _overlaps(left: Path, right: Path) -> bool:
    return _inside(left, right) or _inside(right, left)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _walk_metadata(root: Path) -> list[tuple[Path, str, int]]:
    if not root.is_dir() or _is_reparse(root):
        raise WebsiteStagingError("workspace root must be a normal directory")
    result: list[tuple[Path, str, int]] = []

    def visit(current: Path) -> None:
        try:
            with os.scandir(current) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            raise WebsiteStagingError(
                "workspace directory could not be inspected"
            ) from exc
        for entry in entries:
            path = Path(entry.path)
            if _is_reparse(path):
                raise WebsiteStagingError("workspace contains a reparse point")
            if entry.is_dir(follow_symlinks=False):
                visit(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                raise WebsiteStagingError("workspace contains an unsupported entry")
            relative = path.relative_to(root).as_posix()
            safe_relative_path(relative)
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError as exc:
                raise WebsiteStagingError("workspace file metadata changed") from exc
            result.append((path, relative, size))

    visit(root)
    return result


def scan_tree(
    root: Path,
    *,
    maximum_files: int,
    maximum_total_bytes: int,
) -> tuple[tuple[WebsiteFileState, ...], str]:
    metadata = _walk_metadata(root)
    if len(metadata) > maximum_files:
        raise WebsiteStagingError("website file budget exceeded")
    total = sum(size for _path, _relative, size in metadata)
    if total > maximum_total_bytes:
        raise WebsiteStagingError("website byte budget exceeded")
    states: list[WebsiteFileState] = []
    for path, relative, size in metadata:
        suffix = path.suffix.casefold()
        media_type = MEDIA_TYPES.get(suffix)
        if media_type is None:
            raise WebsiteStagingError(
                f"forbidden website file type: {suffix or 'none'}"
            )
        states.append(
            WebsiteFileState(
                relative_path=relative,
                size_bytes=size,
                sha256=_hash_file(path),
                media_type=media_type,
            )
        )
    ordered = tuple(sorted(states, key=lambda item: item.relative_path.casefold()))
    digest = sha256_payload([item.model_dump(mode="json") for item in ordered])
    return ordered, digest


def read_tree(root: Path, states: tuple[WebsiteFileState, ...]) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for state in states:
        path = confined_path(root, state.relative_path, require_file=True)
        content = path.read_bytes()
        if (
            len(content) != state.size_bytes
            or hashlib.sha256(content).hexdigest() != state.sha256
        ):
            raise WebsiteStagingError("workspace changed while it was being read")
        result[state.relative_path] = content
    return result


def confined_path(root: Path, relative: str, *, require_file: bool = False) -> Path:
    safe_relative_path(relative)
    resolved_root = root.resolve(strict=True)
    if _is_reparse(resolved_root):
        raise WebsiteStagingError("workspace root is a reparse point")
    candidate = resolved_root.joinpath(*relative.split("/"))
    current = resolved_root
    for part in relative.split("/"):
        current = current / part
        if current.exists() and _is_reparse(current):
            raise WebsiteStagingError("workspace path crosses a reparse point")
    resolved = candidate.resolve(strict=False)
    if not _inside(resolved, resolved_root):
        raise WebsiteStagingError("workspace path escapes its root")
    if require_file and (not candidate.is_file() or _is_reparse(candidate)):
        raise WebsiteStagingError("expected workspace file is unavailable")
    return candidate


class WebsiteWorkspaceStore:
    """Persist only bounded metadata beside isolated disposable workspaces."""

    def __init__(self, root: Path, *, protected_roots: tuple[Path, ...]) -> None:
        if not root.exists() or not root.is_dir() or _is_reparse(root):
            raise WebsiteStagingError(
                "staging base must be an existing normal directory"
            )
        self.root = root.resolve(strict=True)
        for protected in protected_roots:
            resolved = protected.resolve(strict=False)
            if _overlaps(self.root, resolved):
                raise WebsiteStagingError("staging base overlaps a protected project")
        self.workspaces = self.root / "workspaces"
        self.restores = self.root / "restores"
        self.state = self.root / "state"
        self.previews = self.state / "previews"
        self.records = self.state / "workspaces"
        for path in (self.workspaces, self.restores, self.previews, self.records):
            path.mkdir(parents=True, exist_ok=True)
            if _is_reparse(path):
                raise WebsiteStagingError("staging metadata path is a reparse point")

    def workspace_root(self, workspace_id: str) -> Path:
        safe_relative_path(workspace_id)
        return self.workspaces / workspace_id

    def site_root(self, workspace_id: str) -> Path:
        root = self.workspace_root(workspace_id)
        site = root / "site"
        if not site.is_dir() or _is_reparse(site):
            raise WebsiteStagingError("unknown or unsafe website workspace")
        return site

    def provision(
        self,
        workspace_id: str,
        fixtures: tuple[WebsiteFileProposal, ...] = (),
    ) -> Path:
        root = self.workspace_root(workspace_id)
        if root.exists():
            raise WebsiteStagingError("website workspace already exists")
        site = root / "site"
        site.mkdir(parents=True)
        try:
            for fixture in fixtures:
                path = confined_path(site, fixture.relative_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(fixture.content_bytes())
            _walk_metadata(site)
        except Exception:
            self._remove_owned(root)
            raise
        return site

    def save_preview(self, preview_hash: str, payload: bytes) -> None:
        self._atomic_write(self.previews / f"{preview_hash}.json", payload)

    def load_preview(self, preview_hash: str) -> bytes:
        path = self.previews / f"{preview_hash}.json"
        if not path.is_file() or _is_reparse(path):
            raise WebsiteStagingError("unknown preview hash")
        return path.read_bytes()

    def save_workspace_record(self, workspace_id: str, payload: bytes) -> None:
        safe_relative_path(workspace_id)
        self._atomic_write(self.records / f"{workspace_id}.json", payload)

    def load_workspace_record(self, workspace_id: str) -> bytes | None:
        safe_relative_path(workspace_id)
        path = self.records / f"{workspace_id}.json"
        if not path.exists():
            return None
        if not path.is_file() or _is_reparse(path):
            raise WebsiteStagingError("workspace record is unsafe")
        return path.read_bytes()

    def create_restore(self, restore_id: str, site: Path) -> Path:
        safe_relative_path(restore_id)
        destination = self.restores / restore_id / "site"
        if destination.parent.exists():
            raise WebsiteStagingError("restore identity already exists")
        destination.mkdir(parents=True)
        try:
            states, _digest = scan_tree(
                site,
                maximum_files=128,
                maximum_total_bytes=5_242_880,
            )
            contents = read_tree(site, states)
            for relative, content in contents.items():
                target = confined_path(destination, relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        except Exception:
            self._remove_owned(destination.parent)
            raise
        return destination

    def remove_restore(self, restore_id: str) -> None:
        safe_relative_path(restore_id)
        self._remove_owned(self.restores / restore_id)

    def cleanup_workspace(self, workspace_id: str) -> None:
        root = self.workspace_root(workspace_id)
        self._remove_owned(root)
        record = self.records / f"{workspace_id}.json"
        if record.exists():
            record.unlink()

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        if not _inside(path.resolve(strict=False), self.root):
            raise WebsiteStagingError("metadata path escapes staging root")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _remove_owned(self, path: Path) -> None:
        resolved = path.resolve(strict=False)
        if resolved == self.root or not _inside(resolved, self.root):
            raise WebsiteStagingError("refusing to remove an unowned path")
        if path.exists() and _is_reparse(path):
            raise WebsiteStagingError("refusing to remove a reparse point")
        shutil.rmtree(path, ignore_errors=False) if path.exists() else None


@dataclass(frozen=True, slots=True)
class StaticInspection:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    external_urls: tuple[str, ...]
    script_files: tuple[str, ...]
    warnings_by_file: dict[str, tuple[str, ...]]


class _HtmlInspectionParser(HTMLParser):
    def __init__(self, *, relative_path: str) -> None:
        super().__init__(convert_charrefs=True)
        self.relative_path = relative_path
        self.references: list[tuple[str, str, str]] = []
        self.errors: list[str] = []
        self.stack: list[str] = []
        self.script_chunks: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.casefold()
        values = {key.casefold(): value or "" for key, value in attrs}
        if lowered not in _VOID_TAGS:
            self.stack.append(lowered)
        if lowered == "script":
            self._in_script = True
        for attribute in ("href", "src", "action", "poster", "data"):
            if attribute in values and values[attribute].strip():
                self.references.append((lowered, attribute, values[attribute].strip()))
        if lowered == "meta" and values.get("http-equiv", "").casefold() == "refresh":
            self.errors.append(f"{self.relative_path}: meta refresh is forbidden")

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        lowered = tag.casefold()
        if lowered not in _VOID_TAGS and self.stack and self.stack[-1] == lowered:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered == "script":
            self._in_script = False
        if lowered in _VOID_TAGS:
            return
        if not self.stack or self.stack[-1] != lowered:
            self.errors.append(f"{self.relative_path}: malformed closing tag {lowered}")
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.script_chunks.append(data)


def _inspect_script(relative: str, text: str) -> list[str]:
    errors = []
    for label, pattern in _DANGEROUS_SCRIPT_PATTERNS:
        if pattern.search(text):
            errors.append(f"{relative}: forbidden JavaScript construct ({label})")
    if _SHELL_TEXT.search(text):
        errors.append(f"{relative}: shell or installer content is forbidden")
    return errors


def _inspect_reference(
    *,
    relative: str,
    tag: str,
    attribute: str,
    raw: str,
    known_paths: frozenset[str],
) -> tuple[list[str], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    external: list[str] = []
    value = raw.strip()
    split = urlsplit(value)
    scheme = split.scheme.casefold()
    if scheme == "file":
        return [f"{relative}: file URL is forbidden"], warnings, external
    if scheme in _EXTERNAL_SCHEMES:
        external.append(value)
        if tag == "form" and attribute == "action":
            errors.append(f"{relative}: external form action is forbidden")
        elif tag in _RESOURCE_TAGS:
            errors.append(f"{relative}: external executable resource is forbidden")
        else:
            warnings.append(f"{relative}: external URL not fetched: {value}")
        return errors, warnings, external
    if scheme in _LOCAL_IGNORED_SCHEMES:
        warnings.append(f"{relative}: non-local link not fetched: {scheme}")
        return errors, warnings, external
    if scheme or value.startswith("//"):
        errors.append(f"{relative}: unsupported URL scheme is forbidden")
        return errors, warnings, external
    path_value = unquote(split.path)
    if not path_value or path_value == "#" or value.startswith("#"):
        return errors, warnings, external
    if path_value.startswith("/") or "\\" in path_value:
        errors.append(f"{relative}: non-relative local link is forbidden")
        return errors, warnings, external
    parent = Path(relative).parent.as_posix()
    joined = (Path(parent) / path_value).as_posix() if parent != "." else path_value
    try:
        target = safe_relative_path(joined)
    except (TypeError, ValueError):
        errors.append(f"{relative}: path-traversal link is forbidden")
        return errors, warnings, external
    if target not in known_paths:
        errors.append(f"{relative}: missing local reference {target}")
    return errors, warnings, external


def inspect_static_content(content: dict[str, bytes]) -> StaticInspection:
    """Inspect local bytes only; no URL, script, command, or model is invoked."""

    errors: list[str] = []
    warnings: list[str] = []
    external_urls: list[str] = []
    script_files: list[str] = []
    warnings_by_file: dict[str, tuple[str, ...]] = {}
    known = frozenset(content)
    for relative in sorted(content, key=str.casefold):
        suffix = Path(relative).suffix.casefold()
        raw = content[relative]
        if suffix not in TEXT_EXTENSIONS:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"{relative}: text file is not UTF-8")
            continue
        file_warnings: list[str] = []
        if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
            errors.append(f"{relative}: secret-like content is forbidden")
        if suffix == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError:
                errors.append(f"{relative}: invalid JSON")
        elif suffix == ".svg":
            if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
                errors.append(
                    f"{relative}: XML declarations with entities are forbidden"
                )
            try:
                ET.fromstring(text)
            except ET.ParseError:
                errors.append(f"{relative}: invalid SVG XML")
        elif suffix == ".js":
            script_files.append(relative)
            errors.extend(_inspect_script(relative, text))
        elif suffix == ".html":
            parser = _HtmlInspectionParser(relative_path=relative)
            try:
                parser.feed(text)
                parser.close()
            except Exception:
                errors.append(f"{relative}: HTML could not be parsed")
            errors.extend(parser.errors)
            if parser.stack:
                errors.append(f"{relative}: HTML contains unclosed tags")
            if parser.script_chunks:
                script_files.append(relative)
                errors.extend(
                    _inspect_script(relative, "\n".join(parser.script_chunks))
                )
            for tag, attribute, value in parser.references:
                ref_errors, ref_warnings, ref_external = _inspect_reference(
                    relative=relative,
                    tag=tag,
                    attribute=attribute,
                    raw=value,
                    known_paths=known,
                )
                errors.extend(ref_errors)
                file_warnings.extend(ref_warnings)
                external_urls.extend(ref_external)
        if suffix == ".css":
            for _quote, value in _CSS_URL.findall(text):
                ref_errors, ref_warnings, ref_external = _inspect_reference(
                    relative=relative,
                    tag="link",
                    attribute="href",
                    raw=value,
                    known_paths=known,
                )
                errors.extend(ref_errors)
                file_warnings.extend(ref_warnings)
                external_urls.extend(ref_external)
        if _SHELL_TEXT.search(text):
            errors.append(f"{relative}: shell or installer content is forbidden")
        if file_warnings:
            unique = tuple(sorted(set(file_warnings)))
            warnings_by_file[relative] = unique
            warnings.extend(unique)
    return StaticInspection(
        errors=tuple(sorted(set(errors))),
        warnings=tuple(sorted(set(warnings))),
        external_urls=tuple(sorted(set(external_urls))),
        script_files=tuple(sorted(set(script_files))),
        warnings_by_file=warnings_by_file,
    )


def write_proposals_atomically(
    site: Path,
    proposals: tuple[WebsiteFileProposal, ...],
) -> None:
    """Validate all temporary files before replacing any target file."""

    temporaries: list[tuple[Path, Path]] = []
    try:
        for proposal in proposals:
            target = confined_path(site, proposal.relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if any(
                _is_reparse(parent)
                for parent in (target, *target.parents)
                if parent.exists() and _inside(parent, site)
            ):
                raise WebsiteStagingError("website target crosses a reparse point")
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            content = proposal.content_bytes()
            temporary.write_bytes(content)
            if (
                temporary.stat().st_size != proposal.size_bytes
                or _hash_file(temporary) != proposal.proposed_sha256
            ):
                raise WebsiteStagingError("temporary website write did not verify")
            temporaries.append((temporary, target))
        for temporary, target in temporaries:
            os.replace(temporary, target)
    finally:
        for temporary, _target in temporaries:
            temporary.unlink(missing_ok=True)


def replace_tree_atomically(current: Path, replacement: Path, *, owner: Path) -> None:
    """Swap two owned directories and restore the original if the swap fails."""

    owner = owner.resolve(strict=True)
    for candidate in (current, replacement):
        if not _inside(candidate.resolve(strict=False), owner) or _is_reparse(
            candidate
        ):
            raise WebsiteStagingError("rollback directory is not safely owned")
    discarded = current.with_name(f".{current.name}.{uuid.uuid4().hex}.discard")
    os.replace(current, discarded)
    try:
        os.replace(replacement, current)
    except Exception:
        os.replace(discarded, current)
        raise
    shutil.rmtree(discarded)


def json_bytes(value: object) -> bytes:
    return canonical_json(value)


__all__ = [
    "MEDIA_TYPES",
    "StaticInspection",
    "WebsiteStagingError",
    "WebsiteWorkspaceStore",
    "confined_path",
    "inspect_static_content",
    "json_bytes",
    "read_tree",
    "replace_tree_atomically",
    "scan_tree",
    "write_proposals_atomically",
]
