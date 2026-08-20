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
   Wrap the write in try/except. In swebench 4.x the call site is
   ``ModalSandboxRuntime.__init__`` → ``self.write_file(...)`` →
   ``self.sandbox.open(path, "w")``; in older swebench it was a free
   ``set_cpu_quota`` function. We patch both: ``write_file`` swallows
   FileNotFoundError for cgroup paths, and ``set_cpu_quota`` (if present)
   is wrapped too.

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
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from openjarvis.core.paths import get_cache_dir
from openjarvis.evals.core.scorer import Scorer
from openjarvis.evals.core.types import EvalRecord

logger = logging.getLogger(__name__)


def _run_subprocess_hard_timeout(
    cmd: list,
    *,
    timeout_s: int,
    cwd: str,
) -> "subprocess.CompletedProcess":
    """Run ``cmd`` with a timeout that is actually enforced.

    ``subprocess.run(..., capture_output=True, timeout=...)`` has a
    well-known deadlock: on timeout it kills only the *direct* child, then
    calls ``communicate()`` again to drain the pipes — but if that child
    spawned grandchildren that inherited the stdout/stderr fds (the Modal
    ``swebench`` harness does exactly this), those grandchildren keep the
    pipe open and the drain blocks **forever**. The nominal timeout never
    fires; the runner freezes.

    This helper avoids that by:

    1. Launching the child in its own process group (``start_new_session``)
       so we can signal the whole tree, not just the direct child.
    2. On timeout, ``SIGTERM`` then ``SIGKILL`` the entire group so no
       grandchild survives to hold a pipe open.
    3. Draining output with a *bounded* ``communicate()`` after the kill so
       even a stubborn drain can't hang us.

    Raises :class:`subprocess.TimeoutExpired` (same contract as
    ``subprocess.run``) so callers can keep their existing except clause.
    """
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # own process group → killable as a tree
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        # Kill the whole group, not just the direct child — Modal harness
        # subprocesses fork workers that would otherwise keep pipes open.
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except (ProcessLookupError, PermissionError):
                break
            try:
                proc.wait(timeout=10)
                break
            except subprocess.TimeoutExpired:
                continue
        # Drain whatever is left, but never block on it again — the group
        # is dead, so this returns promptly; the short cap is just paranoia.
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", ""
        raise subprocess.TimeoutExpired(cmd, timeout_s, output=stdout, stderr=stderr)


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


_CGROUP_SOURCE_SENTINEL = "_OPENJARVIS_CGROUP_V2_PATCH_APPLIED"


def _patch_modal_sandbox_source() -> None:
    """Patch ``run_evaluation_modal.py`` on disk so subprocesses inherit it.

    ``_run_harness`` shells out to ``python -m swebench.harness.run_evaluation``,
    which means our in-process monkey-patches don't help. We do a one-time
    idempotent textual rewrite of the swebench module file in the venv:

    - Replace the bare ``self.write_file("/sys/fs/cgroup/cpu/cpu.shares", "2048")``
      with a try/except FileNotFoundError. Marked with a sentinel so we
      don't reapply on every call.

    Only fires when the original unwrapped line is present and the sentinel
    isn't — safe to run repeatedly. No-op if upstream ever fixes this.
    """
    try:
        from swebench.harness.modal_eval import (
            run_evaluation_modal as _m,  # type: ignore[import-not-found]
        )
    except Exception:
        return
    src_path = getattr(_m, "__file__", None)
    if not src_path:
        return
    try:
        src = Path(src_path).read_text()
    except Exception:
        return
    if _CGROUP_SOURCE_SENTINEL in src:
        return
    needle = '        self.write_file("/sys/fs/cgroup/cpu/cpu.shares", "2048")'
    if needle not in src:
        # Upstream changed the line — bail rather than apply blindly.
        return
    replacement = (
        "        # " + _CGROUP_SOURCE_SENTINEL + "\n"
        "        try:\n"
        '            self.write_file("/sys/fs/cgroup/cpu/cpu.shares", "2048")\n'
        "        except FileNotFoundError:\n"
        "            pass  # cgroup v2 Modal sandbox — path missing is fine\n"
    )
    new_src = src.replace(needle + "\n", replacement, 1)
    try:
        Path(src_path).write_text(new_src)
    except Exception:
        return


def _patch_modal_sandbox_write_file() -> None:
    """Make ``ModalSandboxRuntime.write_file`` survive cgroup-v2 sandboxes.

    swebench 4.x removed ``set_cpu_quota`` and inlined the cgroup write in
    ``ModalSandboxRuntime.__init__`` as
    ``self.write_file("/sys/fs/cgroup/cpu/cpu.shares", "2048")``. Modal v1's
    ``sandbox.open(path, "w")`` raises ``FileNotFoundError`` because the
    sandbox image is cgroup-v2 and the parent dir doesn't exist, which kills
    the whole constructor before any patch can be applied. We wrap
    ``write_file`` to swallow that specific failure for cgroup paths, while
    still letting real write failures (patch/eval script) surface.
    """
    try:
        from swebench.harness.modal_eval import (
            run_evaluation_modal as _m,  # type: ignore[import-not-found]
        )
    except Exception:
        return
    runtime = getattr(_m, "ModalSandboxRuntime", None)
    if runtime is None:
        return
    if getattr(runtime, "_hybrid_write_file_patched", False):
        return
    orig_write = runtime.write_file

    def patched_write_file(self, file_path: str, content: str):  # type: ignore[no-untyped-def]
        try:
            return orig_write(self, file_path, content)
        except FileNotFoundError:
            # cgroup-v1 paths don't exist in Modal v2 sandboxes — skip
            # silently for those, re-raise for everything else.
            if isinstance(file_path, str) and file_path.startswith("/sys/fs/cgroup/"):
                return None
            raise

    runtime.write_file = patched_write_file  # type: ignore[assignment]
    runtime._hybrid_write_file_patched = True  # type: ignore[attr-defined]


def _sentinel_present_on_disk() -> bool:
    """Return True iff the cgroup-v2 sentinel is in the installed swebench file.

    Used to detect that a ``uv sync`` / pip reinstall has reverted the textual
    patch out from under us while the process is still running. The in-process
    monkey-patches survive that (they live on the imported module object), but
    the subprocess fork in :func:`_run_harness` reads the file fresh and would
    silently regress to the broken version.
    """
    try:
        from swebench.harness.modal_eval import (
            run_evaluation_modal as _m,  # type: ignore[import-not-found]
        )
    except Exception:
        return False
    src_path = getattr(_m, "__file__", None)
    if not src_path:
        return False
    try:
        return _CGROUP_SOURCE_SENTINEL in Path(src_path).read_text()
    except Exception:
        return False


def _apply_patches_once() -> None:
    """Apply all swebench patches; idempotent and resilient to disk reverts.

    The in-process flag short-circuits the common case, but if the on-disk
    sentinel is missing we force a re-apply (covers ``uv sync`` / pip
    reinstall clobbering the textual rewrite while the process is alive).
    """
    global _PATCHES_APPLIED
    if _PATCHES_APPLIED and _sentinel_present_on_disk():
        return
    _patch_modal_cgroup_v2()
    _patch_modal_sandbox_write_file()
    _patch_modal_sandbox_source()
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

    Consolidated under the env-aware OpenJarvis cache root
    (``<openjarvis-home>/cache/swebench``) so it never pollutes the project
    root or scatters across ``$HOME``. Honors ``OPENJARVIS_HOME`` /
    ``XDG_DATA_HOME`` via :func:`openjarvis.core.paths.get_cache_dir`.
    """
    cache = get_cache_dir() / "swebench"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _find_report(
    cache: Path, instance_id: str, run_id: str
) -> Optional[Dict[str, Any]]:
    """Find the harness's report JSON for one instance.

    swebench writes ``<model_name_or_path>.<run_id>.json`` inside the
    subprocess CWD. We use ``model_name_or_path="openjarvis-harness"``;
    ``run_id`` is built by :func:`_build_run_id`.
    """
    fname = f"openjarvis-harness.{run_id}.json"
    p = cache / fname
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


_RUN_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_run_id_part(s: str) -> str:
    """Reduce a free-form string to filesystem-safe ``[A-Za-z0-9._-]+``.

    Both the harness summary filename (``<model>.<run_id>.json``) and the
    per-instance log subtree (``logs/run_evaluation/<run_id>/...``) are
    keyed on ``run_id``, so any character that breaks paths or globs will
    silently corrupt the score. Strip leading/trailing dashes too — those
    look fine but make filenames awkward to manage by hand.
    """
    return _RUN_ID_SAFE_RE.sub("-", s).strip("-")


def _build_run_id(instance_id: str, cell_name: Optional[str]) -> str:
    """Construct a swebench ``run_id`` unique per (cell, instance).

    The harness keys both its "already run, skipping" cache and its report
    file path on ``run_id`` alone, so two concurrent cells scoring the
    same ``instance_id`` with the same ``run_id`` collide: the second
    cell's harness invocation finds the first's report on disk, skips
    actual execution, and our caller silently reads the wrong verdict (or
    ``no_report`` if the two cells race on the summary file write). See
    :func:`_run_harness` for the full failure mode.

    With ``cell_name`` we emit ``oj-<cell>-<instance>``, which keeps the
    intra-cell resume cache working (same cell + same instance → same
    run_id → harness cache hit) while making inter-cell collisions
    impossible. Without ``cell_name`` we fall back to the legacy
    ``oj-<instance>`` form for backwards compat with single-cell callers.
    """
    safe_instance = _sanitize_run_id_part(instance_id)
    if not cell_name:
        return f"oj-{safe_instance}"
    safe_cell = _sanitize_run_id_part(cell_name)
    if not safe_cell:
        return f"oj-{safe_instance}"
    return f"oj-{safe_cell}-{safe_instance}"


def _run_harness(
    instance_id: str,
    patch: str,
    timeout_s: int,
    cell_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Hand one prediction to ``python -m swebench.harness.run_evaluation``.

    Returns ``{"success": bool, "score": float, "details": dict}``.
    """
    _apply_patches_once()
    backend = os.environ.get("SWEBENCH_BACKEND", "modal").lower()
    cache = _harness_cache_dir()
    run_id = _build_run_id(instance_id, cell_name)

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
        preds_path.write_text(
            json.dumps(
                {
                    "instance_id": instance_id,
                    "model_name_or_path": "openjarvis-harness",
                    "model_patch": patch,
                }
            )
            + "\n"
        )

        cmd = [
            sys.executable,
            "-m",
            "swebench.harness.run_evaluation",
            "--predictions_path",
            str(preds_path),
            "--max_workers",
            "1",
            "--run_id",
            run_id,
            "--dataset_name",
            "SWE-bench/SWE-bench_Verified",
            "--instance_ids",
            instance_id,
        ]
        if backend == "modal":
            cmd += ["--modal", "true"]

        try:
            proc = _run_subprocess_hard_timeout(
                cmd,
                timeout_s=timeout_s,
                cwd=str(cache),
            )
        except subprocess.TimeoutExpired as exc:
            # The harness subprocess (and its Modal grandchildren) exceeded
            # the cap and were force-killed as a process group. Record an
            # error verdict rather than letting the exception bubble — the
            # caller's row stays well-formed and the cell keeps moving.
            return {
                "success": False,
                "score": 0.0,
                "details": {
                    "reason": "harness_timeout",
                    "timeout_s": timeout_s,
                    "stdout": (exc.stdout or "")[-2000:],
                    "stderr": (exc.stderr or "")[-2000:],
                },
            }

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
        cell_name: Optional[str] = None,
        judge_backend: object = None,  # noqa: ARG002 — CLI factory compat
        judge_model: str = "",  # noqa: ARG002 — CLI factory compat
    ) -> None:
        self._timeout_s = int(timeout_s)
        # ``cell_name`` namespaces the ``run_id`` so concurrent cells scoring
        # the same SWE instance don't collide on the harness's shared cache.
        # See :func:`_build_run_id` for the failure mode this prevents. Pass
        # the hybrid cell name (e.g. ``"skillorchestra-qwen36-opus47-swe-n100"``)
        # or leave as ``None`` for single-cell callers.
        self._cell_name = cell_name

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

        instance_id = record.metadata.get("instance_id") or record.record_id or ""
        if not instance_id:
            return False, {"reason": "missing_instance_id"}

        result = _run_harness(
            instance_id,
            patch,
            self._timeout_s,
            cell_name=self._cell_name,
        )
        details = dict(result.get("details", {}))
        details["patch"] = patch
        return bool(result["success"]), details


__all__ = [
    "SWEBenchHarnessScorer",
    "extract_patch",
    "_build_run_id",
    "_sanitize_run_id_part",
]
