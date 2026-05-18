"""Tests for openjarvis.learning.spec_search.storage.session_store module."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from openjarvis.learning.spec_search.models import (
    AutonomyMode,
    BenchmarkSnapshot,
    EditOutcome,
    LearningSession,
    SessionStatus,
    TriggerKind,
)


def _make_session(
    session_id: str = "session-001",
    parent_session_id: str | None = None,
    status: SessionStatus = SessionStatus.INITIATED,
    teacher_cost_usd: float = 0.0,
) -> LearningSession:
    snap = BenchmarkSnapshot(
        benchmark_version="personal_v1",
        overall_score=0.6,
        cluster_scores={"cluster-001": 0.5},
        task_count=20,
        elapsed_seconds=60.0,
    )
    return LearningSession(
        id=session_id,
        parent_session_id=parent_session_id,
        trigger=TriggerKind.SCHEDULED,
        trigger_metadata={},
        status=status,
        autonomy_mode=AutonomyMode.TIERED,
        started_at=datetime(2026, 4, 8, 3, 0, 0, tzinfo=timezone.utc),
        ended_at=None,
        diagnosis_path=Path(f"/tmp/{session_id}/diagnosis.md"),
        plan_path=Path(f"/tmp/{session_id}/plan.json"),
        benchmark_before=snap,
        benchmark_after=None,
        edit_outcomes=[],
        git_checkpoint_pre="abc1234",
        git_checkpoint_post=None,
        teacher_cost_usd=teacher_cost_usd,
        error=None,
    )


def _make_outcome(
    edit_id: str = "edit-001",
    pillar: str = "intelligence",
    op: str = "set_model_for_query_class",
    target: str = "learning.routing.policy_map.math",
    risk_tier: str = "auto",
    status: str = "applied",
    benchmark_delta: float | None = 0.04,
) -> tuple[EditOutcome, dict]:
    """Return (EditOutcome, extra_columns) — the SessionStore stores some
    metadata that isn't on the EditOutcome model itself (pillar/op/target/
    risk_tier/rationale come from the parent Edit)."""
    outcome = EditOutcome(
        edit_id=edit_id,
        status=status,  # type: ignore[arg-type]
        benchmark_delta=benchmark_delta,
        cluster_deltas={"cluster-001": 0.1} if benchmark_delta else {},
        error=None if status == "applied" else "test failure",
        applied_at=(
            datetime(2026, 4, 8, 3, 5, 0, tzinfo=timezone.utc)
            if status == "applied"
            else None
        ),
    )
    extras = {
        "pillar": pillar,
        "op": op,
        "target": target,
        "risk_tier": risk_tier,
        "rationale": "test rationale",
    }
    return outcome, extras


class TestSessionStoreInit:
    """Tests for SessionStore initialization."""

    def test_creates_tables(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        db = tmp_path / "learning.db"
        store = SessionStore(db)

        assert store.list_sessions() == []
        assert store.get_session("nonexistent") is None
        assert store.list_outcomes("nonexistent") == []
        store.close()

    def test_idempotent_init(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        db = tmp_path / "learning.db"
        SessionStore(db).close()
        store = SessionStore(db)  # Should not raise.
        assert store.list_sessions() == []
        store.close()


class TestSessionStoreSaveAndGet:
    """Tests for save_session/get_session round-trip."""

    def test_round_trip(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        original = _make_session()
        store.save_session(original)

        restored = store.get_session(original.id)
        assert restored is not None
        assert restored == original
        store.close()

    def test_update_existing_session(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        session = _make_session(status=SessionStatus.INITIATED)
        store.save_session(session)

        # Update status and re-save.
        session = session.model_copy(update={"status": SessionStatus.COMPLETED})
        store.save_session(session)

        restored = store.get_session(session.id)
        assert restored is not None
        assert restored.status == SessionStatus.COMPLETED
        store.close()

    def test_get_returns_none_for_unknown(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        assert store.get_session("does-not-exist") is None
        store.close()


class TestSessionStoreList:
    """Tests for list_sessions ordering and filters."""

    def test_lists_in_started_at_desc_order(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        s1 = _make_session(session_id="s1")
        s2 = _make_session(session_id="s2")
        s2 = s2.model_copy(
            update={"started_at": datetime(2026, 4, 9, 3, 0, 0, tzinfo=timezone.utc)}
        )

        store.save_session(s1)
        store.save_session(s2)

        listed = store.list_sessions()
        assert [s.id for s in listed] == ["s2", "s1"]
        store.close()

    def test_filter_by_status(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        s1 = _make_session(session_id="s1", status=SessionStatus.COMPLETED)
        s2 = _make_session(session_id="s2", status=SessionStatus.FAILED)
        store.save_session(s1)
        store.save_session(s2)

        completed = store.list_sessions(status=SessionStatus.COMPLETED)
        failed = store.list_sessions(status=SessionStatus.FAILED)
        assert [s.id for s in completed] == ["s1"]
        assert [s.id for s in failed] == ["s2"]
        store.close()

    def test_limit(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        for i in range(5):
            session = _make_session(session_id=f"s{i}")
            session = session.model_copy(
                update={
                    "started_at": datetime(2026, 4, 8, 3 + i, 0, 0, tzinfo=timezone.utc)
                }
            )
            store.save_session(session)

        listed = store.list_sessions(limit=3)
        assert len(listed) == 3
        store.close()


class TestEditOutcomes:
    """Tests for save_outcome / list_outcomes."""

    def test_round_trip(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        session = _make_session()
        store.save_session(session)

        outcome, extras = _make_outcome()
        store.save_outcome(session.id, outcome, **extras)

        listed = store.list_outcomes(session.id)
        assert len(listed) == 1
        assert listed[0].edit_id == "edit-001"
        assert listed[0].status == "applied"
        assert listed[0].benchmark_delta == 0.04
        store.close()

    def test_multiple_outcomes_per_session(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        session = _make_session()
        store.save_session(session)

        for i in range(3):
            outcome, extras = _make_outcome(edit_id=f"edit-{i}")
            store.save_outcome(session.id, outcome, **extras)

        listed = store.list_outcomes(session.id)
        assert len(listed) == 3
        assert {o.edit_id for o in listed} == {"edit-0", "edit-1", "edit-2"}
        store.close()

    def test_outcomes_for_unknown_session_returns_empty(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        assert store.list_outcomes("nonexistent") == []
        store.close()


class TestParentSessionChain:
    """Tests for parent_session_id foreign key."""

    def test_parent_id_round_trips(self, tmp_path: Path) -> None:
        from openjarvis.learning.spec_search.storage.session_store import (
            SessionStore,
        )

        store = SessionStore(tmp_path / "learning.db")
        parent = _make_session(session_id="parent")
        child = _make_session(session_id="child", parent_session_id="parent")
        store.save_session(parent)
        store.save_session(child)

        restored = store.get_session("child")
        assert restored is not None
        assert restored.parent_session_id == "parent"
        store.close()
