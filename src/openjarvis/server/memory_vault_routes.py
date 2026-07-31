"""Local, audited API for evidence-bound Markdown vault memory."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Annotated, Any

from openjarvis.codex.redaction import redact_data
from openjarvis.memory.candidates import candidate_to_dict
from openjarvis.memory.safe_write import ConcurrentMemoryWrite
from openjarvis.memory.task_bridge import MemoryTaskContext
from openjarvis.memory.vault_models import MemoryConflict, MemoryNote
from openjarvis.server.task_routes import _require_local, _validated_header

try:
    from fastapi import APIRouter, Header, HTTPException, Query, Request
    from pydantic import BaseModel, Field, field_validator
except ImportError:
    raise ImportError("fastapi and pydantic are required for memory routes")

router = APIRouter(prefix="/v1/memory", tags=["memory-vault"])


class CandidateRequest(BaseModel):
    body: str = Field(min_length=1, max_length=100_000)
    note_type: str = Field(default="fact", max_length=40)
    scope: str = Field(default="personal", max_length=80)
    project: str | None = Field(default=None, max_length=200)
    tags: list[str] = Field(default_factory=list, max_length=100)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    proposed_path: str | None = Field(default=None, max_length=4096)
    correction: bool = False
    conflict_key: str | None = Field(default=None, max_length=200)

    @field_validator("body")
    @classmethod
    def _body_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("body must not be blank")
        return value.strip()


class ConflictResolutionRequest(BaseModel):
    winner_note_id: str = Field(min_length=1, max_length=200)
    resolution: str = Field(min_length=1, max_length=2000)


def _service(request: Request):
    service = getattr(request.app.state, "vault_memory_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Obsidian vault memory is not configured",
        )
    return service


def _workflow(request: Request):
    workflow = getattr(_service(request), "candidate_workflow", None)
    if workflow is None:
        raise HTTPException(
            status_code=503,
            detail="Memory candidate workflow is not configured",
        )
    return workflow


def _context(
    request: Request,
    *,
    task_id: str,
    session_id: str,
    correlation_id: str,
    thread_id: str | None,
    turn_id: str | None,
) -> MemoryTaskContext:
    _require_local(request)
    context = MemoryTaskContext(
        task_id=_validated_header(task_id, "X-Task-ID"),
        session_id=_validated_header(session_id, "X-Session-ID"),
        correlation_id=_validated_header(correlation_id, "X-Correlation-ID"),
        thread_id=(_validated_header(thread_id, "X-Thread-ID") if thread_id else None),
        turn_id=_validated_header(turn_id, "X-Turn-ID") if turn_id else None,
    )
    bridge = getattr(_service(request), "task_bridge", None)
    if bridge is None:
        raise HTTPException(
            status_code=503,
            detail="Memory task correlation is not configured",
        )
    try:
        bridge.validate(context)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return context


def _mutation(
    request: Request,
    *,
    task_id: str,
    session_id: str,
    correlation_id: str,
    idempotency_key: str,
    thread_id: str | None,
    turn_id: str | None,
) -> tuple[MemoryTaskContext, str]:
    context = _context(
        request,
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
        thread_id=thread_id,
        turn_id=turn_id,
    )
    return context, _validated_header(idempotency_key, "Idempotency-Key")


@router.get("/health")
async def memory_health(request: Request) -> dict[str, Any]:
    _require_local(request)
    service = getattr(request.app.state, "vault_memory_service", None)
    if service is None:
        return {
            "vault_configured": False,
            "vault_reachable": False,
            "mode": "unconfigured",
            "index_available": False,
            "fts5_available": False,
            "note_count": 0,
            "parser_error_count": 0,
            "last_successful_index": None,
            "last_error": None,
            "embeddings_enabled": False,
            "retrieval_mode": "fts5_bm25",
            "open_candidates": 0,
            "open_conflicts": 0,
            "discovered_count": 0,
            "frontmatter_parsed_count": 0,
            "schema_valid_count": 0,
            "type_supported_count": 0,
            "fts_document_count": 0,
            "retrieval_eligible_count": 0,
            "review_only_count": 0,
            "structural_count": 0,
            "authority_sensitive_count": 0,
            "rejected_count": 0,
        }
    return asdict(service.health())


@router.get("/search")
async def memory_search(
    request: Request,
    task_id: Annotated[str, Header(alias="X-Task-ID")],
    session_id: Annotated[str, Header(alias="X-Session-ID")],
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")],
    query: str = Query(min_length=1, max_length=20_000),
    top_k: int = Query(default=5, ge=1, le=25),
    note_type: str | None = None,
    status: str = "active",
    scope: str | None = None,
    project: str | None = None,
    tags: list[str] = Query(default_factory=list),
    since: str | None = None,
    until: str | None = None,
    include_archived: bool = False,
    thread_id: Annotated[str | None, Header(alias="X-Thread-ID")] = None,
    turn_id: Annotated[str | None, Header(alias="X-Turn-ID")] = None,
) -> dict[str, Any]:
    context = _context(
        request,
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
        thread_id=thread_id,
        turn_id=turn_id,
    )
    filters = {
        "note_type": note_type,
        "status": status,
        "scope": scope,
        "project": project,
        "tags": tags,
        "since": since,
        "until": until,
        "include_archived": include_archived,
    }
    result = _service(request).search(
        query,
        top_k=top_k,
        filters={key: value for key, value in filters.items() if value is not None},
        context=context,
    )
    return _retrieval_dict(result)


@router.get("/review/search")
async def memory_review_search(
    request: Request,
    query: str = Query(min_length=1, max_length=20_000),
    top_k: int = Query(default=5, ge=1, le=25),
    note_type: str | None = None,
) -> dict[str, Any]:
    """Explicitly inspect review-only sources without task/model attachment."""

    _require_local(request)
    filters = {"note_type": note_type} if note_type is not None else {}
    return _retrieval_dict(
        _service(request).review_search(query, top_k=top_k, filters=filters)
    )


@router.get("/structure/search")
async def memory_structure_search(
    request: Request,
    query: str = Query(min_length=1, max_length=20_000),
    top_k: int = Query(default=5, ge=1, le=25),
    note_type: str | None = None,
) -> dict[str, Any]:
    """Explicitly inspect taxonomy/navigation sources outside answer context."""

    _require_local(request)
    filters = {"note_type": note_type} if note_type is not None else {}
    return _retrieval_dict(
        _service(request).structure_search(query, top_k=top_k, filters=filters)
    )


@router.get("/notes/{note_id}")
async def memory_note(note_id: str, request: Request) -> dict[str, Any]:
    _require_local(request)
    note = _service(request).index.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Memory note not found")
    return _note_dict(note)


@router.get("/notes/{note_id}/links")
async def memory_note_links(note_id: str, request: Request) -> dict[str, Any]:
    _require_local(request)
    service = _service(request)
    if service.index.get_note(note_id) is None:
        raise HTTPException(status_code=404, detail="Memory note not found")
    return service.index.note_links(note_id)


@router.get("/graph")
async def memory_graph(
    request: Request,
    limit: int = Query(default=1000, ge=1, le=5000),
) -> dict[str, Any]:
    _require_local(request)
    return _service(request).index.graph(limit=limit)


@router.get("/candidates")
async def memory_candidates(
    request: Request,
    open_only: bool = True,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    _require_local(request)
    candidates = _workflow(request).list(open_only=open_only, limit=limit)
    return {
        "candidates": [candidate_to_dict(item) for item in candidates],
        "count": len(candidates),
    }


@router.get("/conflicts")
async def memory_conflicts(
    request: Request,
    open_only: bool = True,
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    _require_local(request)
    conflicts = _workflow(request).list_conflicts(
        open_only=open_only,
        limit=limit,
    )
    return {
        "conflicts": [_conflict_dict(item) for item in conflicts],
        "count": len(conflicts),
    }


@router.post("/reindex")
async def memory_reindex(
    request: Request,
    task_id: Annotated[str, Header(alias="X-Task-ID")],
    session_id: Annotated[str, Header(alias="X-Session-ID")],
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    thread_id: Annotated[str | None, Header(alias="X-Thread-ID")] = None,
    turn_id: Annotated[str | None, Header(alias="X-Turn-ID")] = None,
) -> dict[str, Any]:
    context, key = _mutation(
        request,
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        thread_id=thread_id,
        turn_id=turn_id,
    )
    service = _service(request)
    cached = _load_api_operation(service, context.task_id, "reindex", key)
    if cached is not None:
        return {**cached, "idempotent_replay": True}
    report = service.rebuild(context=context)
    result = asdict(report)
    _save_api_operation(service, context.task_id, "reindex", key, result)
    return {**result, "idempotent_replay": False}


@router.post("/candidates", status_code=201)
async def create_memory_candidate(
    body: CandidateRequest,
    request: Request,
    task_id: Annotated[str, Header(alias="X-Task-ID")],
    session_id: Annotated[str, Header(alias="X-Session-ID")],
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    thread_id: Annotated[str | None, Header(alias="X-Thread-ID")] = None,
    turn_id: Annotated[str | None, Header(alias="X-Turn-ID")] = None,
) -> dict[str, Any]:
    context, key = _mutation(
        request,
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        thread_id=thread_id,
        turn_id=turn_id,
    )
    try:
        candidate = _service(request).create_candidate(
            context,
            **body.model_dump(),
            idempotency_key=key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return candidate_to_dict(candidate)


@router.post("/candidates/{candidate_id}/approve")
async def approve_memory_candidate(
    candidate_id: str,
    request: Request,
    task_id: Annotated[str, Header(alias="X-Task-ID")],
    session_id: Annotated[str, Header(alias="X-Session-ID")],
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    thread_id: Annotated[str | None, Header(alias="X-Thread-ID")] = None,
    turn_id: Annotated[str | None, Header(alias="X-Turn-ID")] = None,
) -> dict[str, Any]:
    context, key = _mutation(
        request,
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        thread_id=thread_id,
        turn_id=turn_id,
    )
    workflow = _workflow(request)
    candidate = workflow.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Memory candidate not found")
    if candidate.task_id != context.task_id:
        raise HTTPException(status_code=409, detail="Candidate belongs to another task")
    if _service(request).index.mode != "writable-test":
        raise HTTPException(
            status_code=403,
            detail="Memory writes are disabled outside writable-test mode",
        )
    try:
        applied = workflow.decide(candidate_id, allow=True, decision_id=key)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, ConcurrentMemoryWrite) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return candidate_to_dict(applied)


@router.post("/candidates/{candidate_id}/reject")
async def reject_memory_candidate(
    candidate_id: str,
    request: Request,
    task_id: Annotated[str, Header(alias="X-Task-ID")],
    session_id: Annotated[str, Header(alias="X-Session-ID")],
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    thread_id: Annotated[str | None, Header(alias="X-Thread-ID")] = None,
    turn_id: Annotated[str | None, Header(alias="X-Turn-ID")] = None,
) -> dict[str, Any]:
    context, key = _mutation(
        request,
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        thread_id=thread_id,
        turn_id=turn_id,
    )
    workflow = _workflow(request)
    candidate = workflow.get(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Memory candidate not found")
    if candidate.task_id != context.task_id:
        raise HTTPException(status_code=409, detail="Candidate belongs to another task")
    try:
        rejected = workflow.decide(candidate_id, allow=False, decision_id=key)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return candidate_to_dict(rejected)


@router.post("/conflicts/{conflict_id}/resolve")
async def resolve_memory_conflict(
    conflict_id: str,
    body: ConflictResolutionRequest,
    request: Request,
    task_id: Annotated[str, Header(alias="X-Task-ID")],
    session_id: Annotated[str, Header(alias="X-Session-ID")],
    correlation_id: Annotated[str, Header(alias="X-Correlation-ID")],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    thread_id: Annotated[str | None, Header(alias="X-Thread-ID")] = None,
    turn_id: Annotated[str | None, Header(alias="X-Turn-ID")] = None,
) -> dict[str, Any]:
    context, key = _mutation(
        request,
        task_id=task_id,
        session_id=session_id,
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        thread_id=thread_id,
        turn_id=turn_id,
    )
    service = _service(request)
    operation = f"conflict.resolve:{conflict_id}"
    cached = _load_api_operation(service, context.task_id, operation, key)
    if cached is not None:
        return cached
    try:
        conflict = _workflow(request).resolve_conflict(
            conflict_id,
            winner_note_id=body.winner_note_id,
            resolution=body.resolution,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result = _conflict_dict(conflict)
    _save_api_operation(service, context.task_id, operation, key, result)
    return result


def _note_dict(note: MemoryNote) -> dict[str, Any]:
    data = asdict(note)
    data["conflict_state"] = note.conflict_state.value
    data["identity_kind"] = note.identity_kind.value
    data["trust_class"] = note.trust_class.value
    data["retrieval_class"] = note.retrieval_class.value
    data["authority_class"] = note.authority_class.value
    data["scope_class"] = note.scope_class.value
    data["parse_status"] = note.parse_status
    return data


def _conflict_dict(conflict: MemoryConflict) -> dict[str, Any]:
    data = asdict(conflict)
    data["state"] = conflict.state.value
    return data


def _retrieval_dict(result) -> dict[str, Any]:
    return {
        "retrieval_id": result.retrieval_id,
        "query": result.query,
        "normalized_query": result.normalized_query,
        "candidates": [
            {
                **asdict(candidate),
                "conflict_state": candidate.conflict_state.value,
            }
            for candidate in result.candidates
        ],
        "selected_sources": [asdict(source) for source in result.selected_sources],
        "confidence": result.confidence,
        "evidence_status": result.evidence_status.value,
        "evidence_code": result.evidence_code,
        "retrieval_method": result.retrieval_method,
        "retrieval_purpose": result.retrieval_purpose,
        "filters": dict(result.filters),
        "warnings": list(result.warnings),
    }


def _operation_key(task_id: str, operation: str, key: str) -> str:
    return f"{task_id}:{operation}:{key}"


def _load_api_operation(
    service,
    task_id: str,
    operation: str,
    key: str,
) -> dict[str, Any] | None:
    row = service.index.connection.execute(
        "SELECT result FROM memory_api_operations WHERE operation_key=?",
        (_operation_key(task_id, operation, key),),
    ).fetchone()
    return json.loads(row["result"]) if row else None


def _save_api_operation(
    service,
    task_id: str,
    operation: str,
    key: str,
    result: dict[str, Any],
) -> None:
    with service.index.connection:
        service.index.connection.execute(
            """
            INSERT OR IGNORE INTO memory_api_operations (
                operation_key, operation, task_id, result, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                _operation_key(task_id, operation, key),
                operation,
                task_id,
                json.dumps(redact_data(result), ensure_ascii=False, sort_keys=True),
                datetime.now(timezone.utc).isoformat(),
            ),
        )


__all__ = ["router"]
