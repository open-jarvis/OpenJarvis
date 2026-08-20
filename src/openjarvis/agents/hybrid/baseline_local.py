"""BaselineLocalAgent — local-only reference for the hybrid ablation.

Mirror of :class:`BaselineCloudAgent` (`baseline_cloud.py`) but the entire
trajectory runs on the local vLLM model. No cloud teacher / router / advisor
is involved — this is the "what does the local model do by itself?" floor
in the n=100 ablation matrix.

On GAIA the agent makes one local call with the formatted prompt (which
already carries the ``FINAL ANSWER:`` reminder from
``_prompts.format_gaia``) and returns the text. On SWE-bench-Verified
the agent delegates to :func:`run_swe_agent_loop` with ``backbone="local"``
so the model gets to run bash and read the repo — same wiring as the
``mini-swe-agent`` cells but driven by the local model.

Construction args mirror :class:`LocalCloudAgent`. The ``local`` block in
the cell registry determines the local model + endpoint; ``cloud`` is
accepted for schema compatibility but unused (and ``cost_usd`` is always
0 — local inference is free).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import LocalCloudAgent
from openjarvis.agents.hybrid.mini_swe_agent import run_swe_agent_loop
from openjarvis.core.registry import AgentRegistry


@AgentRegistry.register("baseline_local")
class BaselineLocalAgent(LocalCloudAgent):
    """Local-only baseline. ``cloud_*`` fields are ignored.

    Configurable knobs via ``cfg``:

    - ``local_max_tokens`` (int, default 4096): max_tokens per GAIA call
      and per turn of the SWE agent loop.
    - ``local_temperature`` (float, default 0.0): sampling temperature
      for the local model.
    - ``swe_use_agent_loop`` (bool, default True for SWE): if False the
      SWE branch falls back to a one-shot blind patch (not recommended;
      kept for parity with other agents).
    - ``swe_max_turns`` (int, default 30): SWE-bench loop turn cap.
    - ``swe_bash_timeout_s`` (int, default 120): bash timeout per turn.
    - ``swe_turn_max_tokens`` (int, default 4096): max_tokens per agent
      turn inside the SWE loop. Falls back to ``local_max_tokens``.
    """

    agent_id = "baseline_local"

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

        local_max_tokens = int(cfg.get("local_max_tokens", 4096))
        local_temperature = float(cfg.get("local_temperature", 0.0))

        if not self._local_model or not self._local_endpoint:
            raise ValueError(
                "baseline_local requires `local.model` and `local.endpoint` "
                "in the cell registry — got "
                f"model={self._local_model!r}, endpoint={self._local_endpoint!r}"
            )

        if is_swe:
            use_loop = bool(cfg.get("swe_use_agent_loop", True))
            if use_loop:
                out = run_swe_agent_loop(
                    task,
                    backbone="local",
                    backbone_model=self._local_model,
                    local_endpoint=self._local_endpoint,
                    initial_prompt=input,
                    max_turns=int(cfg.get("swe_max_turns", 30)),
                    bash_timeout=int(cfg.get("swe_bash_timeout_s", 120)),
                    output_cap=int(cfg.get("swe_output_cap", 10_000)),
                    turn_max_tokens=int(
                        cfg.get("swe_turn_max_tokens", local_max_tokens)
                    ),
                    trace_prefix="baseline_local",
                )
                meta = {
                    "tokens_local": out["tokens_in"] + out["tokens_out"],
                    "tokens_cloud": 0,
                    "cost_usd": 0.0,
                    "turns": out["turns"],
                    # SWE-bench: one bash invocation per agent turn.
                    "tool_calls": int(out["turns"]),
                    "traces": {
                        "backbone": "local",
                        "max_turns_hit": out["max_turns_hit"],
                        "patch_chars": len(out["patch"]),
                        "final_summary": out["final_summary"],
                    },
                }
                return out["answer"], meta

            # One-shot blind patch fallback on SWE (no bash).
            text, p_tok, c_tok = self._call_vllm(
                self._local_model,
                self._local_endpoint,
                user=input,
                max_tokens=local_max_tokens,
                temperature=local_temperature,
            )
            meta = {
                "tokens_local": p_tok + c_tok,
                "tokens_cloud": 0,
                "cost_usd": 0.0,
                "turns": 1,
                "tool_calls": 0,
                "traces": {
                    "mode": "one_shot_swe",
                    "backbone": "local",
                },
            }
            return text, meta

        # GAIA branch — one-shot local call. Matches baseline_cloud's
        # GAIA one-shot path (no web_search; baseline_cloud's web_search
        # is Anthropic server-side only and has no local equivalent).
        text, p_tok, c_tok = self._call_vllm(
            self._local_model,
            self._local_endpoint,
            user=input,
            max_tokens=local_max_tokens,
            temperature=local_temperature,
        )
        meta = {
            "tokens_local": p_tok + c_tok,
            "tokens_cloud": 0,
            "cost_usd": 0.0,
            "turns": 1,
            "web_search_uses": 0,
            "tool_calls": 0,
            "traces": {
                "mode": "one_shot",
                "is_swe": is_swe,
                "backbone": "local",
            },
        }
        return text, meta


__all__ = ["BaselineLocalAgent"]
