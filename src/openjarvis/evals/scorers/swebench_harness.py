"""SWE-bench harness scorer — runs the official `swebench` test harness.

This is the authoritative pass/fail scorer for SWE-bench-Verified.
The lightweight :class:`SWEBenchScorer` in ``swebench_structural.py``
checks only that the model produced *something patch-shaped*; this one
actually applies the patch, runs the targeted tests, and reads the
harness's report JSON.

Backends (selected by ``SWEBENCH_BACKEND`` env var):

- ``modal`` (default) — runs on Modal in the cloud; needs ``swebench[modal]``
  installed and ``modal token new`` configured once.
- ``docker`` — runs locally; needs Docker daemon + user in ``docker`` group.

Ported from ``hybrid-local-cloud-compute/benches/swebench_verified/{runner,parsing}.py``,
with two upstream-`swebench` patches applied at import time:

1. **Modal cgroup-v2 fix**:
   ``swebench/harness/modal_eval/run_evaluation_modal.py:66`` writes to
   ``/sys/fs/cgroup/cpu/cpu.shares`` (cgroup v1). Modal v2 sandboxes use
   cgroup v2 — the path doesn't exist and every sandbox dies on the write.
   Wrap the write in try/except.

2. **Rescore `*_ids` fix**: older harness rescore code read
   ``resolved_instances`` / ``unresolved_instances`` / ``error_instances``
   as lists. Current swebench writes counts there and puts IDs in
   ``*_ids`` fields. Wherever we read these we use ``*_ids``.

Both patches are idempotent and only fire when the harness modules are
imported via this scorer (we don't touch swebench until ``score()`` is
called for the first time).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)


# ---------- Patch tracking ----------

_PATCHES_APPLIED = False


def _patch_modal_cgroup_v2() -> None:
    """Wrap the cgroup-v1 write in run_evaluation_modal.py with try/except.

    The upstream line is ``Path("/sys/fs/cgroup/cpu/cpu.shares").write_text(...)``.
    Modal v2 sandboxes are cgroup-v2 and that path doesn't exist; the write
    raises FileNotFoundError and the sandbox dies. We replace the entire
    ``set_cpu_quota`` function body (if present) with a try/except wrapper.
    """
    try:
        from swebench.harness.modal_eval import (
            run_evaluation_modal as _m,  # type: ignore[import-not-found]
        )
    except Exception:
        return
    if getattr(_m, "_hybrid_cgroup_patched", False):
        return
    orig = getattr(_m, "set_cpu_quota", None)
    if orig is None:
        # Upstream API changed: ``set_cpu_quota`` no longer exists. The
        # cgroup-v1 write that used to live inside it is either gone (good)
        # or now lives somewhere we can't patch (bad — every Modal-v2
        # sandbox will still die). Surface loudly so failures aren't
        # silently scored as 0 via the ``no_report`` fallback in
        # :func:`_run_harness`.
        logger.warning(
            "swebench.harness.modal_eval.run_evaluation_modal.set_cpu_quota "
            "is missing — cgroup-v2 patch could not be applied. If your "
            "Modal sandboxes are scoring 0 with `reason: no_report`, "
            "verify upstream swebench's Modal cgroup handling."
        )
        _m._hybrid_cgroup_patched = True  # type: ignore[attr-defined]
        return

    def patched(*args, **kwargs):  # type: ignore[no-untyped-def]
        try:
            return orig(*args, **kwargs)
        except FileNotFoundError:
            # cgroup v2 sandbox — path missing is expected, skip.
            return None
        except PermissionError:
            return None

    _m.set_cpu_quota = patched  # type: ignore[assignment]
    _m._hybrid_cgroup_patched = True  # type: ignore[attr-defined]


def _apply_patches_once() -> None:
    global _PATCHES_APPLIED
    if _PATCHES_APPLIED:
        return
    _patch_modal_cgroup_v2()
    _PATCHES_APPLIED = True


# ---------- Patch extraction ----------

_FENCE_PATTERNS = [
    re.compile(r"```(?:diff|patch)\n(.*?)```", re.DOTALL),
    re.compile(r"```\n(diff --git .*?)```", re.DOTALL),
]


def extract_patch(text: str) -> Optional[str]:
    """Pull a unified diff out of agent output. ``None`` if not found."""
    if not text:
        return None
    for pat in _FENCE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1).strip() + "\n"
    if "diff --git" in text:
        start = text.index("diff --git")
        return text[start:].strip() + "\n"
    return None


# ---------- Harness invocation ----------

def _harness_cache_dir() -> Path:
    """Where the swebench subprocess writes its report JSON + logs/ tree.

    Defaults to ``$OPENJARVIS_HOME/.swebench-cache`` if set, otherwise to a
    process-shared tempdir. Pin both so we don't pollute the project root.
    """
    home = os.environ.get("OPENJARVIS_HOME")
    if home:
        cache = Path(home) / ".swebench-cache"
    else:
        cache = Path(tempfile.gettempdir()) / "openjarvis-swebench-cache"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _find_report(cache: Path, instance_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    """Find the harness's report JSON for one instance.

    swebench writes ``<model_name_or_path>.<run_id>.json`` inside the
    subprocess CWD. We use ``model_name_or_path="openjarvis-harness"``,
    ``run_id=f"oj-{instance_id}"`` in :func:`_run_harness`.
    """
    fname = f"openjarvis-harness.{run_id}.json"
    p = cache / fname
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _run_harness(instance_id: str, patch: str, timeout_s: int) -> Dict[str, Any]:
    """Hand one prediction to ``python -m swebench.harness.run_evaluation``.

    Returns ``{"success": bool, "score": float, "details": dict}``.
    """
    _apply_patches_once()
    backend = os.environ.get("SWEBENCH_BACKEND", "modal").lower()
    cache = _harness_cache_dir()
    run_id = f"oj-{instance_id}"

    # Defend against stale reports: ``run_id`` is deterministic per
    # instance, the cache dir is shared across runs, and ``_find_report``
    # globs by filename. If a prior subprocess crashed mid-run (or was
    # killed by timeout) and left a stale JSON, we'd silently read that
    # old verdict as the current result. Delete it up front.
    stale = cache / f"openjarvis-harness.{run_id}.json"
    if stale.exists():
        try:
            stale.unlink()
        except OSError as exc:
            logger.warning("Could not remove stale report %s: %s", stale, exc)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        preds_path = tmp_path / "predictions.jsonl"
        preds_path.write_text(json.dumps({
            "instance_id": instance_id,
            "model_name_or_path": "openjarvis-harness",
            "model_patch": patch,
        }) + "\n")

        cmd = [
            sys.executable, "-m", "swebench.harness.run_evaluation",
            "--predictions_path", str(preds_path),
            "--max_workers", "1",
            "--run_id", run_id,
            "--dataset_name", "SWE-bench/SWE-bench_Verified",
            "--instance_ids", instance_id,
        ]
        if backend == "modal":
            cmd += ["--modal", "true"]

        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout_s, cwd=str(cache),
        )

        report = _find_report(cache, instance_id, run_id)
        if report is None:
            return {
                "success": False,
                "score": 0.0,
                "details": {
                    "reason": "no_report",
                    "stdout": proc.stdout[-2000:],
                    "stderr": proc.stderr[-2000:],
                },
            }

        # The fix from `rescore.py`: read `resolved_ids` (current schema)
        # not `resolved_instances` (older). Older harness wrote lists into
        # `resolved_instances`; current swebench puts the count there and
        # the actual instance ids in `resolved_ids`.
        resolved_ids = report.get("resolved_ids") or []
        # Belt-and-suspenders: also accept the older list-typed field, in
        # case the user is on an older swebench install.
        if not resolved_ids:
            legacy = report.get("resolved_instances")
            if isinstance(legacy, list):
                resolved_ids = legacy
        resolved = instance_id in resolved_ids
        return {
            "success": resolved,
            "score": 1.0 if resolved else 0.0,
            "details": {"report": report},
        }


# ---------- Scorer ----------

class SWEBenchHarnessScorer(Scorer):
    """SWE-bench Verified scorer that runs the official harness.

    ``score(record, model_answer)`` returns ``(is_correct, details)``:

    - ``is_correct = True`` if the harness marks the instance resolved.
    - ``is_correct = False`` on harness failure or unresolved.
    - ``details`` includes the raw harness report under ``["report"]`` plus
      a ``"patch"`` field with the extracted patch text.
    """

    scorer_id = "swebench_harness"

    def __init__(
        self,
        *,
        timeout_s: int = 1800,
        judge_backend: object = None,  # noqa: ARG002 — CLI factory compat
        judge_model: str = "",         # noqa: ARG002 — CLI factory compat
    ) -> None:
        self._timeout_s = int(timeout_s)

    def score(
        self,
        record: EvalRecord,
        model_answer: str,
    ) -> Tuple[Optional[bool], Dict[str, Any]]:
        if not model_answer or not model_answer.strip():
            return False, {"reason": "empty_response"}

        patch = extract_patch(model_answer)
        if patch is None:
            return False, {"reason": "no_patch_extracted"}

        instance_id = (
            record.metadata.get("instance_id")
            or record.record_id
            or ""
        )
        if not instance_id:
            return False, {"reason": "missing_instance_id"}

        result = _run_harness(instance_id, patch, self._timeout_s)
        details = dict(result.get("details", {}))
        details["patch"] = patch
        return bool(result["success"]), details


__all__ = ["SWEBenchHarnessScorer", "extract_patch"]
