"""SkillOrchestraAgent — the OpenJarvis harness entry point.

A faithful port of the SkillOrchestra eval orchestrator (arXiv:2602.19672,
``orchestration/eval_frames.py``). The agent runs the multi-round
search -> reasoning -> answer loop in :mod:`.orchestrator`, using the
verbatim ``eval_orchestrator`` prompts, the ``StageSkillHandbook`` +
``RoutingStrategy`` machinery, real Python subprocess execution, and a
model-alias pool collapsed onto the cell's local/cloud pair.

Three things the original needs that this environment does not have, and
how each is handled (see ``README.md`` in this package for the full
note):

* **Learned handbook** — produced offline by the explore->learn->select
  pipeline. With no handbook the orchestrator runs ``routing_strategy =
  "none"`` (the original's baseline mode). Point ``method_cfg.handbook_path``
  at a ``StageSkillHandbook`` JSON to enable skill routing.
* **FAISS wiki retriever** — the ``search`` tool POSTs to it when
  ``method_cfg.retriever_url`` is set; otherwise it falls back to
  Anthropic ``web_search``.
* **6+ model pool** — the alias tiers collapse onto the cell's local +
  cloud models; override per alias with ``method_cfg.model_pool``.

SWE-bench cells are out of scope for the original (it is a QA
orchestrator). They run the cloud backbone through the shared mini SWE
agent loop instead.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.core.registry import AgentRegistry

from .._base import LocalCloudAgent
from ..mini_swe_agent import run_swe_agent_loop
from .orchestrator import run_orchestrator
from .stage_router import StageSkillHandbook

_VALID_STRATEGIES = {
    "none",
    "router_decides",
    "analyze_model_decide",
    "weighted_avg",
    "weakest_skill",
    "strongest_skill",
}


@AgentRegistry.register("skillorchestra")
class SkillOrchestraAgent(LocalCloudAgent):
    """Inference-time skill-aware orchestrator. See module docstring."""

    agent_id = "skillorchestra"

    # ------------------------------------------------------------------

    def _is_soft_failure(self, exc: BaseException) -> Optional[str]:
        # Malformed orchestrator / router JSON -> soft-fail row, matching
        # the rest of the hybrid family.
        if isinstance(exc, (ValueError, json.JSONDecodeError)):
            return f"{type(exc).__name__}: {str(exc)[:120]}"
        return None

    def _load_handbook(self) -> Optional[StageSkillHandbook]:
        """Load the StageSkillHandbook from ``method_cfg.handbook_path``.

        A relative path resolves against this package directory so the
        shipped ``handbook_seed.json`` works out of the box. Any load
        failure degrades to ``None`` (orchestrator runs baseline mode).
        """
        path = self._cfg.get("handbook_path")
        if not path:
            return None
        p = Path(path)
        if not p.is_absolute():
            p = Path(__file__).parent / p
        if not p.exists():
            return None
        try:
            return StageSkillHandbook.load(str(p))
        except Exception:  # noqa: BLE001
            return None

    # ------------------------------------------------------------------

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        cfg = self._cfg
        task_meta = (context.metadata.get("task") if context is not None else {}) or {}

        # SWE-bench: the original SkillOrchestra has no code-repo mode.
        # Run the cloud backbone through the shared mini SWE agent loop.
        swe_mode = (
            bool(cfg.get("swe_use_agent_loop"))
            and bool(task_meta.get("problem_statement"))
            and bool(task_meta.get("repo"))
            and bool(task_meta.get("base_commit"))
        )
        if swe_mode:
            out = run_swe_agent_loop(
                task_meta,
                backbone="cloud",
                backbone_model=self._cloud_model,
                cloud_endpoint=self._cloud_endpoint,
                initial_prompt=input,
                max_turns=int(cfg.get("swe_max_turns", 30)),
                bash_timeout=int(cfg.get("swe_bash_timeout_s", 120)),
                output_cap=int(cfg.get("swe_output_cap", 10_000)),
                turn_max_tokens=int(cfg.get("swe_turn_max_tokens", 4096)),
                trace_prefix="skillorch_swe",
            )
            meta = {
                "tokens_local": 0,
                "tokens_cloud": out["tokens_in"] + out["tokens_out"],
                "cost_usd": out["cost_usd"],
                "turns": int(out["turns"]),
                "tool_calls": int(out["turns"]),
                "web_search_uses": 0,
                "traces": {
                    "mode": "swe_agent_loop",
                    "backbone_model": self._cloud_model,
                    "note": "original SkillOrchestra is QA-only; SWE uses the cloud backbone",
                },
            }
            return out["answer"], meta

        # QA path — the faithful eval orchestrator.
        handbook = self._load_handbook()
        strategy = str(cfg.get("routing_strategy", "none"))
        if strategy not in _VALID_STRATEGIES:
            raise ValueError(
                f"routing_strategy {strategy!r} unknown; valid: "
                f"{sorted(_VALID_STRATEGIES)}"
            )
        if handbook is None and strategy in ("router_decides", "analyze_model_decide"):
            # These two strategies just honor the orchestrator's own model
            # pick — they need no learned skill data, so an empty handbook
            # is enough to run the skill-orchestrator prompt + loop.
            handbook = StageSkillHandbook()
        if handbook is None:
            # No handbook -> baseline routing, exactly like the original.
            strategy = "none"

        return run_orchestrator(
            self,
            input,
            cfg=cfg,
            handbook=handbook,
            strategy=strategy,
        )


__all__ = ["SkillOrchestraAgent"]
