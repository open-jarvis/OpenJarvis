"""SkillOrchestraAgent — inference-time router (Wang et al., 2026).

Paper: arXiv:2602.19672. The published pipeline is four phases — explore
(run every pool model, collect traces), learn (induce a skill handbook
with per-agent Beta competences and per-skill cost stats), select (Pareto-
optimal handbook subset on a live val set), test. At deployment, the
orchestrator reads the user query, infers skill demands, then picks the
agent that maximizes weighted competence minus λ·cost.

What we reproduce here: the **deployment-time** step only. The full
explore/learn/select pipeline requires multi-model serving + the FRAMES
wiki retriever + a multi-hour LLM-driven learning loop that's out of
scope for the OpenJarvis port (and was out of scope in the hybrid harness).

So this agent uses the orchestrator's *inference logic* with a small
handbook that's synthesized per-task on the fly: cloud (Opus) reads the
question, identifies which skills it needs (from a fixed catalog),
assigns weights, scores each of our two agents (local Qwen-27B vs
cloud Opus) under a cost-discounted weighted-competence rule, then
routes. The chosen agent answers the question.

Hybrid harness result (n=30 GAIA): ``skillorchestra-gaia-qwen27b-opus-30``
= 0.500 acc, $0.02/task — 30× cheaper than baseline-cloud (0.567 / $0.66)
for ~7pp lower accuracy. Best cost-efficient GAIA paradigm by a wide
margin.

Ported from ``hybrid-local-cloud-compute/adapters/skillorchestra_adapter.py``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import LocalCloudAgent
from openjarvis.agents.hybrid._prices import supports_temperature
from openjarvis.agents.hybrid.mini_swe_agent import run_swe_agent_loop
from openjarvis.core.registry import AgentRegistry

# ---------- Skill catalog (compact, GAIA-relevant) ----------
#
# SkillOrchestra learns its taxonomy from execution traces. Without traces
# we use a hand-curated taxonomy covering the kinds of competences GAIA
# actually exercises. Per-agent competences are fixed priors calibrated to
# typical Qwen3.5-27B-FP8 vs Opus 4.7 behavior — what a 1-iteration learn
# would seed before any oracle update.

SKILL_CATALOG: Dict[str, str] = {
    "factual_recall":     "Recall named entities, dates, places, well-known facts from training data without external lookup.",
    "multi_step_reasoning": "Chain several inference steps together (e.g. compose dates, traverse relationships, decompose then aggregate).",
    "arithmetic":         "Exact numeric computation on values already given in the question.",
    "web_grounding":      "Question needs information likely NOT in a small model's parametric memory (rare facts, recent events, niche sources).",
    "long_text_extraction": "Read a long supplied document/context and extract a specific piece.",
    "format_compliance":  "Strict output formatting (e.g. GAIA's `FINAL ANSWER: <answer>` rule, comma-separated lists with no units).",
    "code_or_logic":      "Write or trace code, or apply logical/symbolic constraints precisely.",
}

DEFAULT_AGENT_COMPETENCE: Dict[str, Dict[str, float]] = {
    "local-qwen-27b": {
        "factual_recall":       0.25,
        "multi_step_reasoning": 0.30,
        "arithmetic":           0.55,
        "web_grounding":        0.10,
        "long_text_extraction": 0.55,
        "format_compliance":    0.65,
        "code_or_logic":        0.45,
    },
    "cloud-opus-4-7": {
        "factual_recall":       0.85,
        "multi_step_reasoning": 0.88,
        "arithmetic":           0.85,
        "web_grounding":        0.70,
        "long_text_extraction": 0.90,
        "format_compliance":    0.92,
        "code_or_logic":        0.90,
    },
}

DEFAULT_AGENT_COST_USD: Dict[str, float] = {
    "local-qwen-27b": 0.0,
    "cloud-opus-4-7": 0.30,
}

ROUTER_SYS_MARKER = "<<SKILLORCHESTRA-ROUTER>>"


def _format_catalog() -> str:
    return "\n".join(f"- {sid}: {desc}" for sid, desc in SKILL_CATALOG.items())


def _format_agents(
    competence: Dict[str, Dict[str, float]],
    cost: Dict[str, float],
) -> str:
    lines: List[str] = []
    for aid in competence:
        comp = competence[aid]
        comp_str = ", ".join(f"{k}={v:.2f}" for k, v in comp.items())
        lines.append(f"- **{aid}** (avg cost ${cost.get(aid, 0.0):.2f}/task)")
        lines.append(f"  Skill competences: {comp_str}")
    return "\n".join(lines)


def _build_router_sys(
    competence: Dict[str, Dict[str, float]],
    cost: Dict[str, float],
) -> str:
    return f"""{ROUTER_SYS_MARKER}
You are a skill-aware model router for a compound AI system (the SkillOrchestra deployment-time orchestrator). For each user question you must:

1. Assign weights over the skill catalog (numbers in [0, 1], summing to ~1.0). \
The weights reflect how much each skill matters for *this* question.
2. Score each candidate agent: score(agent) = sum_skill weight_skill * competence(agent, skill) - lambda_cost * avg_cost(agent), with lambda_cost = 0.5.
3. Pick the highest-scoring agent. Tie-break in favor of the cheaper agent.

Skill catalog:
{_format_catalog()}

Agent pool (with learned-prior competences and average costs):
{_format_agents(competence, cost)}

Respond with ONLY a JSON object: {{"chosen_agent": ..., "skill_weights": {{...}}, "reasoning": "..."}}. No prose outside JSON.
"""


def _build_router_schema(agent_ids: List[str]) -> Dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "schema": {
                "type": "object",
                "properties": {
                    "chosen_agent": {"type": "string", "enum": agent_ids},
                    "skill_weights": {
                        "type": "object",
                        "properties": {
                            sid: {"type": "number"} for sid in SKILL_CATALOG
                        },
                        "required": list(SKILL_CATALOG.keys()),
                        "additionalProperties": False,
                    },
                    "reasoning": {"type": "string"},
                },
                "required": ["chosen_agent", "skill_weights", "reasoning"],
                "additionalProperties": False,
            },
        }
    }


def _parse_router_json(text: str) -> Dict[str, Any]:
    s = (text or "").strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    if start == -1:
        raise ValueError(f"router emitted no JSON: {s[:200]!r}")
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])
    raise ValueError(f"router JSON not balanced: {s[:200]!r}")


def _score_agents(
    skill_weights: Dict[str, float],
    competence: Dict[str, Dict[str, float]],
    cost: Dict[str, float],
) -> Dict[str, Dict[str, float]]:
    lam = 0.5
    scores: Dict[str, Dict[str, float]] = {}
    for aid, comps in competence.items():
        comp = sum(
            skill_weights.get(sid, 0.0) * comps[sid] for sid in SKILL_CATALOG
        )
        cost_pen = lam * cost.get(aid, 0.0)
        scores[aid] = {
            "competence": comp,
            "cost_penalty": cost_pen,
            "final_score": comp - cost_pen,
        }
    return scores


@AgentRegistry.register("skillorchestra")
class SkillOrchestraAgent(LocalCloudAgent):
    """Inference-time skill-aware router. See module docstring."""

    agent_id = "skillorchestra"

    def _is_soft_failure(self, exc: BaseException) -> Optional[str]:
        # Empty/unbalanced router JSON — treat as soft failure to match the
        # hybrid adapter's behavior (matches `err=1` rows in the n=30 cell).
        if isinstance(exc, (ValueError, json.JSONDecodeError)):
            return f"{type(exc).__name__}: {str(exc)[:120]}"
        return None

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        cfg = self._cfg
        question = input

        competence: Dict[str, Dict[str, float]] = cfg.get(
            "agent_competence", DEFAULT_AGENT_COMPETENCE
        )
        cost: Dict[str, float] = cfg.get("agent_cost_usd", DEFAULT_AGENT_COST_USD)
        agent_ids = list(competence.keys())
        router_sys = _build_router_sys(competence, cost)
        router_schema = _build_router_schema(agent_ids)

        # 1. Route — Anthropic only (output_config schema is Anthropic-specific
        # in the hybrid adapter). If you need OpenAI routing, swap the prompt
        # to JSON-mode and bypass output_config.
        if self._cloud_endpoint != "anthropic":
            raise ValueError(
                "SkillOrchestra router requires cloud_endpoint='anthropic'; "
                f"got {self._cloud_endpoint!r}"
            )
        router_max = int(cfg.get("router_max_tokens", 1024))
        # Strip temperature for Opus 4.7+; Anthropic's output_config does the schema.
        if supports_temperature(self._cloud_model):
            router_text, r_in, r_out, _ = self._call_anthropic(
                self._cloud_model,
                user=f"Question:\n{question}",
                system=router_sys,
                max_tokens=router_max,
                temperature=0.0,
                output_config=router_schema,
            )
        else:
            router_text, r_in, r_out, _ = self._call_anthropic(
                self._cloud_model,
                user=f"Question:\n{question}",
                system=router_sys,
                max_tokens=router_max,
                output_config=router_schema,
            )

        decision = _parse_router_json(router_text)
        skill_weights: Dict[str, float] = decision.get("skill_weights") or {}
        for sid in SKILL_CATALOG:
            skill_weights.setdefault(sid, 0.0)
        chosen = decision.get("chosen_agent") or ""

        scored = _score_agents(skill_weights, competence, cost)
        if chosen not in competence:
            chosen = max(scored, key=lambda a: scored[a]["final_score"])

        self.record_trace_event({
            "kind": "skillorchestra_route",
            "chosen_agent": chosen,
            "skill_weights": skill_weights,
            "agent_scores": scored,
            "reasoning": decision.get("reasoning", ""),
            "router_raw": router_text,
        })

        tokens_local = 0
        tokens_cloud = r_in + r_out
        run_cost = self.cost_usd(self._cloud_model, r_in, r_out)

        # 2. Execute via chosen agent
        task_meta = (context.metadata.get("task") if context is not None else {}) or {}
        swe_mode = (
            bool(cfg.get("swe_use_agent_loop"))
            and bool(task_meta.get("problem_statement"))
            and bool(task_meta.get("repo"))
            and bool(task_meta.get("base_commit"))
        )
        if chosen == "local-qwen-27b":
            if not (self._local_model and self._local_endpoint):
                raise ValueError(
                    "SkillOrchestra route hit local agent but local_model/"
                    f"local_endpoint missing: {self._local_model!r}/{self._local_endpoint!r}"
                )
            if swe_mode:
                out = run_swe_agent_loop(
                    task_meta,
                    backbone="local",
                    backbone_model=self._local_model,
                    local_endpoint=self._local_endpoint,
                    initial_prompt=question,
                    max_turns=int(cfg.get("swe_max_turns", 30)),
                    bash_timeout=int(cfg.get("swe_bash_timeout_s", 120)),
                    output_cap=int(cfg.get("swe_output_cap", 10_000)),
                    turn_max_tokens=int(cfg.get("swe_turn_max_tokens", 4096)),
                    trace_prefix="skillorch_local",
                )
                ans = out["answer"]
                tokens_local += out["tokens_in"] + out["tokens_out"]
            else:
                ans, w_in, w_out = self._call_vllm(
                    self._local_model,
                    self._local_endpoint,
                    user=question,
                    max_tokens=int(cfg.get("local_max_tokens", 4096)),
                    temperature=float(cfg.get("local_temperature", 0.2)),
                    enable_thinking=False,
                )
                tokens_local += w_in + w_out
            worker_model = self._local_model
        else:
            if swe_mode:
                out = run_swe_agent_loop(
                    task_meta,
                    backbone="cloud",
                    backbone_model=self._cloud_model,
                    cloud_endpoint=self._cloud_endpoint,
                    initial_prompt=question,
                    max_turns=int(cfg.get("swe_max_turns", 30)),
                    bash_timeout=int(cfg.get("swe_bash_timeout_s", 120)),
                    output_cap=int(cfg.get("swe_output_cap", 10_000)),
                    turn_max_tokens=int(cfg.get("swe_turn_max_tokens", 4096)),
                    trace_prefix="skillorch_cloud",
                )
                ans = out["answer"]
                tokens_cloud += out["tokens_in"] + out["tokens_out"]
                run_cost += out["cost_usd"]
            else:
                ans, w_in, w_out, _ = self._call_anthropic(
                    self._cloud_model,
                    user=question,
                    max_tokens=int(cfg.get("cloud_max_tokens", 4096)),
                    temperature=0.0,
                )
                tokens_cloud += w_in + w_out
                run_cost += self.cost_usd(self._cloud_model, w_in, w_out)
            worker_model = self._cloud_model

        meta = {
            "tokens_local": tokens_local,
            "tokens_cloud": tokens_cloud,
            "cost_usd": run_cost,
            "turns": 2,  # router + worker
            "traces": {
                "chosen_agent": chosen,
                "worker_model": worker_model,
                "skill_weights": skill_weights,
                "agent_scores": scored,
                "reasoning": decision.get("reasoning", ""),
            },
        }
        return ans, meta


__all__ = [
    "DEFAULT_AGENT_COMPETENCE",
    "DEFAULT_AGENT_COST_USD",
    "SKILL_CATALOG",
    "SkillOrchestraAgent",
]
