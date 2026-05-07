"""DistillationOrchestrator: top-level driver for a learning session.

Wires diagnose (M2) → plan (M3) → execute (M4) → gate (M5) into a
single ``run(trigger)`` method. All dependencies are injected.

See spec §3, §7.2, §7.7.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from openjarvis.learning.distillation.diagnose.runner import DiagnosisRunner
from openjarvis.learning.distillation.execute.base import ApplyContext
from openjarvis.learning.distillation.execute.loop import _build_registry
from openjarvis.learning.distillation.gate.benchmark_gate import BenchmarkGate
from openjarvis.learning.distillation.gate.cold_start import check_readiness
from openjarvis.learning.distillation.models import (
    AutonomyMode,
    BenchmarkSnapshot,
    EditOutcome,
    EditRiskTier,
    LearningSession,
    SessionStatus,
)
from openjarvis.learning.distillation.pending_queue import PendingQueue
from openjarvis.learning.distillation.plan.planner import LearningPlanner

logger = logging.getLogger(__name__)


class DistillationOrchestrator:
    """Top-level driver for a distillation learning session.

    All dependencies are injected so tests can mock everything.
    """

    def __init__(
        self,
        *,
        teacher_engine: Any,
        teacher_model: str,
        trace_store: Any,
        benchmark_samples: list,
        student_runner: Any,
        judge: Any,
        session_store: Any,
        checkpoint_store: Any,
        openjarvis_home: Path,
        autonomy_mode: AutonomyMode = AutonomyMode.TIERED,
        scorer: Callable[..., BenchmarkSnapshot] | None = None,
        benchmark_version: str = "personal_v1",
        min_traces: int = 20,
        max_cost_usd: float = 5.0,
        max_tool_calls: int = 30,
        min_improvement: float = 0.0,
        max_regression: float = 0.05,
        subsample_size: int = 50,
    ) -> None:
        self._engine = teacher_engine
        self._model = teacher_model
        self._trace_store = trace_store
        self._benchmark_samples = benchmark_samples
        self._student_runner = student_runner
        self._judge = judge
        self._session_store = session_store
        self._checkpoint_store = checkpoint_store
        self._home = Path(openjarvis_home)
        self._autonomy = autonomy_mode
        self._scorer = scorer
        self._bench_version = benchmark_version
        self._min_traces = min_traces
        self._max_cost = max_cost_usd
        self._max_tool_calls = max_tool_calls
        self._min_improvement = min_improvement
        self._max_regression = max_regression
        self._subsample_size = subsample_size

    def run(self, trigger: Any) -> LearningSession:
        """Execute a full distillation session.

        Returns the completed LearningSession.
        """
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        session_id = f"session-{ts}_{uuid.uuid4().hex[:8]}"
        session_dir = self._home / "learning" / "sessions" / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Initialize session
        pre_sha = self._checkpoint_store.current_sha()
        session = LearningSession(
            id=session_id,
            trigger=trigger.kind,
            trigger_metadata=trigger.metadata,
            status=SessionStatus.INITIATED,
            autonomy_mode=self._autonomy,
            started_at=datetime.now(timezone.utc),
            diagnosis_path=session_dir / "diagnosis.md",
            plan_path=session_dir / "plan.json",
            benchmark_before=BenchmarkSnapshot(
                benchmark_version=self._bench_version,
                overall_score=0.0,
                cluster_scores={},
                task_count=0,
                elapsed_seconds=0.0,
            ),
            git_checkpoint_pre=pre_sha,
            teacher_cost_usd=0.0,
        )

        try:
            # Cold start check
            readiness = check_readiness(self._trace_store, min_traces=self._min_traces)
            if not readiness.ready:
                session = session.model_copy(
                    update={
                        "status": SessionStatus.FAILED,
                        "error": readiness.message,
                        "ended_at": datetime.now(timezone.utc),
                    }
                )
                self._session_store.save_session(session)
                return session

            # Capture benchmark before
            if self._scorer is not None:
                before_snap = self._scorer(
                    benchmark_version=self._bench_version,
                    subsample_size=self._subsample_size,
                    seed=hash(session_id) % (2**31),
                )
                session = session.model_copy(update={"benchmark_before": before_snap})

            # Phase 1: Diagnose
            session = session.model_copy(update={"status": SessionStatus.DIAGNOSING})
            self._session_store.save_session(session)

            diagnosis_runner = DiagnosisRunner(
                teacher_engine=self._engine,
                teacher_model=self._model,
                trace_store=self._trace_store,
                benchmark_samples=self._benchmark_samples,
                student_runner=self._student_runner,
                judge=self._judge,
                session_dir=session_dir,
                session_id=session_id,
                config={
                    "config_path": self._home / "config.toml",
                    "openjarvis_home": self._home,
                },
                max_turns=self._max_tool_calls,
                max_cost_usd=self._max_cost,
            )
            diag_result = diagnosis_runner.run()
            cost = diag_result.cost_usd

            if not diag_result.clusters:
                session = session.model_copy(
                    update={
                        "status": SessionStatus.FAILED,
                        "error": "diagnosis produced no actionable clusters",
                        "teacher_cost_usd": cost,
                        "ended_at": datetime.now(timezone.utc),
                    }
                )
                self._session_store.save_session(session)
                return session

            # Phase 2: Plan
            session = session.model_copy(update={"status": SessionStatus.PLANNING})
            self._session_store.save_session(session)

            planner = LearningPlanner(
                teacher_engine=self._engine,
                teacher_model=self._model,
                session_id=session_id,
                session_dir=session_dir,
                prompt_reader=lambda t: self._read_prompt(t),
            )
            plan = planner.run(
                diagnosis_md=diag_result.diagnosis_md,
                clusters=diag_result.clusters,
            )
            cost += plan.estimated_cost_usd

            # Phase 3: Execute
            session = session.model_copy(update={"status": SessionStatus.EXECUTING})
            self._session_store.save_session(session)

            ctx = ApplyContext(
                openjarvis_home=self._home,
                session_id=session_id,
            )
            registry = _build_registry()

            gate: BenchmarkGate | None = None
            if self._scorer is not None:
                gate = BenchmarkGate(
                    scorer=self._scorer,
                    benchmark_version=self._bench_version,
                    min_improvement=self._min_improvement,
                    max_regression=self._max_regression,
                    subsample_size=self._subsample_size,
                )

            session_seed = hash(session_id) % (2**31)
            outcomes: list[EditOutcome] = []

            for edit in plan.edits:
                # Manual autonomy mode: everything goes to review
                if self._autonomy == AutonomyMode.MANUAL:
                    outcomes.append(
                        EditOutcome(
                            edit_id=edit.id,
                            status="pending_review",
                            benchmark_delta=None,
                            cluster_deltas={},
                            error=None,
                            applied_at=None,
                        )
                    )
                    continue

                # Manual risk tier: always skip
                if edit.risk_tier == EditRiskTier.MANUAL:
                    outcomes.append(
                        EditOutcome(
                            edit_id=edit.id,
                            status="skipped",
                            benchmark_delta=None,
                            cluster_deltas={},
                            error="manual tier, requires explicit approval",
                            applied_at=None,
                        )
                    )
                    continue

                # Review tier in tiered mode: route to pending
                if (
                    edit.risk_tier == EditRiskTier.REVIEW
                    and self._autonomy == AutonomyMode.TIERED
                ):
                    outcomes.append(
                        EditOutcome(
                            edit_id=edit.id,
                            status="pending_review",
                            benchmark_delta=None,
                            cluster_deltas={},
                            error=None,
                            applied_at=None,
                        )
                    )
                    continue

                # Check if the op is supported
                if not registry.is_supported(edit.op):
                    outcomes.append(
                        EditOutcome(
                            edit_id=edit.id,
                            status="skipped",
                            benchmark_delta=None,
                            cluster_deltas={},
                            error=f"op {edit.op.value} not implemented in v1",
                            applied_at=None,
                        )
                    )
                    continue

                # Validate
                applier = registry.get(edit.op)
                validation = applier.validate(edit, ctx)
                if not validation.ok:
                    outcomes.append(
                        EditOutcome(
                            edit_id=edit.id,
                            status="rejected_by_gate",
                            benchmark_delta=None,
                            cluster_deltas={},
                            error=validation.reason,
                            applied_at=None,
                        )
                    )
                    continue

                # Apply the edit
                try:
                    applier.apply(edit, ctx)
                except Exception as exc:
                    logger.warning("Edit %s apply failed: %s", edit.id, exc)
                    outcomes.append(
                        EditOutcome(
                            edit_id=edit.id,
                            status="rejected_by_gate",
                            benchmark_delta=None,
                            cluster_deltas={},
                            error=str(exc),
                            applied_at=None,
                        )
                    )
                    continue

                # If no scorer, accept directly (backward-compat with tests)
                if gate is None:
                    outcomes.append(
                        EditOutcome(
                            edit_id=edit.id,
                            status="applied",
                            benchmark_delta=None,
                            cluster_deltas={},
                            error=None,
                            applied_at=datetime.now(timezone.utc),
                        )
                    )
                    continue

                # Run the benchmark gate
                before_snap = session.benchmark_before
                gate_result = gate.evaluate(
                    before=before_snap,
                    session_seed=session_seed,
                )

                if gate_result.accepted:
                    outcomes.append(
                        EditOutcome(
                            edit_id=edit.id,
                            status="applied",
                            benchmark_delta=gate_result.delta,
                            cluster_deltas={},
                            error=None,
                            applied_at=datetime.now(timezone.utc),
                        )
                    )
                else:
                    # Gate rejected — rollback the edit
                    try:
                        applier.rollback(edit, ctx)
                    except Exception as rb_exc:
                        logger.warning(
                            "Edit %s rollback failed: %s", edit.id, rb_exc
                        )
                    outcomes.append(
                        EditOutcome(
                            edit_id=edit.id,
                            status="rejected_by_gate",
                            benchmark_delta=gate_result.delta,
                            cluster_deltas={},
                            error=gate_result.reason,
                            applied_at=None,
                        )
                    )

            # Enqueue pending_review edits
            pending_queue = PendingQueue(self._home / "learning" / "pending_review")
            has_pending = False
            for outcome, edit in zip(outcomes, plan.edits):
                if outcome.status == "pending_review":
                    pending_queue.enqueue(session_id, edit)
                    has_pending = True

            # Capture benchmark after
            after_snap = None
            if self._scorer is not None:
                after_snap = self._scorer(
                    benchmark_version=self._bench_version,
                    subsample_size=self._subsample_size,
                    seed=session_seed,
                )

            # Determine final status
            if has_pending:
                final_status = SessionStatus.AWAITING_REVIEW
            else:
                final_status = SessionStatus.COMPLETED

            post_sha = self._checkpoint_store.current_sha()
            session = session.model_copy(
                update={
                    "status": final_status,
                    "edit_outcomes": outcomes,
                    "benchmark_after": after_snap,
                    "git_checkpoint_post": post_sha,
                    "teacher_cost_usd": cost,
                    "ended_at": datetime.now(timezone.utc),
                }
            )

        except Exception as e:
            logger.exception("Session %s failed: %s", session_id, e)
            session = session.model_copy(
                update={
                    "status": SessionStatus.FAILED,
                    "error": str(e),
                    "ended_at": datetime.now(timezone.utc),
                }
            )

        self._session_store.save_session(session)

        # Write session.json artifact
        artifact_path = session_dir / "session.json"
        artifact_path.write_text(session.model_dump_json(indent=2), encoding="utf-8")

        return session

    def _read_prompt(self, target: str) -> str:
        """Read a prompt file from the config tree."""
        parts = target.split(".")
        if len(parts) >= 2:
            agent_name = parts[1]
            path = self._home / "agents" / agent_name / "system_prompt.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
        return ""
