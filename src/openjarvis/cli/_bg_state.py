"""Read background-work state from ``~/.openjarvis/.state/``.

Pure-function reader used by the chat banner, completion-notification
dispatcher, and ``jarvis doctor``.  No side effects — safe to call
between every chat turn.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

from openjarvis.core import config


@dataclass(slots=True)
class BgStatus:
    """Snapshot of background-work state."""

    rust_extension: str = "pending"  # pending | ready | failed
    rust_error: str = ""
    models: Dict[str, str] = field(
        default_factory=dict
    )  # id -> pending|downloading|ready|failed

    def all_ready(self) -> bool:
        if self.rust_extension != "ready":
            return False
        if any(s != "ready" for s in self.models.values()):
            return False
        return True


def _safe_read(path: Path) -> Optional[str]:
    """Read a file, returning None if it disappears mid-read (race)."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None


def _read_model_markers(models_dir: Path, *, versioned: bool) -> Dict[str, str]:
    """Read model state markers from one directory."""
    seen: Dict[str, str] = {}
    if not models_dir.is_dir():
        return seen

    for marker in models_dir.iterdir():
        if not marker.is_file() or marker.suffix not in (
            ".downloading",
            ".ready",
            ".failed",
        ):
            continue

        model_id = marker.name[: -len(marker.suffix)]
        if versioned:
            try:
                # Only metadata is needed here; failure details can be large.
                with marker.open(encoding="utf-8", errors="replace") as stream:
                    original_id = stream.readline(65536).rstrip("\r\n")
            except OSError:
                continue
            if (
                not original_id
                or hashlib.sha256(original_id.encode()).hexdigest() != model_id
            ):
                continue
            model_id = original_id

        new_state = marker.suffix.lstrip(".")
        current = seen.get(model_id, "")
        # Precedence: ready > failed > downloading.
        if current == "ready":
            continue
        if new_state == "ready":
            seen[model_id] = "ready"
        elif new_state == "failed" and current != "ready":
            seen[model_id] = "failed"
        elif new_state == "downloading" and current == "":
            seen[model_id] = "downloading"
    return seen


def get_status(home: Optional[Path] = None) -> BgStatus:
    """Snapshot the background-work state from the state directory."""
    home = home or config.DEFAULT_CONFIG_DIR
    state_dir = home / ".state"
    models_dir = state_dir / "models"

    status = BgStatus()

    # Rust extension: ready supersedes failed; failed supersedes pending.
    # The ``extension-built`` marker is only written by the installer scripts,
    # so editable/dev installs (``uv sync`` + ``maturin develop``) never get
    # one. Fall back to the runtime import check so those installs don't show
    # "building" forever (and a stale ``extension-failed`` doesn't lie once the
    # extension has actually been built).
    from openjarvis import _rust_bridge

    if (state_dir / "extension-built").exists() or _rust_bridge.RUST_AVAILABLE:
        status.rust_extension = "ready"
    elif (state_dir / "extension-failed").exists():
        contents = _safe_read(state_dir / "extension-failed")
        if contents is not None:
            status.rust_extension = "failed"
            status.rust_error = contents

    # Legacy markers keep their original names. Versioned markers use fixed-size
    # lowercase hashes, avoiding reserved characters and case-fold collisions.
    seen = _read_model_markers(models_dir, versioned=False)
    # Once a model has versioned state, it supersedes stale legacy markers.
    seen.update(_read_model_markers(models_dir / "v1", versioned=True))
    status.models = seen

    return status
