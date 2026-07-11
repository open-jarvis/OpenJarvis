"""ToolOrchestraAgent — port of NVlabs ToolOrchestra (arXiv:2511.21689).

Two modes, gated by ``method_cfg.orchestrator_mode``:

* ``"prompted"`` (default, legacy): a cloud model (Opus etc.) plays the
  orchestrator, dispatching to a numbered worker pool via JSON
  ``{"action": "call_worker"|"final_answer", ...}`` actions. Useful as
  a prompted upper-bound reference point — NOT the paper's setup.

* ``"rl"`` (paper-faithful): the RL-trained ``nvidia/Orchestrator-8B``
  served on a local vLLM is the orchestrator. It emits OpenAI-style
  ``tool_calls`` (or ``<tool_call>{...}</tool_call>`` text blocks when
  vLLM's tool parser doesn't catch them) for three expert tools —
  ``enhance_reasoning``, ``answer``, ``search`` — exactly as in the
  upstream ``evaluation/tools.json``. Each tool's ``model`` arg
  (``answer-1``, ``reasoner-2``, ``search-3``, …) is mapped to a real
  backend through ``EXPERT_MODEL_MAPPING`` — by default the frontier
  Anthropic worker for `*-1` slots, gpt-5-mini for `*-2`, local Qwen
  for `*-3`. Search routes to the Anthropic server-side web_search.

  We do NOT reproduce the upstream Tavily / FAISS-wiki retriever, the
  code-interpreter sandbox, or the multi-vLLM mix (Llama-3.3-70B,
  Qwen-Math, Qwen-Coder); the expert pool collapses onto our existing
  worker types. Energy-wise, "expert" answers are cloud calls.

Pipeline per task (RL mode):

1. Orchestrator-8B reads `Problem: ...\\n\\n{context}\\n\\nChoose an
   appropriate tool.` with the three tools declared.
2. It emits one ``tool_call`` per turn — ``search`` updates the
   context, ``enhance_reasoning`` appends code/exec output (we run the
   tool as a plain LLM call, no sandbox — the model just gets prose
   back), ``answer`` produces the final answer and the loop stops.
3. Up to ``max_turns`` (default 8) turns; on parse failure we fall
   back to the strongest expert worker.

Prompted-mode pipeline:

1. Orchestrator (cloud) reads question + numbered worker pool.
2. Each turn it emits ``{"action": "call_worker", "worker_id": int,
   "input": str}`` or ``{"action": "final_answer", "answer": str}``.
3. Up to ``max_turns`` (default 6) calls before forcing a final-answer
   prompt; fallback to strongest worker on parse failure.

Workers come from ``cfg["workers"]`` or a sensible default pool (local
Qwen if vLLM up, plus a web-search tool via Anthropic, Opus 4.7,
gpt-5-mini).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import LocalCloudAgent
from openjarvis.agents.hybrid._prices import PRICES
from openjarvis.agents.hybrid.mini_swe_agent import (
    _clone_repo,
    _extract_diff,
)
from openjarvis.agents.hybrid.toolorchestra.clients import (
    _call_orchestrator_with_tool_calls,
)
from openjarvis.agents.hybrid.toolorchestra.experts import (
    _PAPER_CODER_OPENROUTER,
    _expert_for,
    _paper_expert_for,
)
from openjarvis.agents.hybrid.toolorchestra.parsing import (
    _build_user_prompt,
    _extract_final_answer_text,
    _parse_action,
    _parse_rl_tool_call,
)
from openjarvis.agents.hybrid.toolorchestra.prompts import (
    FORCE_FINAL_PROMPT,
    ORCHESTRATOR_SYS,
    RL_ALL_TOOLS,
    RL_ORCHESTRATOR_SYS,
    RL_TOOLS_SPEC,
)
from openjarvis.agents.hybrid.toolorchestra.sandbox import (
    _call_modal_python,
    _extract_first_python_block,
)
from openjarvis.agents.hybrid.toolorchestra.workers import (
    _TOOLORCH_SEARCH_TYPES,
    _call_worker,
    _resolve_worker_pool,
    _swe_call_worker,
)
from openjarvis.core.registry import AgentRegistry


@AgentRegistry.register("toolorchestra")
class ToolOrchestraAgent(LocalCloudAgent):
    """Multi-turn dispatcher over a mixed worker pool.

    Two modes (see module docstring): ``method_cfg.orchestrator_mode``
    is ``"prompted"`` (default, cloud-as-orchestrator) or ``"rl"``
    (paper-faithful, drives ``nvidia/Orchestrator-8B`` on a local vLLM).
    """

    agent_id = "toolorchestra"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Validate `method_cfg.worker_pool` early — surfaces config errors
        # at agent construction rather than on the first task. No-op when
        # the override is absent.
        if self._cfg.get("worker_pool") is not None:
            _resolve_worker_pool(
                self._cfg,
                self._local_model,
                self._local_endpoint,
                self._cloud_model,
                self._cloud_endpoint,
            )
        # Validate `orchestrator_mode` (typo-checked here, not on first task).
        mode = str(self._cfg.get("orchestrator_mode", "prompted")).lower()
        if mode not in ("prompted", "rl"):
            raise ValueError(
                f"toolorchestra: orchestrator_mode must be 'prompted' or 'rl'; "
                f"got {mode!r}"
            )

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        mode = str(self._cfg.get("orchestrator_mode", "prompted")).lower()
        if mode == "rl":
            return self._run_rl(input, context, **kwargs)
        return self._run_prompted(input, context, **kwargs)

    # ------------------------------------------------------------------
    # Legacy prompted-orchestrator path.
    # ------------------------------------------------------------------
    def _run_prompted(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        cfg = self._cfg
        question = input
        # Resolution order (strict replace, no merge):
        #   1. `cfg["workers"]` — legacy direct override, used by tests.
        #   2. `cfg["worker_pool"]` — cell-config override; validated +
        #      $local/$cloud substituted.
        #   3. `_default_pool(...)` — heterogeneous default.
        if cfg.get("workers"):
            workers = cfg["workers"]
        else:
            workers = _resolve_worker_pool(
                cfg,
                self._local_model,
                self._local_endpoint,
                self._cloud_model,
                self._cloud_endpoint,
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
            shared_workdir = Path(
                tempfile.mkdtemp(
                    prefix=f"toolorch-swe-{task_meta.get('task_id', 'x')}-"
                )
            )
            try:
                _clone_repo(task_meta["repo"], task_meta["base_commit"], shared_workdir)
            except Exception:
                shutil.rmtree(shared_workdir, ignore_errors=True)
                raise
            self.record_trace_event(
                {
                    "kind": "toolorchestra_swe_workdir",
                    "workdir": str(shared_workdir),
                    "repo": task_meta["repo"],
                    "base_commit": task_meta["base_commit"],
                }
            )

        # try/finally guards ``shared_workdir`` against exceptions raised
        # anywhere in the turn loop, the worker calls, the fallback, or
        # the diff-extraction step. Without this, at n=500 SWE-bench an
        # exception leaves hundreds of MB of cloned repos in tempdir.
        try:
            history: List[Dict[str, Any]] = []
            tokens_local = 0
            tokens_cloud = 0
            cost = 0.0
            n_web_searches_total = 0
            # tool_calls: bash turns from SWE subloops + web_search uses
            # from GAIA. Orchestrator dispatch turns are NOT counted (they
            # produce text only — calling a worker is one tool call's worth
            # of "delegation" but the actual tool action happens inside).
            tool_calls = 0
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
                history.append(
                    {
                        "role": "orchestrator",
                        "turn": turn,
                        "raw": text,
                        "action": action,
                    }
                )
                self.record_trace_event(
                    {
                        "kind": "toolorchestra_action",
                        "turn": turn,
                        "action": action,
                        "raw": text,
                    }
                )

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
                        (
                            w_text,
                            w_in,
                            w_out,
                            is_local,
                            extra_cost,
                            n_searches,
                            bash_turns,
                        ) = _swe_call_worker(
                            worker,
                            str(w_input),
                            cfg,
                            task_meta,
                            shared_workdir,
                            turn,
                        )
                        tool_calls += bash_turns
                    else:
                        w_text, w_in, w_out, is_local, extra_cost, n_searches = (
                            _call_worker(worker, str(w_input), cfg)
                        )
                    if is_local:
                        tokens_local += w_in + w_out
                    else:
                        tokens_cloud += w_in + w_out
                        cost += self.cost_usd(worker["model"], w_in, w_out) + extra_cost
                    n_web_searches_total += n_searches
                    tool_calls += n_searches
                    history.append(
                        {
                            "role": "worker",
                            "turn": turn,
                            "worker_id": wid,
                            "worker_name": worker["name"],
                            "worker_model": worker["model"],
                            "output": w_text,
                            "tokens_in": w_in,
                            "tokens_out": w_out,
                            "n_web_searches": n_searches,
                        }
                    )
                    continue
                # Unknown action kind — treat as parse failure.
                parse_failures += 1

            if final_answer is None:
                # Hard fallback: call the strongest non-search worker directly.
                # "Strongest" = highest output-token price in `_prices.PRICES`,
                # which tracks model capability tier closely enough for this.
                # Search workers are excluded — they answer fact-lookup
                # questions, not synthesis.
                non_search = [
                    w for w in workers if w.get("type") not in _TOOLORCH_SEARCH_TYPES
                ] or workers
                worker = max(
                    non_search,
                    key=lambda w: PRICES.get(w.get("model", ""), (0.0, 0.0))[1],
                )
                if swe_mode and shared_workdir is not None:
                    (ans, w_in, w_out, is_local, extra_cost, _, bash_turns) = (
                        _swe_call_worker(
                            worker,
                            question,
                            cfg,
                            task_meta,
                            shared_workdir,
                            max_turns + 1,
                        )
                    )
                    tool_calls += bash_turns
                else:
                    ans, w_in, w_out, is_local, extra_cost, _ = _call_worker(
                        worker, question, cfg
                    )
                if is_local:
                    tokens_local += w_in + w_out
                else:
                    tokens_cloud += w_in + w_out
                    cost += self.cost_usd(worker["model"], w_in, w_out) + extra_cost
                history.append(
                    {
                        "role": "worker",
                        "turn": max_turns + 1,
                        "worker_id": worker["id"],
                        "worker_name": worker["name"],
                        "worker_model": worker["model"],
                        "output": ans,
                        "tokens_in": w_in,
                        "tokens_out": w_out,
                        "fallback": True,
                    }
                )
                final_answer = ans

            # In SWE mode, the authoritative output is the working-tree diff —
            # frame it (the runner extracts it via the scorer's ```diff fence).
            if swe_mode and shared_workdir is not None:
                patch = _extract_diff(shared_workdir)
                if patch.strip():
                    final_answer = (
                        f"{final_answer}\n\n```diff\n{patch}```"
                        if final_answer
                        else f"```diff\n{patch}```"
                    )

            meta = {
                "tokens_local": tokens_local,
                "tokens_cloud": tokens_cloud,
                "cost_usd": cost,
                "turns": len([h for h in history if h["role"] == "orchestrator"]),
                "web_search_uses": n_web_searches_total,
                "tool_calls": int(tool_calls),
                "traces": {
                    "history": history,
                    "forced_final": forced_final,
                    "parse_failures": parse_failures,
                    "workers": workers,
                    "n_web_searches": n_web_searches_total,
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

    # ------------------------------------------------------------------
    # Paper-faithful Orchestrator-8B path.
    # ------------------------------------------------------------------
    def _run_rl(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        cfg = self._cfg
        question = input

        # Orchestrator endpoint / model (where the RL'd 8B lives).
        orch_endpoint = str(
            cfg.get("orchestrator_endpoint", "http://localhost:8003/v1")
        )
        orch_model = str(cfg.get("orchestrator_model", "orchestrator-8b"))
        max_turns = int(cfg.get("max_turns", 8))
        orch_max_tokens = int(cfg.get("orchestrator_max_tokens", 4096))
        orch_temp = float(cfg.get("orchestrator_temperature", 1.0))

        # Paper-match pool toggle (2026-05-19). When set, `_paper_expert_for`
        # replaces `_expert_for` and `enhance_reasoning` is post-processed
        # through a Modal Python sandbox. See module docstring + paper-match
        # doc at `docs/26.5.19/toolorchestra-papermatch.md`.
        paper_mode = str(cfg.get("pool", "")).lower() == "paper"

        # SWE-bench detection: same gate as the prompted path. Requires
        # `method_cfg.swe_use_agent_loop = true` AND the task carries the
        # SWE-bench fields. When active, the `enhance_reasoning` and
        # `answer` workers route through `run_swe_agent_loop` on a shared
        # workdir; search workers stay one-shot. At end, the working-tree
        # diff is appended to final_answer so `_score_swebench` can extract
        # it via the ```diff fence.
        task_meta = (context.metadata.get("task") if context is not None else {}) or {}
        swe_mode = (
            bool(cfg.get("swe_use_agent_loop"))
            and bool(task_meta.get("problem_statement"))
            and bool(task_meta.get("repo"))
            and bool(task_meta.get("base_commit"))
        )
        shared_workdir: Optional[Path] = None
        if swe_mode:
            shared_workdir = Path(
                tempfile.mkdtemp(
                    prefix=f"toolorch-rl-swe-{task_meta.get('task_id', 'x')}-"
                )
            )
            try:
                _clone_repo(task_meta["repo"], task_meta["base_commit"], shared_workdir)
            except Exception:
                shutil.rmtree(shared_workdir, ignore_errors=True)
                raise
            self.record_trace_event(
                {
                    "kind": "toolorchestra_rl_swe_workdir",
                    "workdir": str(shared_workdir),
                    "repo": task_meta["repo"],
                    "base_commit": task_meta["base_commit"],
                }
            )

        # ``context_str`` mirrors the upstream's running context — accumulates
        # search documents and code/exec snippets across turns. We keep this
        # as a single string for prompt simplicity; the upstream uses
        # tokenized cutoffs (we cap at ~24k chars instead).
        context_str = ""
        doc_list: List[str] = []
        history: List[Dict[str, Any]] = []
        tokens_local = 0
        tokens_cloud = 0
        cost = 0.0
        n_web_searches_total = 0
        tool_calls = 0
        final_answer: Optional[str] = None
        parse_failures = 0

        # Single outer try/finally guards `shared_workdir` against any
        # exception in the orchestrator loop, the post-loop fallback, or
        # the diff-extraction step. Matches the prompted path's pattern.
        try:
            for turn in range(1, max_turns + 1):
                user = (
                    f"Problem: {question}\n\n{context_str}\n\n"
                    "Choose an appropriate tool."
                )

                # Orchestrator-8B served on local vLLM. We pass the three NVlabs
                # tools verbatim. In paper-mode we use the local helper so we
                # get the SDK-level ``tool_calls`` object back — `_call_vllm`
                # returns just text and loses the call when vLLM's parser
                # caught it. Orchestrator-8B emits its routing decision in the
                # OpenAI-native ``tool_calls`` array with an empty text body,
                # so the legacy `_call_vllm` path saw nothing and silently fell
                # through to the answer-1 fallback (parse_failures: 2 on every
                # non-opus-gaia cell — see docs/reports/toolorchestra.md). Both
                # modes now use `_call_orchestrator_with_tool_calls` so the
                # parser can read structured tool calls; the text-tag path in
                # `_parse_rl_tool_call` is still the fallback when `tool_calls`
                # is empty.
                text, o_in, o_out, sdk_tool_calls = _call_orchestrator_with_tool_calls(
                    orch_model,
                    orch_endpoint,
                    user=user,
                    system=RL_ORCHESTRATOR_SYS,
                    max_tokens=orch_max_tokens,
                    temperature=orch_temp,
                    tools=RL_TOOLS_SPEC,
                )
                self.record_trace_event(
                    {
                        "kind": "vllm",
                        "role": "orchestrator",
                        "model": orch_model,
                        "endpoint": orch_endpoint,
                        "system": RL_ORCHESTRATOR_SYS,
                        "user": user,
                        "response": text,
                        "tool_calls": [
                            {
                                "id": getattr(tc, "id", None),
                                "type": getattr(tc, "type", None),
                                "function": {
                                    "name": getattr(
                                        getattr(tc, "function", None), "name", None
                                    ),
                                    "arguments": getattr(
                                        getattr(tc, "function", None), "arguments", None
                                    ),
                                },
                            }
                            for tc in (sdk_tool_calls or [])
                        ],
                        "tokens_in": o_in,
                        "tokens_out": o_out,
                    }
                )
                tokens_local += o_in + o_out

                action = _parse_rl_tool_call(text, sdk_tool_calls)
                history.append(
                    {
                        "role": "orchestrator",
                        "turn": turn,
                        "raw": text,
                        "action": action,
                    }
                )
                self.record_trace_event(
                    {
                        "kind": "toolorchestra_rl_action",
                        "turn": turn,
                        "action": action,
                        "raw": text,
                    }
                )

                if action is None:
                    parse_failures += 1
                    if parse_failures >= 2:
                        break
                    continue

                name = action["name"]
                args = action.get("arguments", {})
                slot = args.get("model", "")

                # Validate against the upstream tool/arg schema.
                valid = (
                    name in RL_ALL_TOOLS
                    and isinstance(slot, str)
                    and (slot in RL_ALL_TOOLS[name]["model"])
                )
                if not valid:
                    parse_failures += 1
                    if parse_failures >= 2:
                        break
                    # Replay with a softer nudge in the context.
                    context_str += (
                        f"\n[Orchestrator emitted invalid tool call "
                        f"name={name!r} slot={slot!r} — try again.]\n"
                    )
                    continue

                # Paper-match (`method_cfg.pool == "paper"`) routes through
                # the Tavily/OpenRouter/Modal pool instead of the default
                # Anthropic-web-search-driven mapping. For `search` this
                # also forces the worker prompt to a raw query string
                # (Tavily takes a single search string, not a chat-style
                # framing).
                if paper_mode:
                    worker = _paper_expert_for(
                        slot,
                        self._local_model,
                        self._local_endpoint,
                        self._cloud_model,
                        self._cloud_endpoint,
                    )
                    # In paper mode, `enhance_reasoning` is always the coder
                    # specialist regardless of the orchestrator's chosen tier.
                    # The coder is then expected to emit a python block which
                    # we exec in Modal (below).
                    if name == "enhance_reasoning":
                        worker = {
                            "name": f"coder:{slot}",
                            "type": "openrouter",
                            "model": _PAPER_CODER_OPENROUTER,
                        }
                else:
                    worker = _expert_for(
                        slot,
                        self._local_model,
                        self._local_endpoint,
                        self._cloud_model,
                        self._cloud_endpoint,
                    )

                # Dispatch — the orchestrator only conveys a tool/model
                # choice, NOT a question rewrite; the prompt we send the
                # expert is the same context the orchestrator saw, framed
                # appropriately for the tool.
                if name == "search":
                    if paper_mode:
                        # Tavily takes a query string. Orchestrator-8B often
                        # emits an extra `query` arg (not in the upstream
                        # schema but useful) — prefer it; else fall back to
                        # the raw question.
                        q = args.get("query")
                        w_input = q if isinstance(q, str) and q.strip() else question
                    else:
                        w_input = (
                            f"Search the web to gather information that helps answer:\n"
                            f"{question}\n\nCurrent context:\n{context_str or '(empty)'}"
                        )
                elif name == "enhance_reasoning":
                    if paper_mode:
                        w_input = (
                            f"Problem: {question}\n\nContext:\n{context_str or '(empty)'}\n\n"
                            "Write a short Python script that computes intermediate "
                            "results which help answer the problem. Output ONLY the "
                            "code inside one ```python ... ``` fenced block. Print "
                            "any results you derive using `print(...)`. The script "
                            "must run with the Python stdlib only — no extra pip "
                            "installs."
                        )
                    else:
                        w_input = (
                            f"Problem: {question}\n\nContext:\n{context_str or '(empty)'}\n\n"
                            "Reason carefully. Outline the key intermediate steps and any "
                            "computations or facts you can derive. Do NOT give a final "
                            "answer — the orchestrator will collect your reasoning and "
                            "call the answer tool next."
                        )
                else:  # name == "answer"
                    w_input = (
                        f"Problem: {question}\n\nContext:\n{context_str or '(empty)'}\n\n"
                        "Provide the final answer to the user. Respect any "
                        "answer-format rules in the question (e.g. GAIA's "
                        "FINAL ANSWER: <value> convention)."
                    )

                # SWE mode: route enhance_reasoning / answer workers through
                # the SWE agent loop on the shared workdir so they can read
                # files, run tests, and edit the working tree. Search workers
                # stay one-shot (no agent loop). The `_swe_call_worker`
                # one-shot fallbacks (openai-typed workers, search) return
                # bash_turns=0; vllm/anthropic-typed workers run the loop.
                bash_turns = 0
                if swe_mode and shared_workdir is not None and name != "search":
                    (
                        w_text,
                        w_in,
                        w_out,
                        is_local,
                        extra_cost,
                        n_searches,
                        bash_turns,
                    ) = _swe_call_worker(
                        worker,
                        w_input,
                        cfg,
                        task_meta,
                        shared_workdir,
                        turn,
                    )
                else:
                    w_text, w_in, w_out, is_local, extra_cost, n_searches = (
                        _call_worker(worker, w_input, cfg)
                    )
                if is_local:
                    tokens_local += w_in + w_out
                else:
                    tokens_cloud += w_in + w_out
                    cost += self.cost_usd(worker["model"], w_in, w_out) + extra_cost
                n_web_searches_total += n_searches
                # SWE bash turns count as tool calls (each one is a $BASH block
                # the agent executed). On non-SWE turns fall back to the
                # original "at least one expert call" accounting.
                tool_calls += bash_turns if bash_turns > 0 else max(1, n_searches)

                # Paper-match: pipe coder output through a Modal sandbox so
                # `enhance_reasoning` actually executes the code the coder
                # wrote. Append the exec output to the worker's text. No-op
                # when no python block is found.
                modal_exec_output: Optional[str] = None
                modal_exec_rc: Optional[int] = None
                if paper_mode and name == "enhance_reasoning" and not swe_mode:
                    code = _extract_first_python_block(w_text)
                    if code:
                        timeout_s = int(cfg.get("modal_python_timeout_s", 60))
                        modal_exec_output, modal_exec_rc = _call_modal_python(
                            code,
                            timeout_s=timeout_s,
                        )
                        tool_calls += 1
                        w_text = (
                            f"{w_text}\n\n[modal-python stdout/stderr "
                            f"(rc={modal_exec_rc})]\n{modal_exec_output}"
                        )

                history.append(
                    {
                        "role": "worker",
                        "turn": turn,
                        "tool": name,
                        "slot": slot,
                        "worker_model": worker["model"],
                        "worker_type": worker["type"],
                        "output": w_text,
                        "tokens_in": w_in,
                        "tokens_out": w_out,
                        "n_web_searches": n_searches,
                        "bash_turns": bash_turns,
                        "modal_exec_rc": modal_exec_rc,
                    }
                )

                # Update accumulated context for the next turn.
                if name == "search":
                    # Treat the search worker's response as a document.
                    doc_list.append(w_text)
                    ctx_docs = "\n\n".join(
                        f"Doc {i + 1}: {d}" for i, d in enumerate(doc_list)
                    )
                    # Crude char-level cap mirrors the upstream's ~24k token cap.
                    context_str = ("Documents:\n" + ctx_docs)[-24000:]
                elif name == "enhance_reasoning":
                    snippet = f"\n\nReasoning/exec output:\n{w_text}"
                    context_str = (context_str + snippet)[-24000:]
                else:  # answer
                    final_answer = w_text.strip()
                    break

            if final_answer is None:
                # Hard fallback: ask the frontier worker directly. In SWE
                # mode route this final call through the agent loop too so
                # it can still touch the workdir and emit a diff.
                expert_fn = _paper_expert_for if paper_mode else _expert_for
                worker = expert_fn(
                    "answer-1",
                    self._local_model,
                    self._local_endpoint,
                    self._cloud_model,
                    self._cloud_endpoint,
                )
                fb_bash_turns = 0
                if swe_mode and shared_workdir is not None:
                    (ans, w_in, w_out, is_local, extra_cost, _, fb_bash_turns) = (
                        _swe_call_worker(
                            worker,
                            question,
                            cfg,
                            task_meta,
                            shared_workdir,
                            max_turns + 1,
                        )
                    )
                    tool_calls += fb_bash_turns
                else:
                    ans, w_in, w_out, is_local, extra_cost, _ = _call_worker(
                        worker, question, cfg
                    )
                if is_local:
                    tokens_local += w_in + w_out
                else:
                    tokens_cloud += w_in + w_out
                    cost += self.cost_usd(worker["model"], w_in, w_out) + extra_cost
                history.append(
                    {
                        "role": "worker",
                        "turn": max_turns + 1,
                        "tool": "answer",
                        "slot": "answer-1",
                        "worker_model": worker["model"],
                        "worker_type": worker["type"],
                        "output": ans,
                        "tokens_in": w_in,
                        "tokens_out": w_out,
                        "bash_turns": fb_bash_turns,
                        "fallback": True,
                    }
                )
                final_answer = ans

            # In SWE mode, the authoritative output is the working-tree diff —
            # frame it so `_score_swebench`'s extract_patch picks it up.
            if swe_mode and shared_workdir is not None:
                patch = _extract_diff(shared_workdir)
                if patch.strip():
                    final_answer = (
                        f"{final_answer}\n\n```diff\n{patch}```"
                        if final_answer
                        else f"```diff\n{patch}```"
                    )

            meta = {
                "tokens_local": tokens_local,
                "tokens_cloud": tokens_cloud,
                "cost_usd": cost,
                "turns": len([h for h in history if h["role"] == "orchestrator"]),
                "web_search_uses": n_web_searches_total,
                "tool_calls": int(tool_calls),
                "traces": {
                    "history": history,
                    "parse_failures": parse_failures,
                    "orchestrator_model": orch_model,
                    "orchestrator_endpoint": orch_endpoint,
                    "mode": "rl",
                    "pool": "paper" if paper_mode else "default",
                    "swe_mode": swe_mode,
                    "note": (
                        "RL-trained nvidia/Orchestrator-8B as orchestrator. "
                        "Expert pool collapses Tavily/FAISS/Qwen-Math/Coder onto "
                        "our hybrid worker types — see toolorchestra.py docstring."
                    ),
                },
            }
            return final_answer, meta
        finally:
            if shared_workdir is not None:
                shutil.rmtree(shared_workdir, ignore_errors=True)


__all__ = ["ToolOrchestraAgent"]
