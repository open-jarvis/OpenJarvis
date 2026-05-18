"""ConductorAgent — static-DAG planner (Sakana AI, arXiv 2512.04388).

Stage-1 inference-only repro. The paper's trained Qwen2.5-7B conductor is
not released; we substitute a strong zero-shot cloud planner (default
Opus) and run the same plan-then-execute machinery.

Pipeline per task:

1. **Plan** — the conductor reads the question + numbered worker pool
   and emits three lists ``(model_id, subtasks, access_list)`` in JSON,
   up to 5 steps.
2. **Execute** — for each step ``i``: build the worker prompt from
   ``subtasks[i]`` + the concatenated prior ``(subtask, output)``
   messages selected by ``access_list[i]``; call worker
   ``model_id[i]``; the final answer is the output of the last step.

On plan parse failure: retry once with a stricter "JSON only" prompt;
on second failure, fall back to a single call to the strongest available
worker (last in the pool by convention).

Workers come from ``cfg["workers"]`` or a sensible default pool
(local Qwen if vLLM is up, plus Opus 4.7 and gpt-5-mini).

Hybrid harness result: ``conductor-swebenchverified-opusplan-30`` = 0.367
acc / $0.22 per task — +10pp vs baseline-cloud at ~15× cheaper.

Ported from ``hybrid-local-cloud-compute/adapters/conductor_adapter.py``.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import LocalCloudAgent
from openjarvis.agents.hybrid._prices import (
    is_gpt5_family,
    supports_temperature,
)
from openjarvis.agents.hybrid.mini_swe_agent import (
    _clone_repo,
    _extract_diff,
    run_swe_agent_loop,
)
from openjarvis.core.registry import AgentRegistry

CONDUCTOR_SYS = """\
Your role as an assistant involves obtaining answers to questions by an iterative \
process of querying powerful language models, each with a different skillset. \
You will be given the user question and a list of available numbered language \
models with their metadata.

Plan up to 5 workflow steps. Output THREE lists of equal length:

  model_id:    integers (0..N-1) selecting which numbered model handles each step.
  subtasks:    natural-language instructions (one string per step) for that model.
  access_list: for each step, a list of prior step indices whose (subtask, output)
               should be included in that step's prompt; use the string "all" to
               include every prior step, or [] for none. The first step must use [].

Pick the smallest number of steps that will reliably produce a correct final answer. \
The user only sees the output of the LAST step, so make sure the last step both \
solves the task and produces the final user-facing answer in the requested format.

Respond ONLY with a single JSON object (no prose, no markdown fence) with exactly \
these three keys:

  {"model_id": [...], "subtasks": [...], "access_list": [...]}
"""

CONDUCTOR_STRICTER = (
    "Your previous response was not valid JSON or was missing required fields. "
    "Reply with ONLY a single JSON object — no prose, no code fences, no commentary "
    "— containing exactly the three keys model_id (list[int]), subtasks (list[str]), "
    "and access_list (list[list[int] or \"all\"]) of equal length, at most 5 entries, "
    "and access_list[0] must be [] (an empty list)."
)


# ---------- Plan parsing ----------

def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    return s


def _try_json(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None


def _try_literal(s: str):
    """Fallback for the paper's literal Python-list output style."""
    out = {}
    for key in ("model_id", "subtasks", "access_list"):
        m = re.search(
            rf"{key}\s*=\s*(\[[^\]]*\](?:\s*\+\s*\[[^\]]*\])*)", s, re.DOTALL
        )
        if not m:
            return None
        try:
            out[key] = ast.literal_eval(m.group(1))
        except Exception:
            return None
    return out


def _validate_plan(plan: Any, n_workers: int) -> Optional[str]:
    if not isinstance(plan, dict):
        return "plan is not a dict"
    for k in ("model_id", "subtasks", "access_list"):
        if k not in plan:
            return f"missing key {k!r}"
    mi, st, al = plan["model_id"], plan["subtasks"], plan["access_list"]
    if not (isinstance(mi, list) and isinstance(st, list) and isinstance(al, list)):
        return "fields must be lists"
    if not (len(mi) == len(st) == len(al)):
        return f"unequal lengths: {len(mi)}/{len(st)}/{len(al)}"
    if not (1 <= len(mi) <= 5):
        return f"need 1..5 steps, got {len(mi)}"
    for i, m in enumerate(mi):
        if not isinstance(m, int) or not (0 <= m < n_workers):
            return f"model_id[{i}]={m!r} out of range 0..{n_workers - 1}"
    for i, s in enumerate(st):
        if not isinstance(s, str) or not s.strip():
            return f"subtasks[{i}] must be non-empty string"
    for i, a in enumerate(al):
        if a == "all":
            continue
        if not isinstance(a, list):
            return f"access_list[{i}] must be list or \"all\""
        for j in a:
            if not isinstance(j, int) or not (0 <= j < i):
                return f"access_list[{i}] has bad ref {j!r}"
    return None


def _parse_plan(text: str, n_workers: int):
    s = _strip_fences(text)
    for candidate in (_try_json(s), _try_literal(s)):
        if candidate is None:
            continue
        err = _validate_plan(candidate, n_workers)
        if err is None:
            return candidate, None
    return None, "could not parse a valid plan"


# ---------- Worker pool ----------

def _vllm_alive(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(
            base_url.rstrip("/") + "/models", timeout=3
        ) as r:
            return r.status == 200
    except Exception:
        return False


def _default_pool(local_model: Optional[str], local_endpoint: Optional[str]) -> List[Dict[str, Any]]:
    pool: List[Dict[str, Any]] = []
    if local_model and local_endpoint and _vllm_alive(local_endpoint):
        pool.append({
            "id": len(pool),
            "name": "local-qwen",
            "endpoint": "vllm",
            "model": local_model,
            "base_url": local_endpoint,
            "api_key": "EMPTY",
            "description": (
                "Open-weights Qwen3.5 served locally. Cheap and fast. Good at "
                "concise extraction, formatting, arithmetic on given data; "
                "weaker at open-domain factual recall and complex reasoning."
            ),
        })
    pool.append({
        "id": len(pool),
        "name": "frontier-anthropic",
        "endpoint": "anthropic",
        "model": "claude-opus-4-7",
        "description": (
            "Frontier reasoning model. Strongest at multi-step reasoning, "
            "careful instruction following, code, and writing. Expensive; "
            "use sparingly for hard or decisive steps."
        ),
    })
    pool.append({
        "id": len(pool),
        "name": "frontier-openai-mini",
        "endpoint": "openai",
        "model": "gpt-5-mini",
        "description": (
            "Mid-tier OpenAI model. Solid general knowledge and reasoning at "
            "a fraction of frontier cost. Good default for retrieval-style or "
            "broad-knowledge questions."
        ),
    })
    return pool


def _format_worker_pool(workers: List[Dict[str, Any]]) -> str:
    return "\n".join(
        f"Model {w['id']} ({w['name']}): {w['description']}" for w in workers
    )


def _build_conductor_prompt(question: str, workers: List[Dict[str, Any]]) -> str:
    return (
        f"Available models:\n{_format_worker_pool(workers)}\n\n"
        f"User question:\n{question}\n"
    )


def _build_step_prompt(
    question: str,
    subtask: str,
    prior_steps: List[Dict[str, Any]],
    access: "list[int] | str",
) -> str:
    indices = list(range(len(prior_steps))) if access == "all" else list(access)
    pieces = [f"User question:\n{question}\n"]
    if indices:
        pieces.append("Previous routing messages:")
        for j in indices:
            ps = prior_steps[j]
            pieces.append(
                f"[Step {j} subtask]\n{ps['subtask']}\n"
                f"[Step {j} response]\n{ps['output']}"
            )
    pieces.append(f"Your subtask:\n{subtask}")
    return "\n\n".join(pieces)


# ---------- Worker invocation ----------

def _call_worker(
    worker: Dict[str, Any], prompt: str, cfg: Dict[str, Any]
) -> Tuple[str, int, int, bool]:
    """Returns (text, p_tok, c_tok, is_local)."""
    ep = (worker.get("endpoint") or "openai").lower()
    max_tok = int(cfg.get("worker_max_tokens", 4096))
    temp = float(cfg.get("worker_temperature", 0.2))

    if ep == "vllm":
        text, p, c = LocalCloudAgent._call_vllm(
            worker["model"],
            worker["base_url"],
            user=prompt,
            max_tokens=max_tok,
            temperature=temp,
            enable_thinking=False,
        )
        return text, p, c, True
    if ep == "openai":
        text, p, c = LocalCloudAgent._call_openai(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=(1.0 if is_gpt5_family(worker["model"]) else temp),
        )
        return text, p, c, False
    if ep == "anthropic":
        eff_temp = temp if supports_temperature(worker["model"]) else 0.0
        text, p, c, _ = LocalCloudAgent._call_anthropic(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=eff_temp,
        )
        return text, p, c, False
    raise ValueError(f"unsupported worker endpoint: {ep!r}")


def _swe_worker_step(
    worker: Dict[str, Any],
    task: Dict[str, Any],
    prompt: str,
    cfg: Dict[str, Any],
    workdir: Path,
    step_idx: int,
) -> Tuple[str, int, int, bool]:
    """Run one Conductor worker step as a mini-SWE-agent subloop on a shared
    workdir. Returns (final_summary_or_diff, tokens_in, tokens_out, is_local)
    in the same shape as ``_call_worker``."""
    ep = (worker.get("endpoint") or "openai").lower()
    if ep == "vllm":
        backbone, model, endpoint, is_local = (
            "local", worker["model"], worker.get("base_url"), True,
        )
    elif ep == "anthropic":
        backbone, model, endpoint, is_local = (
            "cloud", worker["model"], None, False,
        )
    else:
        # OpenAI workers (gpt-5-mini etc.) aren't supported as agent-loop
        # backbones today (the loop's tool-call format is Anthropic- or
        # OpenAI-via-vllm-shaped only). Fall back to one-shot for those —
        # SWE-bench-wise they were already weak; this preserves behavior.
        return _call_worker(worker, prompt, cfg)
    out = run_swe_agent_loop(
        task,
        backbone=backbone,
        backbone_model=model,
        cloud_endpoint="anthropic" if backbone == "cloud" else "anthropic",
        local_endpoint=endpoint,
        initial_prompt=prompt,
        max_turns=int(cfg.get("swe_max_turns", 30)),
        bash_timeout=int(cfg.get("swe_bash_timeout_s", 120)),
        output_cap=int(cfg.get("swe_output_cap", 10_000)),
        turn_max_tokens=int(cfg.get("swe_turn_max_tokens", 4096)),
        trace_prefix=f"conductor_step{step_idx}",
        workdir=workdir,
    )
    return out["final_summary"] or out["answer"], out["tokens_in"], out["tokens_out"], is_local


@AgentRegistry.register("conductor")
class ConductorAgent(LocalCloudAgent):
    """Plan-then-execute static DAG over a worker pool. See module docstring."""

    agent_id = "conductor"

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        question = input
        cfg = self._cfg
        workers = cfg.get("workers") or _default_pool(
            self._local_model, self._local_endpoint
        )
        if not workers:
            raise RuntimeError("conductor: empty worker pool")

        # 1. Plan
        user = _build_conductor_prompt(question, workers)
        plan_text, p_in, p_out = self._call_cloud(
            user=user,
            system=CONDUCTOR_SYS,
            max_tokens=int(cfg.get("conductor_max_tokens", 2048)),
            temperature=0.0,
        )
        plan, err = _parse_plan(plan_text, len(workers))
        parse_attempts = [{"text": plan_text, "error": err}]
        conductor_p_in, conductor_p_out = p_in, p_out

        if plan is None:
            plan_text2, p_in2, p_out2 = self._call_cloud(
                user=user,
                system=CONDUCTOR_SYS + "\n\n" + CONDUCTOR_STRICTER,
                max_tokens=int(cfg.get("conductor_max_tokens", 2048)),
                temperature=0.0,
            )
            conductor_p_in += p_in2
            conductor_p_out += p_out2
            plan, err2 = _parse_plan(plan_text2, len(workers))
            parse_attempts.append({"text": plan_text2, "error": err2})

        fallback_used = False
        if plan is None:
            fallback_used = True
            plan = {
                "model_id":    [len(workers) - 1],
                "subtasks":    [question],
                "access_list": [[]],
            }

        self.record_trace_event({
            "kind": "conductor_plan",
            "plan": plan,
            "fallback_used": fallback_used,
            "parse_attempts": parse_attempts,
            "workers": [
                {k: v for k, v in w.items() if k != "api_key"}
                for w in workers
            ],
        })

        # 2. Execute
        # If we're on a SWE-bench task AND cfg["swe_use_agent_loop"] is on,
        # every worker step runs through run_swe_agent_loop on a SHARED
        # workdir so step N+1 builds on step N's edits. The final patch is
        # whatever `git diff` produces after the last step.
        task_meta = (context.metadata.get("task") if context is not None else {}) or {}
        swe_mode = (
            bool(cfg.get("swe_use_agent_loop"))
            and bool(task_meta.get("problem_statement"))
            and bool(task_meta.get("repo"))
            and bool(task_meta.get("base_commit"))
        )
        steps: List[Dict[str, Any]] = []
        tokens_local = 0
        tokens_cloud = 0
        cost = 0.0
        final_answer = ""
        shared_workdir: Optional[Path] = None

        try:
            if swe_mode:
                shared_workdir = Path(tempfile.mkdtemp(
                    prefix=f"conductor-swe-{task_meta.get('task_id','x')}-"
                ))
                _clone_repo(task_meta["repo"], task_meta["base_commit"], shared_workdir)
                self.record_trace_event({
                    "kind": "conductor_swe_workdir",
                    "workdir": str(shared_workdir),
                    "repo": task_meta["repo"],
                    "base_commit": task_meta["base_commit"],
                })

            for i, (mid, subtask, access) in enumerate(
                zip(plan["model_id"], plan["subtasks"], plan["access_list"])
            ):
                worker = workers[mid]
                prompt = _build_step_prompt(question, subtask, steps, access)
                self.record_trace_event({
                    "kind": "conductor_step_dispatch",
                    "step_idx": i,
                    "worker_id": mid,
                    "worker_name": worker["name"],
                    "worker_model": worker["model"],
                    "subtask": subtask,
                    "access": access,
                    "prompt": prompt,
                    "swe_mode": swe_mode,
                })

                if swe_mode:
                    text, w_in, w_out, is_local = _swe_worker_step(
                        worker, task_meta, prompt, cfg, shared_workdir, i,
                    )
                else:
                    text, w_in, w_out, is_local = _call_worker(worker, prompt, cfg)

                if is_local:
                    tokens_local += w_in + w_out
                else:
                    tokens_cloud += w_in + w_out
                    cost += self.cost_usd(worker["model"], w_in, w_out)
                steps.append({
                    "step_idx": i,
                    "model_id": mid,
                    "worker_name": worker["name"],
                    "worker_model": worker["model"],
                    "subtask": subtask,
                    "access": access,
                    "output": text,
                    "tokens_in": w_in,
                    "tokens_out": w_out,
                })
                final_answer = text

            # For SWE mode, the authoritative patch is whatever lives in
            # the working tree at the end — replace whatever the last
            # worker emitted with the full diff (so scoring picks it up).
            if swe_mode and shared_workdir is not None:
                patch = _extract_diff(shared_workdir)
                if patch.strip():
                    final_answer = (
                        f"{final_answer}\n\n```diff\n{patch}```"
                        if final_answer else f"```diff\n{patch}```"
                    )
        finally:
            if shared_workdir is not None:
                shutil.rmtree(shared_workdir, ignore_errors=True)

        # Conductor (planner) cost goes into cloud bucket
        cost += self.cost_usd(self._cloud_model, conductor_p_in, conductor_p_out)
        tokens_cloud += conductor_p_in + conductor_p_out

        traces = [
            (s["step_idx"], s["model_id"], s["subtask"], s["output"])
            for s in steps
        ]

        meta = {
            "tokens_local": tokens_local,
            "tokens_cloud": tokens_cloud,
            "cost_usd": cost,
            "turns": len(steps) + 1,  # planner + N execution steps
            "traces": {
                "steps": traces,
                "plan": plan,
                "fallback_used": fallback_used,
                "parse_attempts": parse_attempts,
                "workers": [
                    {k: v for k, v in w.items() if k != "api_key"}
                    for w in workers
                ],
            },
        }
        return final_answer, meta


__all__ = ["ConductorAgent"]
