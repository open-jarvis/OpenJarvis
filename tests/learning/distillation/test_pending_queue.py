"""Tests for openjarvis.learning.distillation.pending_queue module."""

from __future__ import annotations

from pathlib import Path

from openjarvis.learning.distillation.models import (
    Edit,
    EditOp,
    EditPillar,
    EditRiskTier,
)


def _make_edit(edit_id: str = "edit-001") -> Edit:
    return Edit(
        id=edit_id,
        pillar=EditPillar.AGENT,
        op=EditOp.REPLACE_SYSTEM_PROMPT,
        target="agents.simple.system_prompt",
        payload={"new_content": "New prompt.\n"},
        rationale="Better prompt",
        expected_improvement="cluster-001",
        risk_tier=EditRiskTier.REVIEW,
    )


class TestPendingQueue:
    def test_enqueue_creates_file(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.pending_queue import PendingQueue

        queue = PendingQueue(tmp_path / "pending_review")
        queue.enqueue("session-001", _make_edit())
        files = list((tmp_path / "pending_review").glob("*.json"))
        assert len(files) == 1
        assert "session-001" in files[0].name
        assert "edit-001" in files[0].name

    def test_list_pending(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.pending_queue import PendingQueue

        queue = PendingQueue(tmp_path / "pending_review")
        queue.enqueue("session-001", _make_edit("e1"))
        queue.enqueue("session-001", _make_edit("e2"))
        pending = queue.list_pending()
        assert len(pending) == 2
        ids = {p["edit"]["id"] for p in pending}
        assert ids == {"e1", "e2"}

    def test_resolve_removes_file(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.pending_queue import PendingQueue

        queue = PendingQueue(tmp_path / "pending_review")
        queue.enqueue("session-001", _make_edit())
        assert len(queue.list_pending()) == 1
        queue.resolve("session-001", "edit-001")
        assert len(queue.list_pending()) == 0

    def test_list_empty_queue(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.pending_queue import PendingQueue

        queue = PendingQueue(tmp_path / "pending_review")
        assert queue.list_pending() == []

    def test_get_pending_edit(self, tmp_path: Path) -> None:
        from openjarvis.learning.distillation.pending_queue import PendingQueue

        queue = PendingQueue(tmp_path / "pending_review")
        queue.enqueue("session-001", _make_edit())
        edit_data = queue.get("session-001", "edit-001")
        assert edit_data is not None
        assert edit_data["edit"]["id"] == "edit-001"
        assert edit_data["session_id"] == "session-001"
