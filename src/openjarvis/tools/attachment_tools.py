"""Tools for working with the attachment library.

* ``list_attachments`` - what the user has attached (newest first)
* ``read_attachment`` - read an attachment's text / image description in pages
* ``save_attachment_to_knowledge`` - add it to the searchable knowledge base

Attachments can be referred to by id or by (part of) their file name, so a
routine can say "summarise the latest invoice.pdf".
"""

from __future__ import annotations

import uuid
from typing import Any

from openjarvis.core.registry import ToolRegistry
from openjarvis.core.types import ToolResult
from openjarvis.tools._stubs import BaseTool, ToolSpec

_PAGE_CHARS = 8000


def _lib():
    from openjarvis.attachments.library import get_attachment_library

    return get_attachment_library()


@ToolRegistry.register("list_attachments")
class ListAttachmentsTool(BaseTool):
    tool_id = "list_attachments"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="list_attachments",
            description=(
                "List files and images the user has attached to Jarvis "
                "(newest first), with id, name, type and date. Use before "
                "read_attachment when the user refers to an earlier attachment."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Optional part of a file name to filter by.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max items (default 15).",
                    },
                },
            },
            category="attachments",
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        query = str(params.get("query") or "").strip().lower()
        try:
            limit = max(1, min(50, int(params.get("limit") or 15)))
        except (TypeError, ValueError):
            limit = 15
        items = [
            a for a in _lib().list(limit=500) if not query or query in a.name.lower()
        ]
        if not items:
            return ToolResult(
                tool_name="list_attachments",
                content="No attachments found.",
                success=True,
            )
        lines = [
            f"- {a.id} | {a.name} | {a.kind} | {a.created_at[:16].replace('T', ' ')} UTC"
            + (" | in knowledge base" if a.knowledge_doc_id else "")
            for a in items[:limit]
        ]
        return ToolResult(
            tool_name="list_attachments", content="\n".join(lines), success=True
        )


@ToolRegistry.register("read_attachment")
class ReadAttachmentTool(BaseTool):
    tool_id = "read_attachment"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="read_attachment",
            description=(
                "Read the text of an attachment (documents) or its description "
                "(images), by id or file name. Long files are returned in pages: "
                "pass the offset from the previous result to continue."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "attachment": {
                        "type": "string",
                        "description": "Attachment id or (part of) its file name.",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Character offset to start from (default 0).",
                    },
                },
                "required": ["attachment"],
            },
            category="attachments",
            timeout_seconds=15.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        lib = _lib()
        att = lib.find(str(params.get("attachment") or ""))
        if att is None:
            return ToolResult(
                tool_name="read_attachment",
                content="No such attachment. Use list_attachments to see what exists.",
                success=False,
            )
        text = lib.text(att.id)
        if not text.strip():
            reason = att.error or (
                "the image is still being analysed"
                if att.status == "describing"
                else "it has no readable text"
            )
            return ToolResult(
                tool_name="read_attachment",
                content=f"{att.name}: nothing to read ({reason}).",
                success=False,
            )
        try:
            offset = max(0, int(params.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        page = text[offset : offset + _PAGE_CHARS]
        end = offset + len(page)
        footer = (
            f"\n\n[{end} of {len(text)} characters shown; call read_attachment "
            f"with offset={end} to continue]"
            if end < len(text)
            else "\n\n[end of attachment]"
        )
        return ToolResult(
            tool_name="read_attachment",
            content=f'Attachment {att.id} "{att.name}" ({att.kind}):\n{page}{footer}',
            success=True,
        )


@ToolRegistry.register("save_attachment_to_knowledge")
class SaveAttachmentToKnowledgeTool(BaseTool):
    tool_id = "save_attachment_to_knowledge"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="save_attachment_to_knowledge",
            description=(
                "Add an attachment's text to Jarvis's long-term searchable "
                "knowledge base (use when the user says to remember a document)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "attachment": {
                        "type": "string",
                        "description": "Attachment id or (part of) its file name.",
                    }
                },
                "required": ["attachment"],
            },
            category="attachments",
            timeout_seconds=60.0,
        )

    def execute(self, **params: Any) -> ToolResult:
        name = "save_attachment_to_knowledge"
        lib = _lib()
        att = lib.find(str(params.get("attachment") or ""))
        if att is None:
            return ToolResult(
                tool_name=name, content="No such attachment.", success=False
            )
        if att.knowledge_doc_id:
            return ToolResult(
                tool_name=name,
                content=f"{att.name} is already in the knowledge base.",
                success=True,
            )
        text = lib.text(att.id).strip()
        if not text:
            return ToolResult(
                tool_name=name,
                content=f"{att.name} has no readable text to save.",
                success=False,
            )
        from openjarvis.server.upload_router import _chunk_text, _get_store

        store = _get_store()
        doc_id = str(uuid.uuid4())
        chunks = _chunk_text(text)
        for idx, chunk in enumerate(chunks):
            store.store(
                chunk,
                source="attachment",
                doc_type=att.name.rsplit(".", 1)[-1].lower(),
                doc_id=doc_id,
                title=att.name,
                chunk_index=idx,
            )
        lib.mark_in_knowledge(att.id, doc_id)
        return ToolResult(
            tool_name=name,
            content=f"Saved {att.name} to the knowledge base ({len(chunks)} sections).",
            success=True,
        )


__all__ = [
    "ListAttachmentsTool",
    "ReadAttachmentTool",
    "SaveAttachmentToKnowledgeTool",
]
