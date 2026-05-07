"""Pending review queue for edits awaiting user approval.

Edits in the ``review`` tier (when autonomy mode is ``tiered``) are
written here as JSON files. The user reviews them via ``jarvis learning
review`` and approves or rejects.

See spec §7.5.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from openjarvis.learning.distillation.models import Edit

logger = logging.getLogger(__name__)


class PendingQueue:
    """File-based queue for pending review edits.

    Each edit is stored as ``<queue_dir>/<session_id>__<edit_id>.json``.
    """

    def __init__(self, queue_dir: Path) -> None:
        self._dir = Path(queue_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def enqueue(self, session_id: str, edit: Edit) -> Path:
        """Write an edit to the pending queue. Returns the file path."""
        filename = f"{session_id}__{edit.id}.json"
        path = self._dir / filename
        data = {
            "session_id": session_id,
            "edit": json.loads(edit.model_dump_json()),
        }
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Enqueued edit %s for review", edit.id)
        return path

    def list_pending(self) -> list[dict[str, Any]]:
        """Return all pending edits as dicts."""
        results = []
        for path in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append(data)
            except (json.JSONDecodeError, OSError):
                logger.warning("Skipping corrupt pending file: %s", path)
        return results

    def get(self, session_id: str, edit_id: str) -> dict[str, Any] | None:
        """Return a specific pending edit, or None."""
        filename = f"{session_id}__{edit_id}.json"
        path = self._dir / filename
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def resolve(self, session_id: str, edit_id: str) -> bool:
        """Remove a pending edit (approved or rejected). Returns True if found."""
        filename = f"{session_id}__{edit_id}.json"
        path = self._dir / filename
        if path.exists():
            path.unlink()
            logger.info("Resolved pending edit %s", edit_id)
            return True
        return False
