"""ToolOrchestraAgent — prompted port of NVlabs ToolOrchestra (arXiv:2511.21689).

The paper RL-trains an 8B Orchestrator (``nvidia/Nemotron-Orchestrator-8B``)
to coordinate basic tools + specialist LLMs + generalist LLMs in
multi-turn agentic loops, ranked #1 on GAIA at release.

The hybrid harness adapter for ToolOrchestra is a documented stub —
running the real thing needs a separate vLLM srun for the Orchestrator-8B
checkpoint, a FAISS wiki retriever, a Tavily API key, and a refactor of
the upstream eval scripts. None of that fits in our cluster allocation.

This port keeps the same scope discipline: **inference-time only,
prompted, no RL**. A cloud model plays the role of the orchestrator,
dispatching to a pool of `(tool | specialist_llm | generalist_llm)`
workers in a reactive loop. The loop is the paradigm; the orchestrator
weights are not.

Why ship this at all if it's not the "real" thing? Because the prompted
upper-bound is useful as a reference point alongside the other paradigms,
and because the OpenJarvis registry needs all six entries for the
distillation pipeline to slot ToolOrchestra in alongside the rest.

Pipeline per task:

1. Orchestrator (cloud) reads question + numbered worker pool.
2. Each turn it emits ``{"action": "call_worker", "worker_id": int,
   "input": str}`` or ``{"action": "final_answer", "answer": str}``.
3. Up to ``max_turns`` (default 6) calls before forcing a final-answer
   prompt; fallback to strongest worker on parse failure.

Workers come from ``cfg["workers"]`` or a sensible default pool (local
Qwen if vLLM up, plus a web-search tool via Anthropic, Opus 4.7,
gpt-5-mini).

Not yet validated end-to-end in the hybrid harness — the hybrid adapter
``raise NotImplementedError``s. Treat results from this paradigm as
preliminary until we have a real ToolOrchestra-8B deployment.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import (
    ANTHROPIC_WEB_SEARCH_TOOL,
    WEB_SEARCH_COST_PER_CALL,
    LocalCloudAgent,
)
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

ORCHESTRATOR_SYS = """\
You are a tool-orchestrating agent. You coordinate a pool of workers to answer the user's question. Each turn you MUST emit exactly one JSON object — no prose, no markdown fences — taking one of two forms:

  {"action": "call_worker", "worker_id": <int>, "input": "<question or instruction for that worker>"}

  {"action": "final_answer", "answer": "<final answer to the user, respecting the question's answer-format rules>"}

Strategy:

- Call cheap / specialized workers first (small local model for extraction or arithmetic on given data; web_search for unknowns; specialist LLMs for code/math).
- Call the frontier worker (Opus / GPT-5) sparingly, for hard reasoning or a final synthesis pass.
- Stop and emit `final_answer` as soon as the previous worker output is sufficient. Do NOT call a worker just to paraphrase.
- The user only sees the `answer` field of `final_answer`, so make sure it follows any answer-format rules in the question.
"""

FORCE_FINAL_PROMPT = (
    "Worker-call budget exhausted. Emit `final_answer` now using everything "
    "you've learned. Respect the question's answer-format rules."
)


def _build_pool_block(workers: List[Dict[str, Any]]) -> str:
    return "\n".join(
        f"Worker {w['id']} ({w['name']}): {w['description']}" for w in workers
    )


def _build_user_prompt(
    question: str,
    workers: List[Dict[str, Any]],
    history: List[Dict[str, Any]],
) -> str:
    pieces = [
        f"Worker pool:\n{_build_pool_block(workers)}",
        f"User question:\n{question}",
    ]
    if history:
        pieces.append("Conversation so far (orchestrator turns and worker outputs):")
        for h in history:
            if h["role"] == "orchestrator":
                pieces.append(f"[Orchestrator turn {h['turn']}]\n{h['raw']}")
            else:
                pieces.append(
                    f"[Worker {h['worker_id']} ({h['worker_name']}) turn {h['turn']}]\n"
                    f"{h['output']}"
                )
    pieces.append(
        "Emit the next JSON action object now — exactly one object, no prose."
    )
    return "\n\n".join(pieces)


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


def _parse_action(text: str) -> Optional[Dict[str, Any]]:
    s = _strip_fences(text)
    # First try direct parse, then balanced-brace extraction.
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and "action" in obj:
            return obj
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(s[start : i + 1])
                    if isinstance(obj, dict) and "action" in obj:
                        return obj
                except json.JSONDecodeError:
                    return None
    return None


def _extract_final_answer_text(text: str) -> str:
    """Best-effort: pull the answer string from a malformed action emission.

    Tries `"answer": "..."` regex, then the GAIA-style `FINAL ANSWER:` line.
    """
    m = re.search(r'"answer"\s*:\s*"((?:\\.|[^"\\])*)"', text, re.DOTALL)
    if m:
        return m.group(1).encode("utf-8").decode("unicode_escape")
    m = re.search(r"FINAL\s*ANSWER\s*:\s*(.+?)\s*$", text, re.IGNORECASE | re.MULTILINE)
    if m:
        return m.group(1).strip()
    return text.strip()


# ---------- Worker pool ----------

def _default_pool(local_model: Optional[str], local_endpoint: Optional[str]) -> List[Dict[str, Any]]:
    pool: List[Dict[str, Any]] = []
    if local_model and local_endpoint:
        pool.append({
            "id": len(pool),
            "name": "local-qwen",
            "type": "vllm",
            "model": local_model,
            "base_url": local_endpoint,
            "description": (
                "Open-weights Qwen3.5 served locally. Cheap and fast. Good at "
                "concise extraction, formatting, arithmetic on given data."
            ),
        })
    pool.append({
        "id": len(pool),
        "name": "web-search",
        "type": "anthropic-web-search",
        "model": "claude-haiku-4-5",
        "description": (
            "Anthropic server-side web_search. Use for facts that need a lookup "
            "(recent events, rare names/dates, niche sources). Returns a digest."
        ),
    })
    pool.append({
        "id": len(pool),
        "name": "frontier-anthropic",
        "type": "anthropic",
        "model": "claude-opus-4-7",
        "description": (
            "Frontier reasoning model. Use for hard multi-step reasoning, "
            "code review, or a final synthesis pass. Expensive — use sparingly."
        ),
    })
    pool.append({
        "id": len(pool),
        "name": "frontier-openai-mini",
        "type": "openai",
        "model": "gpt-5-mini",
        "description": (
            "Mid-tier OpenAI model. Solid general knowledge and reasoning at a "
            "fraction of frontier cost."
        ),
    })
    return pool


def _call_worker(
    worker: Dict[str, Any], prompt: str, cfg: Dict[str, Any]
) -> Tuple[str, int, int, bool, float, int]:
    """Returns (text, p_tok, c_tok, is_local, extra_cost, n_web_searches)."""
    wtype = worker.get("type", "openai")
    max_tok = int(cfg.get("worker_max_tokens", 4096))
    temp = float(cfg.get("worker_temperature", 0.2))

    if wtype == "vllm":
        text, p, c = LocalCloudAgent._call_vllm(
            worker["model"],
            worker["base_url"],
            user=prompt,
            max_tokens=max_tok,
            temperature=temp,
            enable_thinking=False,
        )
        return text, p, c, True, 0.0, 0
    if wtype == "openai":
        eff_temp = 1.0 if is_gpt5_family(worker["model"]) else temp
        text, p, c = LocalCloudAgent._call_openai(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=eff_temp,
        )
        return text, p, c, False, 0.0, 0
    if wtype == "anthropic":
        eff_temp = temp if supports_temperature(worker["model"]) else 0.0
        text, p, c, _ = LocalCloudAgent._call_anthropic(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=eff_temp,
        )
        return text, p, c, False, 0.0, 0
    if wtype == "anthropic-web-search":
        eff_temp = temp if supports_temperature(worker["model"]) else 0.0
        text, p, c, n_searches = LocalCloudAgent._call_anthropic(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=eff_temp,
            tools=[ANTHROPIC_WEB_SEARCH_TOOL],
            tool_choice={"type": "any"},
        )
        extra = n_searches * WEB_SEARCH_COST_PER_CALL
        return text, p, c, False, extra, n_searches
    raise ValueError(f"unsupported worker type: {wtype!r}")


def _swe_call_worker(
    worker: Dict[str, Any],
    prompt: str,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    workdir: Path,
    turn: int,
) -> Tuple[str, int, int, bool, float, int]:
    """SWE-bench worker dispatch: route solver workers through
    run_swe_agent_loop on a shared workdir. Web-search workers fall back
    to the regular one-shot dispatch (search isn't an agent loop)."""
    wtype = worker.get("type", "openai")
    if wtype == "anthropic-web-search":
        # Search workers stay one-shot.
        return _call_worker(worker, prompt, cfg)
    if wtype == "vllm":
        backbone = "local"
        endpoint = worker.get("base_url")
    elif wtype == "anthropic":
        backbone = "cloud"
        endpoint = None
    else:
        # OpenAI workers fall back to one-shot.
        return _call_worker(worker, prompt, cfg)
    out = run_swe_agent_loop(
        task,
        backbone=backbone,
        backbone_model=worker["model"],
        cloud_endpoint="anthropic",
        local_endpoint=endpoint,
        initial_prompt=prompt,
        max_turns=int(cfg.get("swe_max_turns", 30)),
        bash_timeout=int(cfg.get("swe_bash_timeout_s", 120)),
        output_cap=int(cfg.get("swe_output_cap", 10_000)),
        turn_max_tokens=int(cfg.get("swe_turn_max_tokens", 4096)),
        trace_prefix=f"toolorch_turn{turn}",
        workdir=workdir,
    )
    is_local = backbone == "local"
    return (
        out["final_summary"] or out["answer"],
        out["tokens_in"], out["tokens_out"],
        is_local, 0.0, 0,
    )


@AgentRegistry.register("toolorchestra")
class ToolOrchestraAgent(LocalCloudAgent):
    """Prompted multi-turn dispatcher over a mixed worker pool.

    Inference-only port — does NOT use the RL-trained Nemotron-Orchestrator-8B.
    See module docstring for what's missing relative to the published paper.
    """

    agent_id = "toolorchestra"

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        cfg = self._cfg
        question = input
        workers = cfg.get("workers") or _default_pool(
            self._local_model, self._local_endpoint
        )
        if not workers:
            raise RuntimeError("toolorchestra: empty worker pool")

        max_turns = int(cfg.get("max_turns", 6))
        orch_max_tokens = int(cfg.get("orchestrator_max_tokens", 1024))

        task_meta = (context.metadata.get("task") if context is not None else {}) or {}
        swe_mode = (
            bool(cfg.get("swe_use_agent_loop"))
            and bool(task_meta.get("problem_statement"))
            and bool(task_meta.get("repo"))
            and bool(task_meta.get("base_commit"))
        )
        shared_workdir: Optional[Path] = None
        if swe_mode:
            shared_workdir = Path(tempfile.mkdtemp(
                prefix=f"toolorch-swe-{task_meta.get('task_id','x')}-"
            ))
            try:
                _clone_repo(task_meta["repo"], task_meta["base_commit"], shared_workdir)
            except Exception:
                shutil.rmtree(shared_workdir, ignore_errors=True)
                raise
            self.record_trace_event({
                "kind": "toolorchestra_swe_workdir",
                "workdir": str(shared_workdir),
                "repo": task_meta["repo"],
                "base_commit": task_meta["base_commit"],
            })

        # try/finally guards ``shared_workdir`` against exceptions raised
        # anywhere in the turn loop, the worker calls, the fallback, or
        # the diff-extraction step. Without this, at n=500 SWE-bench an
        # exception leaves hundreds of MB of cloned repos in tempdir.
        try:
            history: List[Dict[str, Any]] = []
            tokens_local = 0
            tokens_cloud = 0
            cost = 0.0
            final_answer: Optional[str] = None
            forced_final = False
            parse_failures = 0

            for turn in range(1, max_turns + 1):
                sys_prompt = ORCHESTRATOR_SYS
                if turn == max_turns and final_answer is None:
                    sys_prompt = ORCHESTRATOR_SYS + "\n\n" + FORCE_FINAL_PROMPT
                    forced_final = True

                user = _build_user_prompt(question, workers, history)
                text, o_in, o_out = self._call_cloud(
                    user=user,
                    system=sys_prompt,
                    max_tokens=orch_max_tokens,
                    temperature=0.0,
                )
                tokens_cloud += o_in + o_out
                cost += self.cost_usd(self._cloud_model, o_in, o_out)

                action = _parse_action(text)
                history.append({
                    "role": "orchestrator", "turn": turn, "raw": text, "action": action,
                })
                self.record_trace_event({
                    "kind": "toolorchestra_action",
                    "turn": turn,
                    "action": action,
                    "raw": text,
                })

                if action is None:
                    parse_failures += 1
                    if parse_failures >= 2 or forced_final:
                        final_answer = _extract_final_answer_text(text)
                        break
                    continue

                kind = action.get("action")
                if kind == "final_answer":
                    final_answer = str(action.get("answer", "")).strip()
                    break
                if kind == "call_worker":
                    wid = action.get("worker_id")
                    w_input = action.get("input", "")
                    if not isinstance(wid, int) or not (0 <= wid < len(workers)):
                        parse_failures += 1
                        if parse_failures >= 2 or forced_final:
                            final_answer = _extract_final_answer_text(text)
                            break
                        continue
                    worker = workers[wid]
                    if swe_mode and shared_workdir is not None:
                        w_text, w_in, w_out, is_local, extra_cost, n_searches = (
                            _swe_call_worker(
                                worker, str(w_input), cfg, task_meta,
                                shared_workdir, turn,
                            )
                        )
                    else:
                        w_text, w_in, w_out, is_local, extra_cost, n_searches = (
                            _call_worker(worker, str(w_input), cfg)
                        )
                    if is_local:
                        tokens_local += w_in + w_out
                    else:
                        tokens_cloud += w_in + w_out
                        cost += self.cost_usd(worker["model"], w_in, w_out) + extra_cost
                    history.append({
                        "role": "worker",
                        "turn": turn,
                        "worker_id": wid,
                        "worker_name": worker["name"],
                        "worker_model": worker["model"],
                        "output": w_text,
                        "tokens_in": w_in,
                        "tokens_out": w_out,
                        "n_web_searches": n_searches,
                    })
                    continue
                # Unknown action kind — treat as parse failure.
                parse_failures += 1

            if final_answer is None:
                # Hard fallback: call the strongest worker (last) directly.
                worker = workers[-1]
                if swe_mode and shared_workdir is not None:
                    ans, w_in, w_out, is_local, extra_cost, _ = _swe_call_worker(
                        worker, question, cfg, task_meta,
                        shared_workdir, max_turns + 1,
                    )
                else:
                    ans, w_in, w_out, is_local, extra_cost, _ = _call_worker(
                        worker, question, cfg
                    )
                if is_local:
                    tokens_local += w_in + w_out
                else:
                    tokens_cloud += w_in + w_out
                    cost += self.cost_usd(worker["model"], w_in, w_out) + extra_cost
                history.append({
                    "role": "worker",
                    "turn": max_turns + 1,
                    "worker_id": worker["id"],
                    "worker_name": worker["name"],
                    "worker_model": worker["model"],
                    "output": ans,
                    "tokens_in": w_in,
                    "tokens_out": w_out,
                    "fallback": True,
                })
                final_answer = ans

            # In SWE mode, the authoritative output is the working-tree diff —
            # frame it (the runner extracts it via the scorer's ```diff fence).
            if swe_mode and shared_workdir is not None:
                patch = _extract_diff(shared_workdir)
                if patch.strip():
                    final_answer = (
                        f"{final_answer}\n\n```diff\n{patch}```"
                        if final_answer else f"```diff\n{patch}```"
                    )

            meta = {
                "tokens_local": tokens_local,
                "tokens_cloud": tokens_cloud,
                "cost_usd": cost,
                "turns": len([h for h in history if h["role"] == "orchestrator"]),
                "traces": {
                    "history": history,
                    "forced_final": forced_final,
                    "parse_failures": parse_failures,
                    "workers": workers,
                    "note": (
                        "inference-only port; the RL-trained Nemotron-Orchestrator-8B "
                        "is NOT in the loop. Results are preliminary."
                    ),
                },
            }
            return final_answer, meta
        finally:
            if shared_workdir is not None:
                shutil.rmtree(shared_workdir, ignore_errors=True)


__all__ = ["ToolOrchestraAgent"]
