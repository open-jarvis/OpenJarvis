"""Strict immutable contracts for the Phase-8B website-staging pilot."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_DIGEST = r"^[0-9a-f]{64}$"
_IDENTIFIER = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$"
_MEDIA_TYPE = r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$"
_DRIVE_PREFIX = re.compile(r"^[A-Za-z]:")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")


def sha256_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def safe_relative_path(value: str) -> str:
    """Return one canonical POSIX path or reject before any filesystem use."""

    if not isinstance(value, str):
        raise TypeError("website path must be a string")
    if value != value.strip() or not value or "\x00" in value:
        raise ValueError("website path must be non-empty and canonical")
    if "\\" in value or _DRIVE_PREFIX.match(value):
        raise ValueError("absolute or Windows-style website paths are forbidden")
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("/"):
        raise ValueError("absolute website paths are forbidden")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("website path traversal is forbidden")
    if any(part.startswith(".") for part in path.parts):
        raise ValueError("hidden website paths are forbidden")
    if path.as_posix() != value:
        raise ValueError("website path must use canonical POSIX separators")
    return value


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        str_strip_whitespace=False,
    )


class WebsiteOperation(str, Enum):
    CREATE_STATIC_SITE = "create_static_site"
    UPDATE_STATIC_SITE = "update_static_site"
    PREVIEW_DIFF = "preview_diff"
    VALIDATE_STATIC_SITE = "validate_static_site"
    PACKAGE_ARTIFACT = "package_artifact"
    ROLLBACK_STAGING = "rollback_staging"


class WebsiteOverwritePolicy(str, Enum):
    DENY = "deny"
    REPLACE_IF_UNCHANGED = "replace_if_unchanged"


class WebsiteVerificationPolicy(str, Enum):
    STRICT_STATIC = "strict_static"


class WebsiteChangeKind(str, Enum):
    CREATED = "created"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


class WebsiteVerificationStatus(str, Enum):
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class WebsiteExecutionStatus(str, Enum):
    COMPLETED = "completed"
    NOOP = "noop"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class WebsiteExpectedFileType(StrictFrozenModel):
    relative_path: str
    media_type: str = Field(pattern=_MEDIA_TYPE)

    _path = field_validator("relative_path")(safe_relative_path)


class _WebsiteStagingRequestPayload(StrictFrozenModel):
    request_id: str = Field(pattern=_IDENTIFIER)
    task_id: str = Field(pattern=_IDENTIFIER)
    session_id: str = Field(pattern=_IDENTIFIER)
    correlation_id: str = Field(pattern=_IDENTIFIER)
    workspace_id: str = Field(pattern=_IDENTIFIER)
    operation: WebsiteOperation
    allowed_source_files: tuple[str, ...]
    requested_output_files: tuple[str, ...]
    expected_file_types: tuple[WebsiteExpectedFileType, ...]
    maximum_files: int = Field(gt=0, le=128)
    maximum_total_bytes: int = Field(gt=0, le=5_242_880)
    overwrite_policy: WebsiteOverwritePolicy
    verification_policy: WebsiteVerificationPolicy
    idempotency_key: str = Field(pattern=_IDENTIFIER)
    created_at: datetime

    @field_validator("allowed_source_files", "requested_output_files")
    @classmethod
    def _paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        validated = tuple(safe_relative_path(value) for value in values)
        if len(set(validated)) != len(validated):
            raise ValueError("website file paths must be unique")
        if validated != tuple(sorted(validated, key=str.casefold)):
            raise ValueError("website file paths must be canonically sorted")
        return validated

    @field_validator("created_at")
    @classmethod
    def _created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must include a UTC offset")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _file_contract(self) -> Self:
        outputs = set(self.requested_output_files)
        types = tuple(item.relative_path for item in self.expected_file_types)
        if len(set(types)) != len(types):
            raise ValueError("expected_file_types paths must be unique")
        if tuple(sorted(types, key=str.casefold)) != types:
            raise ValueError("expected_file_types must be canonically sorted")
        if set(types) != outputs:
            raise ValueError("expected_file_types must cover requested output files")
        expected_after = set(self.allowed_source_files) | outputs
        if len(expected_after) > self.maximum_files:
            raise ValueError("requested files exceed maximum_files")
        if self.operation is WebsiteOperation.CREATE_STATIC_SITE and (
            self.allowed_source_files
        ):
            raise ValueError("create_static_site requires an empty source set")
        return self


class WebsiteStagingRequest(_WebsiteStagingRequestPayload):
    request_hash: str = Field(pattern=_DIGEST)

    @classmethod
    def create(cls, **values: Any) -> Self:
        payload = _WebsiteStagingRequestPayload(**values)
        digest = sha256_payload(payload.model_dump(mode="json"))
        return cls(**payload.model_dump(), request_hash=digest)

    @model_validator(mode="after")
    def _hash_is_bound(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"request_hash"})
        if self.request_hash != sha256_payload(payload):
            raise ValueError("request_hash does not match the request")
        return self


class WebsiteFileProposal(StrictFrozenModel):
    relative_path: str
    media_type: str = Field(pattern=_MEDIA_TYPE)
    content_text: str | None = None
    content_base64: str | None = None
    size_bytes: int = Field(ge=0, le=5_242_880)
    proposed_sha256: str = Field(pattern=_DIGEST)
    expected_before_sha256: str | None = Field(default=None, pattern=_DIGEST)

    _path = field_validator("relative_path")(safe_relative_path)

    def content_bytes(self) -> bytes:
        if self.content_text is not None:
            return self.content_text.encode("utf-8")
        assert self.content_base64 is not None
        return base64.b64decode(self.content_base64, validate=True)

    @classmethod
    def from_text(
        cls,
        *,
        relative_path: str,
        media_type: str,
        content: str,
        expected_before_sha256: str | None = None,
    ) -> Self:
        encoded = content.encode("utf-8")
        return cls(
            relative_path=relative_path,
            media_type=media_type,
            content_text=content,
            size_bytes=len(encoded),
            proposed_sha256=hashlib.sha256(encoded).hexdigest(),
            expected_before_sha256=expected_before_sha256,
        )

    @classmethod
    def from_bytes(
        cls,
        *,
        relative_path: str,
        media_type: str,
        content: bytes,
        expected_before_sha256: str | None = None,
    ) -> Self:
        return cls(
            relative_path=relative_path,
            media_type=media_type,
            content_base64=base64.b64encode(content).decode("ascii"),
            size_bytes=len(content),
            proposed_sha256=hashlib.sha256(content).hexdigest(),
            expected_before_sha256=expected_before_sha256,
        )

    @model_validator(mode="after")
    def _content_is_bound(self) -> Self:
        if (self.content_text is None) == (self.content_base64 is None):
            raise ValueError("exactly one proposal content representation is required")
        try:
            content = self.content_bytes()
        except (ValueError, TypeError) as exc:
            raise ValueError("content_base64 is invalid") from exc
        if len(content) != self.size_bytes:
            raise ValueError("proposal size does not match content")
        if hashlib.sha256(content).hexdigest() != self.proposed_sha256:
            raise ValueError("proposal hash does not match content")
        return self


class WebsiteFileState(StrictFrozenModel):
    relative_path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=_DIGEST)
    media_type: str = Field(pattern=_MEDIA_TYPE)

    _path = field_validator("relative_path")(safe_relative_path)


class WebsiteFileDiff(StrictFrozenModel):
    relative_path: str
    change: WebsiteChangeKind
    before_sha256: str | None = Field(default=None, pattern=_DIGEST)
    after_sha256: str = Field(pattern=_DIGEST)
    size_bytes: int = Field(ge=0)

    _path = field_validator("relative_path")(safe_relative_path)


class WebsiteStagingPlan(StrictFrozenModel):
    plan_id: str = Field(pattern=_IDENTIFIER)
    request: WebsiteStagingRequest
    proposals: tuple[WebsiteFileProposal, ...]
    before_files: tuple[WebsiteFileState, ...]
    after_files: tuple[WebsiteFileState, ...]
    file_diffs: tuple[WebsiteFileDiff, ...]
    before_manifest_sha256: str = Field(pattern=_DIGEST)
    predicted_manifest_sha256: str = Field(pattern=_DIGEST)
    risk_level: int = Field(ge=0, le=4)
    warnings: tuple[str, ...] = ()
    external_urls: tuple[str, ...] = ()
    script_files: tuple[str, ...] = ()
    predicted_total_bytes: int = Field(ge=0)
    created_at: datetime
    preview_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _preview_is_bound(self) -> Self:
        paths = tuple(item.relative_path for item in self.proposals)
        if paths != self.request.requested_output_files:
            raise ValueError("proposals must exactly match requested output files")
        payload = self.model_dump(mode="json", exclude={"preview_hash"})
        if self.preview_hash != sha256_payload(payload):
            raise ValueError("preview_hash does not match the plan")
        return self


class WebsiteArtifactEntry(StrictFrozenModel):
    artifact_id: str = Field(pattern=_IDENTIFIER)
    workspace_id: str = Field(pattern=_IDENTIFIER)
    request_id: str = Field(pattern=_IDENTIFIER)
    task_id: str = Field(pattern=_IDENTIFIER)
    relative_path: str
    media_type: str = Field(pattern=_MEDIA_TYPE)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=_DIGEST)
    source_class: str = Field(pattern=r"^(synthetic_fixture|website_proposal)$")
    created_or_modified: WebsiteChangeKind
    verification_status: WebsiteVerificationStatus
    warnings: tuple[str, ...] = ()
    created_at: datetime

    _path = field_validator("relative_path")(safe_relative_path)


class WebsiteArtifactManifest(StrictFrozenModel):
    workspace_id: str = Field(pattern=_IDENTIFIER)
    request_id: str = Field(pattern=_IDENTIFIER)
    task_id: str = Field(pattern=_IDENTIFIER)
    artifacts: tuple[WebsiteArtifactEntry, ...]
    created_at: datetime
    manifest_sha256: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _manifest_is_bound(self) -> Self:
        paths = tuple(item.relative_path for item in self.artifacts)
        if paths != tuple(sorted(paths, key=str.casefold)) or len(set(paths)) != len(
            paths
        ):
            raise ValueError("artifact paths must be canonical and unique")
        payload = self.model_dump(mode="json", exclude={"manifest_sha256"})
        if self.manifest_sha256 != sha256_payload(payload):
            raise ValueError("manifest_sha256 does not match artifacts")
        return self


class WebsiteVerificationResult(StrictFrozenModel):
    workspace_id: str = Field(pattern=_IDENTIFIER)
    request_id: str = Field(pattern=_IDENTIFIER)
    status: WebsiteVerificationStatus
    passed: bool
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    manifest_sha256: str = Field(pattern=_DIGEST)
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    checked_at: datetime
    verification_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _verification_is_consistent(self) -> Self:
        if self.passed != (self.status is WebsiteVerificationStatus.PASSED):
            raise ValueError("passed must represent a fully passed verification")
        if self.errors and self.status is not WebsiteVerificationStatus.FAILED:
            raise ValueError("verification errors require failed status")
        if (
            self.warnings
            and not self.errors
            and self.status is not WebsiteVerificationStatus.WARNING
        ):
            raise ValueError("warning-only verification must use warning status")
        payload = self.model_dump(mode="json", exclude={"verification_hash"})
        if self.verification_hash != sha256_payload(payload):
            raise ValueError("verification_hash does not match the result")
        return self


class WebsiteStagingExecution(StrictFrozenModel):
    execution_id: str = Field(pattern=_IDENTIFIER)
    workspace_id: str = Field(pattern=_IDENTIFIER)
    request_id: str = Field(pattern=_IDENTIFIER)
    task_id: str = Field(pattern=_IDENTIFIER)
    action_id: str = Field(pattern=_IDENTIFIER)
    preview_hash: str = Field(pattern=_DIGEST)
    before_manifest_sha256: str = Field(pattern=_DIGEST)
    after_manifest_sha256: str = Field(pattern=_DIGEST)
    artifact_manifest_sha256: str = Field(pattern=_DIGEST)
    verification_hash: str = Field(pattern=_DIGEST)
    restore_id: str = Field(pattern=_IDENTIFIER)
    status: WebsiteExecutionStatus
    no_op: bool
    trace_evaluation_hash: str | None = Field(default=None, pattern=_DIGEST)
    created_at: datetime


class WebsiteRollbackRecord(StrictFrozenModel):
    rollback_id: str = Field(pattern=_IDENTIFIER)
    workspace_id: str = Field(pattern=_IDENTIFIER)
    request_id: str = Field(pattern=_IDENTIFIER)
    task_id: str = Field(pattern=_IDENTIFIER)
    action_id: str = Field(pattern=_IDENTIFIER)
    execution_id: str = Field(pattern=_IDENTIFIER)
    expected_after_manifest_sha256: str = Field(pattern=_DIGEST)
    restored_manifest_sha256: str = Field(pattern=_DIGEST)
    byte_identical: bool
    drift_detected: bool
    restore_probe_removed: bool
    created_at: datetime
    record_hash: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def _record_is_bound(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"record_hash"})
        if self.record_hash != sha256_payload(payload):
            raise ValueError("record_hash does not match rollback record")
        return self


__all__ = [
    "WebsiteArtifactEntry",
    "WebsiteArtifactManifest",
    "WebsiteChangeKind",
    "WebsiteExecutionStatus",
    "WebsiteExpectedFileType",
    "WebsiteFileDiff",
    "WebsiteFileProposal",
    "WebsiteFileState",
    "WebsiteOperation",
    "WebsiteOverwritePolicy",
    "WebsiteRollbackRecord",
    "WebsiteStagingExecution",
    "WebsiteStagingPlan",
    "WebsiteStagingRequest",
    "WebsiteVerificationPolicy",
    "WebsiteVerificationResult",
    "WebsiteVerificationStatus",
    "canonical_json",
    "safe_relative_path",
    "sha256_payload",
    "utc_now",
]
