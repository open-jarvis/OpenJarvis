"""Loopback-only API for the isolated website-staging pilot."""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from openjarvis.server.task_routes import _mutation_context, _require_local
from openjarvis.website import (
    WebsiteFileProposal,
    WebsiteStagingError,
    WebsiteStagingRequest,
)

router = APIRouter(prefix="/v1/website-staging", tags=["website-staging"])
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,199}$")


class WebsitePreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request: WebsiteStagingRequest
    proposals: tuple[WebsiteFileProposal, ...]


class WebsiteApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=256)
    request_id: str = Field(min_length=1, max_length=256)
    expected_preview_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["request_approval", "allow_once", "deny"] = "request_approval"


class WebsiteValidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=256)
    expected_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class WebsiteRollbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(min_length=1, max_length=256)
    execution_id: str = Field(min_length=1, max_length=256)
    expected_manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["request_approval", "allow_once", "deny"] = "request_approval"


def _service(request: Request):
    service = getattr(request.app.state, "website_staging_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Isolated website staging is unavailable",
        )
    return service


def _actor(value: Annotated[str, Header(alias="X-Actor")]) -> str:
    if not _ACTOR.fullmatch(value):
        raise HTTPException(status_code=422, detail="X-Actor is invalid")
    return value


def _plan_payload(plan) -> dict[str, Any]:
    payload = plan.model_dump(mode="json")
    payload["proposals"] = [
        {
            "relative_path": item.relative_path,
            "media_type": item.media_type,
            "size_bytes": item.size_bytes,
            "proposed_sha256": item.proposed_sha256,
            "expected_before_sha256": item.expected_before_sha256,
        }
        for item in plan.proposals
    ]
    return payload


def _identity_from_workspace(service, workspace_id: str) -> tuple[str, str]:
    record = service.workspace(workspace_id)
    try:
        request = record["plan"]["request"]
        return str(request["correlation_id"]), str(request["idempotency_key"])
    except (KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=409, detail="Workspace has no bound request"
        ) from exc


@router.post("/preview")
async def preview_website(
    body: WebsitePreviewBody,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
    actor: Annotated[str, Depends(_actor)],
) -> dict[str, Any]:
    correlation_id, idempotency_key = mutation
    if body.request.correlation_id != correlation_id:
        raise HTTPException(status_code=409, detail="Correlation-ID mismatch")
    if body.request.idempotency_key != idempotency_key:
        raise HTTPException(status_code=409, detail="Idempotency-Key mismatch")
    try:
        plan = _service(request).preview(body.request, body.proposals, actor=actor)
    except WebsiteStagingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _plan_payload(plan)


@router.post("/apply")
async def apply_website(
    body: WebsiteApplyBody,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
    actor: Annotated[str, Depends(_actor)],
) -> dict[str, Any]:
    correlation_id, idempotency_key = mutation
    service = _service(request)
    expected_correlation, expected_idempotency = _identity_from_workspace(
        service, body.workspace_id
    )
    if correlation_id != expected_correlation:
        raise HTTPException(status_code=409, detail="Correlation-ID mismatch")
    if idempotency_key != expected_idempotency:
        raise HTTPException(status_code=409, detail="Idempotency-Key mismatch")
    try:
        action, execution = await service.apply(
            workspace_id=body.workspace_id,
            request_id=body.request_id,
            expected_preview_hash=body.expected_preview_hash,
            idempotency_key=idempotency_key,
            actor=actor,
            decision=body.decision,
        )
    except WebsiteStagingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "action": action.model_dump(mode="json"),
        "execution": execution.model_dump(mode="json") if execution else None,
        "allow_once_only": True,
    }


@router.post("/validate")
async def validate_website(
    body: WebsiteValidateBody,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
    actor: Annotated[str, Depends(_actor)],
) -> dict[str, Any]:
    del actor
    correlation_id, idempotency_key = mutation
    service = _service(request)
    expected_correlation, expected_idempotency = _identity_from_workspace(
        service, body.workspace_id
    )
    if (
        correlation_id != expected_correlation
        or idempotency_key != expected_idempotency
    ):
        raise HTTPException(status_code=409, detail="Mutation identity mismatch")
    try:
        result = service.validate(body.workspace_id)
    except WebsiteStagingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result.manifest_sha256 != body.expected_manifest_hash:
        raise HTTPException(status_code=409, detail="Manifest hash mismatch")
    return result.model_dump(mode="json")


@router.post("/rollback")
async def rollback_website(
    body: WebsiteRollbackBody,
    request: Request,
    mutation: Annotated[tuple[str, str], Depends(_mutation_context)],
    actor: Annotated[str, Depends(_actor)],
) -> dict[str, Any]:
    correlation_id, idempotency_key = mutation
    service = _service(request)
    expected_correlation, expected_idempotency = _identity_from_workspace(
        service, body.workspace_id
    )
    if (
        correlation_id != expected_correlation
        or idempotency_key != expected_idempotency
    ):
        raise HTTPException(status_code=409, detail="Mutation identity mismatch")
    try:
        action, rollback = await service.rollback(
            workspace_id=body.workspace_id,
            execution_id=body.execution_id,
            expected_manifest_hash=body.expected_manifest_hash,
            idempotency_key=idempotency_key,
            actor=actor,
            decision=body.decision,
        )
    except WebsiteStagingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "action": action.model_dump(mode="json"),
        "rollback": rollback.model_dump(mode="json") if rollback else None,
        "allow_once_only": True,
    }


@router.get("/{workspace_id}")
async def get_website_workspace(workspace_id: str, request: Request) -> dict[str, Any]:
    _require_local(request)
    try:
        return _service(request).workspace(workspace_id)
    except WebsiteStagingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{workspace_id}/artifacts")
async def get_website_artifacts(workspace_id: str, request: Request) -> dict[str, Any]:
    _require_local(request)
    try:
        return _service(request).artifacts(workspace_id).model_dump(mode="json")
    except WebsiteStagingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


__all__ = ["router"]
