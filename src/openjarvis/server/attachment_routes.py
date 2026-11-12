"""REST API for attachments (``/v1/attachments``), used by the HUD.

* ``POST   /v1/attachments``                 upload one or more files (multipart)
* ``GET    /v1/attachments``                 list, newest first
* ``GET    /v1/attachments/{id}``            details + text preview
* ``GET    /v1/attachments/{id}/file``       the original file (for preview)
* ``GET    /v1/attachments/{id}/text``       extracted text / image description
* ``POST   /v1/attachments/{id}/knowledge``  add to the searchable knowledge base
* ``DELETE /v1/attachments/{id}``            remove it

Chat messages reference attachments by id (``attachments`` on the chat
request); see ``routes.chat_completions``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/attachments", tags=["attachments"])

_PREVIEW_CHARS = 2000
_MAX_FILES_PER_UPLOAD = 10


def library_for(request: Request):
    """The attachment library, with the image describer wired to the engine."""
    from openjarvis.attachments.library import (
        get_attachment_library,
        make_vision_describer,
    )

    lib = get_attachment_library()
    state = request.app.state
    if not getattr(state, "_attachment_describer_ready", False):
        engine = getattr(state, "engine", None)
        model = os.environ.get("OPENJARVIS_VISION_MODEL", "").strip() or getattr(
            state, "model", ""
        )
        if engine is not None and model:
            lib.set_describer(make_vision_describer(engine, model))
        state._attachment_describer_ready = True
    return lib


def _summary(att) -> Dict[str, Any]:
    data = att.to_dict()
    data.pop("sha256", None)
    data.pop("extra", None)
    return data


def _get_or_404(lib, att_id: str):
    att = lib.get(att_id)
    if att is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return att


@router.post("")
async def upload_attachments(
    request: Request,
    files: List[UploadFile] = File(...),
    source: str = Form("upload"),
) -> Dict[str, Any]:
    from openjarvis.attachments.library import AttachmentError

    if len(files) > _MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status_code=400,
            detail=f"Attach at most {_MAX_FILES_PER_UPLOAD} files at once.",
        )
    lib = library_for(request)
    if source not in ("upload", "paste", "drop", "screenshot"):
        source = "upload"
    created, errors = [], []
    for upload in files:
        data = await upload.read()
        try:
            att = await asyncio.to_thread(
                lib.add,
                data,
                upload.filename or "attachment",
                mime=upload.content_type or "",
                source=source,
            )
            created.append(_summary(att))
        except AttachmentError as exc:
            errors.append({"name": upload.filename, "error": str(exc)})
    if not created and errors:
        raise HTTPException(status_code=400, detail=errors[0]["error"])
    return {"attachments": created, "errors": errors}


@router.get("")
async def list_attachments(request: Request, limit: int = 100) -> Dict[str, Any]:
    lib = library_for(request)
    return {"attachments": [_summary(a) for a in lib.list(limit=max(1, min(500, limit)))]}


@router.get("/{att_id}")
async def get_attachment(att_id: str, request: Request) -> Dict[str, Any]:
    lib = library_for(request)
    data = _summary(_get_or_404(lib, att_id))
    data["preview"] = lib.text(att_id)[:_PREVIEW_CHARS]
    return data


@router.get("/{att_id}/file")
async def get_attachment_file(att_id: str, request: Request) -> Response:
    lib = library_for(request)
    att = _get_or_404(lib, att_id)
    data = lib.file_bytes(att_id)
    if data is None:
        raise HTTPException(status_code=404, detail="File content missing")
    safe_name = att.name.replace('"', "")
    return Response(
        content=data,
        media_type=att.mime,
        headers={
            "Content-Disposition": f'inline; filename="{safe_name}"',
            "X-Content-Type-Options": "nosniff",
            # Never let an uploaded HTML/SVG file run scripts in the app origin.
            "Content-Security-Policy": "sandbox",
        },
    )


@router.get("/{att_id}/text")
async def get_attachment_text(
    att_id: str, request: Request, offset: int = 0, limit: int = 20000
) -> Dict[str, Any]:
    lib = library_for(request)
    _get_or_404(lib, att_id)
    text = lib.text(att_id)
    offset = max(0, offset)
    limit = max(1, min(100_000, limit))
    return {
        "id": att_id,
        "offset": offset,
        "total_chars": len(text),
        "text": text[offset : offset + limit],
    }


@router.post("/{att_id}/knowledge")
async def save_to_knowledge(att_id: str, request: Request) -> Dict[str, Any]:
    lib = library_for(request)
    att = _get_or_404(lib, att_id)
    if att.knowledge_doc_id:
        return {"id": att_id, "knowledge_doc_id": att.knowledge_doc_id, "chunks": 0}
    text = lib.text(att_id).strip()
    if not text:
        raise HTTPException(
            status_code=400, detail="This attachment has no readable text to save yet."
        )
    from openjarvis.server.upload_router import _chunk_text, _get_store

    def _ingest() -> int:
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
        lib.mark_in_knowledge(att_id, doc_id)
        return len(chunks)

    count = await asyncio.to_thread(_ingest)
    updated = lib.get(att_id)
    return {
        "id": att_id,
        "knowledge_doc_id": updated.knowledge_doc_id if updated else None,
        "chunks": count,
    }


@router.delete("/{att_id}")
async def delete_attachment(att_id: str, request: Request) -> Dict[str, str]:
    lib = library_for(request)
    _get_or_404(lib, att_id)
    await asyncio.to_thread(lib.delete, att_id)
    return {"status": "deleted", "id": att_id}


__all__ = ["library_for", "router"]
