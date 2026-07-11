"""Braintrust telemetry for the ToolOrchestra rollout.

Each ``run_unified_rollout`` becomes ONE Braintrust trace (root span); the
orchestrator turns and every expert/tool dispatch nest inside it, and the
underlying OpenAI/Anthropic calls (wrapped clients) nest one level deeper — so
you see the full routing tree with inputs/outputs/tokens/cost per node.

On by default. Degrades to a total no-op (never raises, never changes behavior)
when: ``OJ_BRAINTRUST=0``, the ``braintrust`` package isn't installed, or
``BRAINTRUST_API_KEY`` is unset. Concurrency: rollouts run one-per-thread
(ThreadPoolExecutor); threads don't inherit contextvars, so each rollout opens
its own independent root trace and same-thread child calls nest correctly.
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_STATE: dict = {"resolved": False, "enabled": False, "bt": None}


def _truthy(v: str) -> bool:
    return v.strip().lower() not in ("0", "false", "no", "off", "")


def _resolve() -> bool:
    """Lazily decide whether tracing is active and init the logger once."""
    if _STATE["resolved"]:
        return _STATE["enabled"]
    _STATE["resolved"] = True
    if not _truthy(os.getenv("OJ_BRAINTRUST", "1")):  # on by default
        return False
    if not os.getenv("BRAINTRUST_API_KEY"):
        logger.info(
            "braintrust on-by-default but BRAINTRUST_API_KEY unset — tracing disabled"
        )
        return False
    try:
        import braintrust as _bt

        proj_id = os.getenv("OJ_BRAINTRUST_PROJECT_ID")
        if proj_id:
            _bt.init_logger(project_id=proj_id)
        else:
            _bt.init_logger(project=os.getenv("OJ_BRAINTRUST_PROJECT", "toolorchestra"))
        _STATE["bt"] = _bt
        _STATE["enabled"] = True
        logger.info(
            "braintrust tracing ENABLED (%s)",
            f"project_id={proj_id}"
            if proj_id
            else f"project={os.getenv('OJ_BRAINTRUST_PROJECT', 'toolorchestra')}",
        )
    except Exception as exc:  # missing pkg / bad key / init failure — never crash
        logger.warning("braintrust init failed (%s) — tracing disabled", exc)
    return _STATE["enabled"]


def enabled() -> bool:
    return _resolve()


def run_context() -> tuple[dict, list]:
    """Run-level metadata + tags for the ROOT rollout span, sourced from env
    (set by the generation driver). No-op-safe: returns ({}, []) if nothing is
    set, and never raises. Env keys:

    - ``OJ_RUN_LABEL``   — human run label (also stamped on the uploaded dataset).
    - ``OJ_GEN_MODEL``   — SPECIFIC gen model id (e.g. ``Qwen/Qwen3.5-9B``).
    - ``OJ_RUN_STAGE``   — ``prod``|``smoke`` (inferred from the label if unset).
    - ``OJ_CFG_*``       — config knobs (temperature/max_turns/anonymize/...).
    """
    import datetime

    meta: dict = {}
    tags: list = []
    try:
        label = os.getenv("OJ_RUN_LABEL")
        gen_model = os.getenv("OJ_GEN_MODEL")
        stage = os.getenv("OJ_RUN_STAGE")
        if not stage and label:
            stage = "smoke" if "smoke" in label.lower() else "prod"
        if label:
            meta["run_label"] = label
        if gen_model:
            meta["gen_model"] = gen_model
        if stage:
            meta["stage"] = stage
        cfg = {}
        for env_key, key in (
            ("OJ_CFG_TEMPERATURE", "temperature"),
            ("OJ_CFG_MAX_TURNS", "max_turns"),
            ("OJ_CFG_ANONYMIZE", "anonymize"),
            ("OJ_CFG_REJECTION_ONLY", "rejection_only"),
        ):
            v = os.getenv(env_key)
            if v not in (None, ""):
                cfg[key] = v
        if cfg:
            meta["config"] = cfg
        date = datetime.date.today().isoformat()
        tags = [t for t in (gen_model, stage, date) if t]
    except Exception:  # never let telemetry enrichment break a rollout
        return {}, []
    return meta, tags


def wrap_client(client: Any) -> Any:
    """Wrap an OpenAI/Anthropic client so its calls auto-log under the current
    span. Pass-through (unchanged client) when tracing is off or on any error —
    so this is always safe to call at client construction."""
    if not _resolve():
        return client
    try:
        bt = _STATE["bt"]
        mod = type(client).__module__.lower()
        if "anthropic" in mod:
            return bt.wrap_anthropic(client)
        return bt.wrap_openai(client)
    except Exception as exc:
        logger.warning("braintrust wrap_client failed (%s) — using raw client", exc)
        return client


class _NullSpan:
    """No-op span used when tracing is disabled (keeps call sites branch-free)."""

    def log(self, **_kw: Any) -> None:
        pass

    def __enter__(self) -> "_NullSpan":
        return self

    def __exit__(self, *_a: Any) -> bool:
        return False


@contextlib.contextmanager
def span(name: str, *, span_type: str = "task", **fields: Any):
    """Open a Braintrust span (or a no-op). Use as::

        with span("toolorchestra.rollout", input=...) as s:
            ...
            s.log(output=..., metrics=..., metadata=...)

    ``fields`` (input/metadata/...) are forwarded to ``start_span``.
    """
    if not _resolve():
        yield _NullSpan()
        return
    # Guard only span CREATION (so a Braintrust hiccup degrades to a no-op). Do
    # NOT wrap the yielded body in try/except: an exception from the rollout would
    # be thrown into this generator, caught here, and masked by a second yield
    # ("generator didn't stop after throw()"). Let the body's own exceptions
    # propagate through the `with` untouched — Braintrust records + re-raises.
    try:
        cm = _STATE["bt"].start_span(name=name, type=span_type, **fields)
    except Exception as exc:  # span creation failed — run trace-less, never break
        logger.warning(
            "braintrust start_span(%s) failed (%s) — continuing untraced", name, exc
        )
        yield _NullSpan()
        return
    with cm as s:
        yield s
