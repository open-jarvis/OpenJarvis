"""Git-backed checkpoint store for spec-search config rollback.

A thin wrapper over a local git repository at ``<openjarvis_home>/.git``.
The repo tracks ``config.toml``, ``agents/``, and ``tools/`` so that the
diff between two commits captures the harness state at any point in time.
The repo does NOT track ``learning/`` (sessions are append-only artifacts,
not config state).

The wrapper shells out to ``git`` via ``subprocess`` rather than depending
on a third-party library — keeps the dependency surface zero.

See spec §7.4 and §7.6.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from openjarvis.learning.spec_search.storage.paths import (
    ConfigurationError,
    _find_source_root,
)

logger = logging.getLogger(__name__)


# Files and directories the checkpoint repo tracks.
_TRACKED_PATHS = ("config.toml", "agents", "tools")

# Marker line in baseline commits so we can detect them on re-init.
_BASELINE_COMMIT_MESSAGE = "learning: checkpoint baseline"


class DirtyWorkingTreeError(RuntimeError):
    """Raised when begin_stage is called on a working tree with uncommitted changes."""


@dataclass(frozen=True)
class StageHandle:
    """Snapshot of repo state captured at the start of a staging operation."""

    edit_id: str
    pre_stage_sha: str


class CheckpointStore:
    """Thin git wrapper for the spec-search checkpoint repo.

    Parameters
    ----------
    root :
        The directory that *contains* the checkpoint repo (the repo's
        ``.git`` lives at ``root / ".git"``). For production use this is
        ``~/.openjarvis/`` (or ``$OPENJARVIS_HOME``); for tests it's a
        ``tmp_path`` subdirectory.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root).resolve()

    @property
    def root(self) -> Path:
        return self._root

    # ------------------------------------------------------------------
    # init
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Initialize the checkpoint repo if it doesn't exist.

        Refuses to initialize if ``self.root`` is inside the OpenJarvis source
        tree — this is the same defense-in-depth check as
        ``resolve_spec_search_root``: we never want a stray git repo writing
        config snapshots into the working copy.

        Idempotent: if ``.git`` already exists and contains a baseline commit,
        does nothing.
        """
        source_root = _find_source_root()
        if source_root is not None:
            try:
                self._root.relative_to(source_root)
            except ValueError:
                pass
            else:
                raise ConfigurationError(
                    f"CheckpointStore root ({self._root}) is inside the "
                    f"OpenJarvis source tree ({source_root}). Refusing to "
                    "initialize a checkpoint repo there."
                )

        self._root.mkdir(parents=True, exist_ok=True)

        if (self._root / ".git").exists() and self._has_baseline_commit():
            return

        if not (self._root / ".git").exists():
            self._git("init", "-q")
            self._git("config", "user.email", "spec-search@openjarvis.local")
            self._git("config", "user.name", "OpenJarvis Spec Search")

        # Stage whatever tracked paths currently exist (it's OK if some
        # don't yet — the user may not have agents or tools dirs at first
        # init time, in which case the baseline commit is empty).
        for rel in _TRACKED_PATHS:
            target = self._root / rel
            if target.exists():
                self._git("add", rel)

        # Allow empty so init succeeds even on a brand-new openjarvis home.
        self._git(
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            _BASELINE_COMMIT_MESSAGE,
        )

    # ------------------------------------------------------------------
    # current_sha
    # ------------------------------------------------------------------

    def current_sha(self) -> str:
        """Return the abbreviated sha of HEAD."""
        return self._git("rev-parse", "--short", "HEAD")

    # ------------------------------------------------------------------
    # Staging primitives
    # ------------------------------------------------------------------

    def begin_stage(self, edit_id: str) -> StageHandle:
        """Capture HEAD sha and assert the working tree is clean.

        Raises
        ------
        DirtyWorkingTreeError
            If there are uncommitted changes to tracked files. The
            orchestrator should never start a stage on a dirty tree —
            it indicates the user has manual edits in progress.
        """
        if self._working_tree_dirty():
            raise DirtyWorkingTreeError(
                f"Cannot begin stage for {edit_id}: working tree has "
                "uncommitted changes. Commit or stash them first."
            )
        return StageHandle(
            edit_id=edit_id,
            pre_stage_sha=self.current_sha(),
        )

    def commit_stage(
        self,
        handle: StageHandle,
        *,
        message: str,
        session_id: str,
        risk_tier: str,
    ) -> str:
        """Stage all tracked-path changes and create a commit.

        The commit message has the form::

            <message>

            Edit-ID: <handle.edit_id>
            Session-ID: <session_id>
            Risk-Tier: <risk_tier>

        Returns the new commit sha (abbreviated).
        """
        for rel in _TRACKED_PATHS:
            target = self._root / rel
            if target.exists():
                self._git("add", rel)

        full_message = (
            f"{message}\n"
            "\n"
            f"Edit-ID: {handle.edit_id}\n"
            f"Session-ID: {session_id}\n"
            f"Risk-Tier: {risk_tier}\n"
        )
        self._git("commit", "-q", "-m", full_message)
        return self.current_sha()

    def discard_stage(self, handle: StageHandle) -> None:
        """Restore the working tree to ``handle.pre_stage_sha``."""
        for rel in _TRACKED_PATHS:
            target = self._root / rel
            if target.exists():
                self._git("checkout", handle.pre_stage_sha, "--", rel)
        # Sanity check: HEAD must still equal the pre-stage sha.
        if self.current_sha() != handle.pre_stage_sha:
            raise RuntimeError(
                "discard_stage left HEAD at unexpected sha — something "
                "committed during the stage. Aborting for safety."
            )

    # ------------------------------------------------------------------
    # Session-level rollback
    # ------------------------------------------------------------------

    def revert_session(self, session_id: str) -> list[str]:
        """Revert all commits tagged ``Session-ID: <session_id>``.

        Reverts are applied in reverse chronological order (newest first),
        each producing a *new* commit so history is preserved (no rewriting).
        Returns the list of new revert commit shas.
        """
        log = self._git(
            "log",
            "--format=%H",
            f"--grep=Session-ID: {session_id}",
        )
        if not log.strip():
            return []

        # log is newest-first, which is the order we want for revert.
        target_shas = log.strip().splitlines()
        new_shas: list[str] = []
        for sha in target_shas:
            self._git("revert", "--no-edit", sha)
            new_shas.append(self.current_sha())
        return new_shas

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _git(self, *args: str) -> str:
        """Run a git command in the repo and return stripped stdout."""
        result = subprocess.run(
            ["git", *args],
            cwd=self._root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _has_baseline_commit(self) -> bool:
        try:
            log = self._git("log", "--format=%s")
        except subprocess.CalledProcessError:
            return False
        return _BASELINE_COMMIT_MESSAGE in log

    def _working_tree_dirty(self) -> bool:
        """Return True if there are uncommitted changes to tracked files."""
        status = self._git("status", "--porcelain")
        return bool(status.strip())
