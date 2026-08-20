"""PinchBench task environment — per-task workspace setup and grading."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from types import TracebackType
from typing import Any, Optional, Type

from openjarvis.evals.core.types import EvalRecord

LOGGER = logging.getLogger(__name__)


class PinchBenchTaskEnv:
    """Per-task workspace environment for PinchBench.

    Context manager that creates an isolated workspace directory,
    populates fixture files from the task definition, and runs
    grading after agent execution via run_tests().
    """

    def __init__(
        self,
        record: EvalRecord,
        judge_backend: Any = None,
        judge_model: str = "anthropic/claude-opus-4-5",
    ) -> None:
        self._record = record
        self._judge_backend = judge_backend
        self._judge_model = judge_model
        self._workspace: Optional[Path] = None
        self._owns_workspace: bool = True
        self._event_recorder: Any = None
        self._original_cwd: Optional[str] = None

    def set_event_recorder(self, recorder: Any) -> None:
        """Receive the EventRecorder from AgenticRunner for transcript building."""
        self._event_recorder = recorder

    def __enter__(self) -> PinchBenchTaskEnv:
        # Use the AgenticRunner's workspace if already set (agent.set_workspace
        # is called before create_task_env), otherwise create a temp dir.
        existing = self._record.metadata.get("workspace_path")
        if existing and Path(existing).is_dir():
            self._workspace = Path(existing)
            self._owns_workspace = False
        else:
            self._workspace = Path(tempfile.mkdtemp(prefix="pinchbench_"))
            self._owns_workspace = True

        # Populate fixture files
        repo_dir = Path(self._record.metadata.get("pinchbench_repo_dir", ""))
        workspace_files = self._record.metadata.get("workspace_files", [])

        for file_spec in workspace_files:
            if "content" in file_spec:
                # Inline content
                dest_key = file_spec.get("path", file_spec.get("dest", "file.txt"))
                dest = self._workspace / dest_key
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(file_spec["content"])
            elif "source" in file_spec:
                # Asset file from repo
                source = repo_dir / "assets" / file_spec["source"]
                dest_key = file_spec.get(
                    "dest", file_spec.get("path", file_spec["source"])
                )
                dest = self._workspace / dest_key
                dest.parent.mkdir(parents=True, exist_ok=True)
                if source.exists():
                    shutil.copy2(str(source), str(dest))
                else:
                    LOGGER.warning("Asset not found: %s", source)

        self._record.metadata["workspace_path"] = str(self._workspace)

        # Change CWD so file_read/file_write resolve paths relative to workspace
        self._original_cwd = os.getcwd()
        os.chdir(str(self._workspace))

        LOGGER.info(
            "PinchBench workspace: %s (task %s)",
            self._workspace,
            self._record.record_id,
        )
        return self

    def run_tests(self) -> None:
        """Grade the agent's work using PinchBench grading logic.

        Called by AgenticRunner after agent execution, before QueryTrace
        is constructed. Builds transcript from raw EventRecorder events.
        """
        from openjarvis.evals.scorers.pinchbench import (
            events_to_transcript,
            grade_pinchbench_task,
        )

        workspace_path = self._record.metadata.get("workspace_path", "")
        events = self._event_recorder.get_events() if self._event_recorder else []
        transcript = events_to_transcript(events)

        try:
            result = grade_pinchbench_task(
                record=self._record,
                transcript=transcript,
                workspace_path=workspace_path,
                judge_backend=self._judge_backend,
                judge_model=self._judge_model,
            )
        except Exception as exc:
            LOGGER.error(
                "Grading failed for %s: %s",
                self._record.record_id,
                exc,
            )
            result = {"score": 0.0, "breakdown": {}, "notes": f"Grading error: {exc}"}

        self._record.metadata["is_resolved"] = result["score"] >= 0.5
        self._record.metadata["reward"] = result["score"]
        self._record.metadata["pinchbench_score"] = result["score"]
        self._record.metadata["pinchbench_breakdown"] = result["breakdown"]
        self._record.metadata["pinchbench_notes"] = result.get("notes", "")

        LOGGER.info(
            "PinchBench grading for %s: score=%.2f resolved=%s",
            self._record.record_id,
            result["score"],
            result["score"] >= 0.5,
        )

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        # Restore original CWD
        if self._original_cwd:
            try:
                os.chdir(self._original_cwd)
            except OSError:
                pass
            self._original_cwd = None

        # Only clean up workspaces we created ourselves (not AgenticRunner's)
        if self._owns_workspace and self._workspace and self._workspace.exists():
            keep = os.environ.get("PINCHBENCH_KEEP_WORKSPACES", "").strip()
            if keep and keep != "0":
                LOGGER.info("Keeping workspace: %s", self._workspace)
            else:
                shutil.rmtree(self._workspace, ignore_errors=True)
        self._workspace = None
        self._event_recorder = None


__all__ = ["PinchBenchTaskEnv"]
