"""BaselineCloudAgent — cloud-only reference for the hybrid ablation.

Used as the "what does the cloud do alone?" row in the n=100 ablation
matrix (see ``.openjarvis/experiments/hybrid/docs/results-table.md``).
No local model is involved — ``local_*`` settings are ignored.

On GAIA the agent makes one cloud call with the formatted prompt (which
already carries the ``FINAL ANSWER:`` format reminder from
``_prompts.format_gaia``) and returns the text. On SWE-bench-Verified
the agent delegates to :func:`run_swe_agent_loop` with ``backbone="cloud"``
so the model gets to run bash and read the repo — same wiring as the
``mini-swe-agent-swebenchverified-opus-*`` cells. As of 2026-05-15
``_loop_cloud`` dispatches to per-endpoint loops for Anthropic, OpenAI,
and Gemini so all three cloud backbones get the proper bash-agent loop
on SWE (previously OpenAI / Gemini SWE cells silently fell back to a
one-shot blind patch — fixed).

Construction args mirror :class:`LocalCloudAgent`. The ``cloud`` block
in the cell registry determines the cloud model + endpoint; ``local``
is accepted for schema compatibility but unused.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import (
    WEB_SEARCH_COST_PER_CALL,
    LocalCloudAgent,
    build_web_search_tool,
    web_search_cfg,
)
from openjarvis.agents.hybrid._prices import cost as estimate_cost
from openjarvis.agents.hybrid._prices import default_max_output_tokens
from openjarvis.agents.hybrid.mini_swe_agent import run_swe_agent_loop
from openjarvis.core.registry import AgentRegistry


@AgentRegistry.register("baseline_cloud")
class BaselineCloudAgent(LocalCloudAgent):
    """Cloud-only baseline used as a reference in the n=100 ablation.

    Configurable knobs via ``cfg``:

    - ``cloud_max_tokens`` (int, default 4096 / 16384 for reasoning models):
      max_tokens per GAIA call and per turn of the SWE agent loop. Default
      jumps to 16384 for GPT-5 family and Gemini 2.5 Pro because those models
      burn the budget on hidden chain-of-thought before emitting visible
      answer text; at 4096 they silently truncated 18–26% of GAIA cells with
      empty answers. Override per-cell via ``method_cfg`` to opt out.
    - ``swe_max_turns`` (int, default 30): SWE-bench loop turn cap.
    - ``swe_bash_timeout_s`` (int, default 120): SWE-bench bash timeout.
    """

    agent_id = "baseline_cloud"

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        cfg = self._cfg
        task: Dict[str, Any] = {}
        if context is not None:
            task = context.metadata.get("task") or {}

        is_swe = bool(
            task.get("problem_statement")
            and task.get("repo")
            and task.get("base_commit")
        )

        if is_swe:
            out = run_swe_agent_loop(
                task,
                backbone="cloud",
                backbone_model=self._cloud_model,
                cloud_endpoint=self._cloud_endpoint,
                initial_prompt=input,
                max_turns=int(cfg.get("swe_max_turns", 30)),
                bash_timeout=int(cfg.get("swe_bash_timeout_s", 120)),
                output_cap=int(cfg.get("swe_output_cap", 10_000)),
                turn_max_tokens=int(
                    cfg.get(
                        "cloud_max_tokens", default_max_output_tokens(self._cloud_model)
                    )
                ),
                trace_prefix="baseline_cloud",
            )
            meta = {
                "tokens_local": 0,
                "tokens_cloud": out["tokens_in"] + out["tokens_out"],
                "cost_usd": out["cost_usd"],
                "turns": out["turns"],
                # SWE-bench: one bash invocation per agent turn.
                "tool_calls": int(out["turns"]),
                "traces": {
                    "backbone": "cloud",
                    "max_turns_hit": out["max_turns_hit"],
                    "patch_chars": len(out["patch"]),
                    "final_summary": out["final_summary"],
                },
            }
            return out["answer"], meta

        # GAIA branch. If `web_search.enabled` is true AND we're on
        # Anthropic, run the multi-turn agent loop with the native
        # server-side web_search tool. Otherwise fall back to the
        # legacy one-shot call (preserves behavior of every existing
        # non-opted-in cell).
        ws_enabled, ws_max_uses = web_search_cfg(cfg)
        gaia_max_turns = int(cfg.get("gaia_max_turns", 8))
        if ws_enabled and self._cloud_endpoint == "anthropic":
            text, p_tok, c_tok, n_searches, turns = self._call_anthropic_agent(
                self._cloud_model,
                user=input,
                max_tokens=int(
                    cfg.get(
                        "cloud_max_tokens", default_max_output_tokens(self._cloud_model)
                    )
                ),
                temperature=0.0,
                tools=[build_web_search_tool(ws_max_uses)],
                max_turns=gaia_max_turns,
            )
            cost = (
                estimate_cost(self._cloud_model, p_tok, c_tok)
                + n_searches * WEB_SEARCH_COST_PER_CALL
            )
            meta = {
                "tokens_local": 0,
                "tokens_cloud": p_tok + c_tok,
                "cost_usd": cost,
                "turns": turns,
                "web_search_uses": n_searches,
                # GAIA: the only tool is web_search.
                "tool_calls": int(n_searches),
                "traces": {
                    "mode": "anthropic_agent_loop",
                    "is_swe": is_swe,
                    "cloud_endpoint": self._cloud_endpoint,
                    "web_search_enabled": True,
                    "web_search_max_uses": ws_max_uses,
                    "n_web_searches": n_searches,
                },
            }
            return text, meta

        if ws_enabled and self._cloud_endpoint != "anthropic":
            # OpenAI / Gemini don't have a parity native web_search tool
            # wired here. Skip cleanly rather than fake one. Cells that
            # want web_search must run on Anthropic until those backends
            # are wired.
            self.record_trace_event(
                {
                    "kind": "web_search_skipped",
                    "reason": "non_anthropic_endpoint",
                    "endpoint": self._cloud_endpoint,
                }
            )

        # One-shot direct cloud call. GAIA only — SWE goes through the
        # mini-SWE-agent loop above (now supports anthropic/openai/gemini).
        text, p_tok, c_tok = self._call_cloud(
            user=input,
            max_tokens=int(
                cfg.get(
                    "cloud_max_tokens", default_max_output_tokens(self._cloud_model)
                )
            ),
            temperature=0.0,
        )
        meta = {
            "tokens_local": 0,
            "tokens_cloud": p_tok + c_tok,
            "cost_usd": estimate_cost(self._cloud_model, p_tok, c_tok),
            "turns": 1,
            "web_search_uses": 0,
            # GAIA one-shot: zero tool calls (no bash, no web_search).
            "tool_calls": 0,
            "traces": {
                "mode": "one_shot",
                "is_swe": is_swe,
                "cloud_endpoint": self._cloud_endpoint,
            },
        }
        return text, meta


__all__ = ["BaselineCloudAgent"]
