"""Pydantic models and enums for the distillation subsystem.

This module defines the typed vocabulary used by the diagnose, plan, execute,
and record phases. Three model families:

- Enums: pillar / risk tier / op / trigger kind / autonomy mode / session status
- Edit + LearningPlan + FailureCluster: the teacher's frozen output
- LearningSession + EditOutcome + BenchmarkSnapshot: the durable session record

See spec §4 for the data model rationale.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EditPillar(str, Enum):
    """Which OpenJarvis pillar an edit targets."""

    INTELLIGENCE = "intelligence"
    AGENT = "agent"
    TOOLS = "tools"
    ENGINE = "engine"  # designed-for; no v1 appliers ship


class EditRiskTier(str, Enum):
    """How an edit gets applied: auto, review queue, or manual-only."""

    AUTO = "auto"
    REVIEW = "review"
    MANUAL = "manual"


class EditOp(str, Enum):
    """The set of typed operations a teacher can propose.

    Each op corresponds to one EditApplier in v1 (or a refusing stub for
    deferred ops). The teacher cannot invent new ops — only choose from this
    set.
    """

    # Intelligence
    SET_MODEL_FOR_QUERY_CLASS = "set_model_for_query_class"
    SET_MODEL_PARAM = "set_model_param"

    # Agent
    PATCH_SYSTEM_PROMPT = "patch_system_prompt"
    REPLACE_SYSTEM_PROMPT = "replace_system_prompt"
    SET_AGENT_CLASS = "set_agent_class"
    SET_AGENT_PARAM = "set_agent_param"
    EDIT_FEW_SHOT_EXEMPLARS = "edit_few_shot_exemplars"

    # Tools
    ADD_TOOL_TO_AGENT = "add_tool_to_agent"
    REMOVE_TOOL_FROM_AGENT = "remove_tool_from_agent"
    EDIT_TOOL_DESCRIPTION = "edit_tool_description"

    # v2 placeholder — planner can emit, executor refuses with NotImplementedError
    LORA_FINETUNE = "lora_finetune"


class TriggerKind(str, Enum):
    """What kicked off a learning session."""

    SCHEDULED = "scheduled"
    CLUSTER = "cluster"
    USER_FLAG = "user_flag"
    ON_DEMAND = "on_demand"


class AutonomyMode(str, Enum):
    """How aggressively the orchestrator applies edits without review."""

    AUTO = "auto"  # all tiers auto-apply, ignore review tier
    TIERED = "tiered"  # default: respect per-edit risk tier
    MANUAL = "manual"  # everything goes to review queue (dry-run mode)


class SessionStatus(str, Enum):
    """Lifecycle states for a LearningSession.

    See spec §7.7 for the transition rules.
    """

    INITIATED = "initiated"
    DIAGNOSING = "diagnosing"
    PLANNING = "planning"
    EXECUTING = "executing"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


# ---------------------------------------------------------------------------
# Edit — atomic unit of change
# ---------------------------------------------------------------------------


class Edit(BaseModel):
    """One atomic edit to the OpenJarvis harness.

    Emitted by the LearningPlanner, consumed by an EditApplier. The teacher
    proposes the op, target, payload, rationale, and references; the planner
    overwrites ``risk_tier`` deterministically from the (pillar, op) lookup
    table — the teacher cannot pick its own tier.

    See spec §4.1.
    """

    id: str = Field(
        ...,
        description="UUID for this edit; also used as a footer in git commits.",
    )
    pillar: EditPillar = Field(..., description="Which OpenJarvis pillar is touched.")
    op: EditOp = Field(..., description="The typed operation to perform.")
    target: str = Field(
        ...,
        description="Dotted path to the target, e.g. 'agents.simple.system_prompt'.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Op-specific arguments. Schema depends on op.",
    )
    rationale: str = Field(
        ...,
        description="Teacher's natural-language reason for this edit.",
    )
    expected_improvement: str = Field(
        ...,
        description="Which failure cluster id this edit is intended to address.",
    )
    risk_tier: EditRiskTier = Field(
        ...,
        description="Set by the planner from a (pillar, op) lookup table.",
    )
    references: list[str] = Field(
        default_factory=list,
        description="Trace ids or benchmark task ids that justify this edit.",
    )


# ---------------------------------------------------------------------------
# FailureCluster — a group of related failures with a shared root cause
# ---------------------------------------------------------------------------


class FailureCluster(BaseModel):
    """A group of failing traces that share a hypothesised root cause.

    Populated by the teacher in the diagnose phase. The student/teacher rates
    must come from real ``run_student_on_task`` and ``run_self_on_task`` calls
    against benchmark tasks (see spec §5.3); clusters where both rates are
    missing or zero are dropped by the planner.

    See spec §4.2.
    """

    id: str
    description: str = Field(..., description="Short human description of the cluster.")
    sample_trace_ids: list[str] = Field(
        default_factory=list,
        description="Trace ids that exemplify this cluster (>= 3 typical).",
    )
    student_failure_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Local student's failure rate on benchmark tasks in this cluster.",
    )
    teacher_success_rate: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Frontier teacher's success rate on the same tasks.",
    )
    skill_gap: str = Field(
        ...,
        description="Teacher's qualitative analysis of what the student is missing.",
    )
    addressed_by_edit_ids: list[str] = Field(
        default_factory=list,
        description="Ids of edits in the LearningPlan that target this cluster.",
    )


# ---------------------------------------------------------------------------
# LearningPlan — frozen output of the planning phase
# ---------------------------------------------------------------------------


class LearningPlan(BaseModel):
    """The teacher's frozen plan of edits for a learning session.

    Once written to ``<session_dir>/plan.json`` this is immutable. The
    execution layer reads this file and does not re-prompt the teacher.

    See spec §4.2 and §6.
    """

    session_id: str = Field(..., description="Owning session id.")
    diagnosis_summary: str = Field(
        ...,
        description="Markdown narrative analysis from the teacher (~500-2000 words).",
    )
    failure_clusters: list[FailureCluster] = Field(
        default_factory=list,
        description="Clusters identified in phase 1.",
    )
    edits: list[Edit] = Field(
        default_factory=list,
        description="Typed edit list emitted by the planner.",
    )
    teacher_model: str = Field(
        ...,
        description="Frontier model id used as the teacher (e.g. 'claude-opus-4-6').",
    )
    estimated_cost_usd: float = Field(
        ...,
        ge=0.0,
        description="Total teacher API cost estimate for this session.",
    )
    created_at: datetime = Field(
        ...,
        description="When the plan was finalized.",
    )


# ---------------------------------------------------------------------------
# BenchmarkSnapshot — one personal-benchmark run result
# ---------------------------------------------------------------------------


class BenchmarkSnapshot(BaseModel):
    """A point-in-time score from running the personal benchmark.

    Two of these live on every LearningSession: one captured before any edits
    apply, one captured after. The version is locked at session start so the
    delta is interpretable even if the benchmark is refreshed mid-session.

    See spec §4.3 and §9.
    """

    benchmark_version: str = Field(
        ...,
        description="Personal benchmark version (e.g. 'personal_v3').",
    )
    overall_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Mean per-task score across the benchmark.",
    )
    cluster_scores: dict[str, float] = Field(
        default_factory=dict,
        description="Mean score per failure cluster.",
    )
    task_count: int = Field(
        ...,
        ge=0,
        description="Number of tasks scored in this snapshot.",
    )
    elapsed_seconds: float = Field(
        ...,
        ge=0.0,
        description="Wall-clock time of the benchmark run.",
    )


# ---------------------------------------------------------------------------
# EditOutcome — what happened when one edit was processed
# ---------------------------------------------------------------------------


EditOutcomeStatus = Literal[
    "applied",
    "rejected_by_gate",
    "pending_review",
    "rejected_by_user",
    "rolled_back",
    "skipped",
]


class EditOutcome(BaseModel):
    """Result of attempting to apply one Edit.

    Persisted both in the SessionStore SQLite table and as part of the
    session.json artifact. The status literal is the canonical lifecycle for
    each edit.

    See spec §4.3.
    """

    edit_id: str
    status: EditOutcomeStatus
    benchmark_delta: float | None = Field(
        default=None,
        description="Overall score change from this edit. None if not gated.",
    )
    cluster_deltas: dict[str, float] = Field(
        default_factory=dict,
        description="Per-cluster score change from this edit.",
    )
    error: str | None = Field(
        default=None,
        description="Error message if the edit was rejected or failed.",
    )
    applied_at: datetime | None = Field(
        default=None,
        description="When the edit was committed to the checkpoint repo.",
    )


# ---------------------------------------------------------------------------
# LearningSession — durable record of one full diagnose→record loop
# ---------------------------------------------------------------------------


class LearningSession(BaseModel):
    """The durable record of one distillation session.

    Persisted in two places: `<session_dir>/session.json` (authoritative) and
    the SQLite SessionStore (queryable index). When in doubt, prefer the JSON
    file — SQLite can be rebuilt from the JSON files.

    See spec §4.3, §7.7 (status transitions), §8.
    """

    id: str
    parent_session_id: str | None = Field(
        default=None,
        description="Id of the session this one is a follow-up to, if any.",
    )
    trigger: TriggerKind
    trigger_metadata: dict[str, Any] = Field(default_factory=dict)
    status: SessionStatus
    autonomy_mode: AutonomyMode
    started_at: datetime
    ended_at: datetime | None = None
    diagnosis_path: Path
    plan_path: Path
    benchmark_before: BenchmarkSnapshot
    benchmark_after: BenchmarkSnapshot | None = None
    edit_outcomes: list[EditOutcome] = Field(default_factory=list)
    git_checkpoint_pre: str = Field(
        ...,
        description="Commit sha at session start (baseline commit).",
    )
    git_checkpoint_post: str | None = Field(
        default=None,
        description="Commit sha after edits applied; None until executing finishes.",
    )
    teacher_cost_usd: float = Field(
        ...,
        ge=0.0,
        description="Accumulated teacher API spend for this session.",
    )
    error: str | None = Field(
        default=None,
        description="If status is FAILED, the error message that caused it.",
    )
