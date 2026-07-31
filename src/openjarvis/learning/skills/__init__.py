"""Controlled Phase-7 skill lifecycle domain.

Legacy ``openjarvis.skills`` objects remain untrusted compatibility inputs.  The
types exported here are the only manifests accepted by the learning registry.
"""

from openjarvis.learning.skills.manifest import (
    DeclarativeSkillStep,
    FailureBehavior,
    ManifestSchema,
    ManifestSchemaField,
    RetryPolicy,
    RollbackKind,
    RollbackStrategy,
    SkillIdempotencyPolicy,
    SkillLifecycleStatus,
    SkillManifest,
    SkillManifestDraft,
    SkillManifestError,
    SkillMetricDefinition,
    SkillProvenance,
    VerificationKind,
    VerificationStrategy,
)
from openjarvis.learning.skills.registry import (
    SkillRegistry,
    SkillRegistryError,
    SkillVersionConflictError,
)
from openjarvis.learning.skills.registry_models import (
    RegistryDisposition,
    SkillAuditEvent,
    SkillAuditEventType,
    SkillRegistrationOutcome,
    SkillVersionHead,
    SkillVersionRecord,
)

__all__ = [
    "DeclarativeSkillStep",
    "FailureBehavior",
    "ManifestSchema",
    "ManifestSchemaField",
    "RetryPolicy",
    "RollbackKind",
    "RollbackStrategy",
    "RegistryDisposition",
    "SkillAuditEvent",
    "SkillAuditEventType",
    "SkillIdempotencyPolicy",
    "SkillLifecycleStatus",
    "SkillManifest",
    "SkillManifestDraft",
    "SkillManifestError",
    "SkillMetricDefinition",
    "SkillProvenance",
    "SkillRegistrationOutcome",
    "SkillRegistry",
    "SkillRegistryError",
    "SkillVersionConflictError",
    "SkillVersionHead",
    "SkillVersionRecord",
    "VerificationKind",
    "VerificationStrategy",
]
