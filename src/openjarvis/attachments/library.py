"""Attachment library: files and images the user hands to Jarvis.

Every attachment (uploaded, pasted, dropped or a screenshot) is kept so it can
be used again later - by the user from the HUD, by Jarvis through tools, or by
a routine ("summarise yesterday's invoice"):

* bytes go to the shared content-addressed blob store
  (``connectors.attachment_store.AttachmentStore``, ``~/.openjarvis/blobs``);
* ``~/.openjarvis/attachments/<id>/meta.json`` holds the details and
  ``text.txt`` the readable text - extracted from documents, or a description
  (with any visible text transcribed) written by a vision model for images.

``context_for`` turns a set of attachments into a text block that is added to
the chat message they were attached to, within a character budget.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import shutil
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from openjarvis.attachments.extract import (
    ALLOWED_EXTENSIONS,
    extract_text,
    kind_for,
)

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_CONTEXT_CHARS = 12_000
_SOURCE_PREFIX = "chat-attachment:"
_ID = re.compile(r"^[0-9a-f]{12}$")

# A describer gets (image bytes, mime type) and returns a text description.
Describer = Callable[[bytes, str], str]


class AttachmentError(ValueError):
    """Raised for files that cannot be attached (type, size, missing)."""


@dataclass
class Attachment:
    id: str
    name: str
    mime: str
    size: int
    kind: str  # "text" | "document" | "image"
    source: str  # "upload" | "paste" | "screenshot" | ...
    created_at: str
    sha256: str
    pages: Optional[int] = None
    text_chars: int = 0
    status: str = "ready"  # "ready" | "describing" | "failed"
    error: str = ""
    knowledge_doc_id: Optional[str] = None
    extra: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return asdict(self)


class AttachmentLibrary:
    def __init__(
        self,
        root: Optional[Path] = None,
        blob_store=None,
        *,
        describer: Optional[Describer] = None,
    ) -> None:
        from openjarvis.core.paths import get_config_dir

        self._root = Path(root) if root else get_config_dir() / "attachments"
        self._root.mkdir(parents=True, exist_ok=True)
        if blob_store is None:
            from openjarvis.connectors.attachment_store import AttachmentStore

            blob_store = AttachmentStore()
        self._blobs = blob_store
        self._describer = describer
        self._lock = threading.RLock()

    # -- configuration ------------------------------------------------------

    def set_describer(self, describer: Optional[Describer]) -> None:
        self._describer = describer

    # -- paths / persistence -----------------------------------------------------

    def _dir(self, att_id: str) -> Path:
        if not _ID.match(att_id):
            raise AttachmentError(f"Invalid attachment id: {att_id!r}")
        return self._root / att_id

    def _save(self, att: Attachment) -> None:
        d = self._dir(att.id)
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(
            json.dumps(att.to_dict(), indent=2), encoding="utf-8"
        )

    def _write_text(self, att_id: str, text: str) -> None:
        (self._dir(att_id) / "text.txt").write_text(text, encoding="utf-8")

    # -- create -------------------------------------------------------------------

    def add(
        self,
        data: bytes,
        filename: str,
        *,
        mime: str = "",
        source: str = "upload",
    ) -> Attachment:
        """Store a new attachment and extract its text (images: describe later)."""
        name = Path(filename or "attachment").name.strip() or "attachment"
        ext = Path(name).suffix.lower()
        if not ext and mime:
            ext = (mimetypes.guess_extension(mime) or "").lower()
            name += ext
        if ext not in ALLOWED_EXTENSIONS:
            raise AttachmentError(f"Unsupported file type: {ext or 'unknown'}")
        if not data:
            raise AttachmentError("The file is empty.")
        if len(data) > MAX_FILE_BYTES:
            raise AttachmentError(
                f"File is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB."
            )
        if not mime or mime == "application/octet-stream":
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        att_id = uuid.uuid4().hex[:12]
        with self._lock:
            sha = self._blobs.store(
                data,
                filename=name,
                mime_type=mime,
                source_doc_id=_SOURCE_PREFIX + att_id,
            )
        kind = kind_for(ext)
        extracted = extract_text(data, ext)
        att = Attachment(
            id=att_id,
            name=name,
            mime=mime,
            size=len(data),
            kind=kind,
            source=source,
            created_at=datetime.now(timezone.utc).isoformat(),
            sha256=sha,
            pages=extracted.pages,
            text_chars=len(extracted.text),
            error=extracted.error,
        )
        if kind == "image":
            att.status = "describing" if self._describer else "ready"
        elif extracted.error and not extracted.text:
            att.status = "failed"
        self._save(att)
        self._write_text(att_id, extracted.text)
        if kind == "image" and self._describer is not None:
            threading.Thread(
                target=self._describe,
                args=(att_id, data, mime),
                daemon=True,
                name=f"describe-{att_id}",
            ).start()
        return att

    def _describe(self, att_id: str, data: bytes, mime: str) -> None:
        att = self.get(att_id)
        if att is None:
            return
        try:
            text = (self._describer(data, mime) if self._describer else "").strip()
            if not text:
                raise RuntimeError("The vision model returned no description.")
            self._write_text(att_id, text)
            att.text_chars, att.status, att.error = len(text), "ready", ""
        except Exception as exc:
            logger.info("Describing image %s failed: %s", att_id, exc)
            att.status, att.error = "failed", f"Could not describe the image: {exc}"
        if self.get(att_id) is not None:  # not deleted meanwhile
            self._save(att)

    # -- read ---------------------------------------------------------------------

    def get(self, att_id: str) -> Optional[Attachment]:
        try:
            raw = (self._dir(att_id) / "meta.json").read_text(encoding="utf-8")
        except (OSError, AttachmentError):
            return None
        try:
            return Attachment(**json.loads(raw))
        except (TypeError, ValueError):
            return None

    def list(self, limit: int = 100) -> List[Attachment]:
        items = []
        for d in self._root.iterdir():
            if d.is_dir() and _ID.match(d.name):
                att = self.get(d.name)
                if att is not None:
                    items.append(att)
        items.sort(key=lambda a: a.created_at, reverse=True)
        return items[:limit]

    def find(self, ref: str) -> Optional[Attachment]:
        """Resolve an id, an exact file name, or part of a name (newest first)."""
        ref = (ref or "").strip()
        if not ref:
            return None
        if _ID.match(ref):
            return self.get(ref)
        items = self.list(limit=10_000)
        low = ref.lower()
        for att in items:
            if att.name.lower() == low:
                return att
        for att in items:
            if low in att.name.lower():
                return att
        return None

    def text(self, att_id: str) -> str:
        try:
            return (self._dir(att_id) / "text.txt").read_text(encoding="utf-8")
        except (OSError, AttachmentError):
            return ""

    def file_bytes(self, att_id: str) -> Optional[bytes]:
        att = self.get(att_id)
        if att is None:
            return None
        with self._lock:
            return self._blobs.get_content(att.sha256)

    # -- update / delete ----------------------------------------------------------

    def mark_in_knowledge(self, att_id: str, doc_id: str) -> None:
        att = self.get(att_id)
        if att is not None:
            att.knowledge_doc_id = doc_id
            self._save(att)

    def delete(self, att_id: str) -> bool:
        att = self.get(att_id)
        if att is None:
            return False
        with self._lock:
            self._blobs.release(att.sha256, _SOURCE_PREFIX + att_id)
        shutil.rmtree(self._dir(att_id), ignore_errors=True)
        return True

    # -- chat context ---------------------------------------------------------------

    def context_for(
        self, att_ids: Iterable[str], *, budget_chars: int = DEFAULT_CONTEXT_CHARS
    ) -> str:
        """A text block describing the given attachments for a chat message.

        The budget is shared between attachments; anything cut is marked so the
        model knows it can call ``read_attachment`` for the rest.
        """
        atts = [a for a in (self.get(i) for i in att_ids) if a is not None]
        if not atts:
            return ""
        share = max(1500, budget_chars // len(atts))
        blocks = ["The user attached the following files:"]
        for att in atts:
            head = f'[Attachment {att.id}: "{att.name}" ({att.kind}'
            if att.pages and att.kind == "document":
                unit = "sheet" if att.name.lower().endswith(".xlsx") else "page"
                head += f", {att.pages} {unit}{'s' if att.pages != 1 else ''}"
            head += ")]"
            body = self.text(att.id).strip()
            if att.kind == "image":
                if att.status == "describing":
                    body = (
                        "(The image is still being analysed; "
                        "its description is not ready yet.)"
                    )
                elif not body:
                    body = "(No description available for this image.)"
                else:
                    body = "Image description:\n" + body
            elif not body:
                body = f"(No readable text: {att.error or 'empty file'})"
            if len(body) > share:
                body = (
                    body[:share]
                    + f"\n… [truncated - {len(body) - share} more characters; "
                    f'call read_attachment("{att.id}") with an offset to read on]'
                )
            blocks.append(f"{head}\n{body}")
        return "\n\n".join(blocks)


_LIBRARY: Optional[AttachmentLibrary] = None
_LIBRARY_LOCK = threading.Lock()


def get_attachment_library() -> AttachmentLibrary:
    global _LIBRARY
    with _LIBRARY_LOCK:
        if _LIBRARY is None:
            _LIBRARY = AttachmentLibrary()
        return _LIBRARY


def make_vision_describer(engine, model: str) -> Describer:
    """Describe images with a vision-capable model through *engine*."""
    import base64

    def describe(data: bytes, mime: str) -> str:
        from openjarvis.core.types import Message, Role

        prompt = (
            "Describe this image for an assistant that cannot see it. First give a "
            "one-sentence summary. Then transcribe ALL visible text exactly (keep "
            "numbers, names and amounts). Then note important details (people, "
            "objects, charts, UI elements, errors). Do not guess what is not visible."
        )
        result = engine.generate(
            [
                Message(
                    role=Role.USER,
                    content=prompt,
                    images=[base64.b64encode(data).decode("ascii")],
                )
            ],
            model=model,
            temperature=0.1,
            max_tokens=2048,
        )
        text = str(result.get("content") or "")
        return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    return describe


__all__ = [
    "Attachment",
    "AttachmentError",
    "AttachmentLibrary",
    "MAX_FILE_BYTES",
    "get_attachment_library",
    "make_vision_describer",
]
