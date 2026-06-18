"""The SkillOrchestra eval-orchestrator loop.

Faithful port of ``orchestration/eval_frames.py:run_single`` — the
multi-round search -> reasoning -> answer ReAct loop. Each round:

1. Build a context string from accumulated docs / code results / attempts.
2. Ask the orchestrator model (with the 3 tools) for the next stage. The
   prompt is the verbatim ``build_skill_orchestrator_prompt`` when a
   handbook is loaded, else the baseline ``"Problem: ... Choose an
   appropriate tool."`` string.
3. Parse the tool call + any ``<skill_analysis>`` block; route the worker
   model alias through the configured ``RoutingStrategy``.
4. Execute the tool. ``answer`` ends the loop; the last round force-calls
   ``answer``.

The orchestrator step does raw SDK calls (Anthropic / OpenAI) because it
needs the parsed ``tool_use`` blocks back — the same thing
``extract_response_content_and_tool_calls`` does in the original.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from .._prices import is_gpt5_family, supports_temperature
from .pool import ModelSpec, build_pool
from .prompts import build_skill_orchestrator_prompt
from .stage_router import (
    StageSkillHandbook,
    get_routing_strategy,
    parse_skill_analysis,
)
from .tools import (
    anthropic_tools,
    gemini_tools,
    openai_tools,
    run_answer,
    run_code,
    run_search,
)

# tool name -> routing stage (stage_router uses "reasoning" for code).
_TOOL_STAGE = {
    "search": "search",
    "enhance_reasoning": "reasoning",
    "code": "reasoning",
    "answer": "answer",
}
_STAGE_DEFAULT_ALIAS = {
    "search": "search-1",
    "reasoning": "reasoner-1",
    "answer": "answer-1",
}


# ---------------------------------------------------------------------------
# Orchestrator decision step (raw SDK — needs tool_use blocks back)
# ---------------------------------------------------------------------------

def _orchestrate_step(
    agent: Any,
    *,
    user: str,
    model: str,
    endpoint: str,
    max_tokens: int,
) -> Tuple[str, List[Dict[str, Any]], int, int, float]:
    """One orchestrator turn. Returns (text, tool_calls, p_tok, c_tok, cost).

    ``tool_calls`` is a list of ``{"name", "input"}`` dicts.
    """
    endpoint = endpoint.lower()
    if endpoint == "anthropic":
        import anthropic

        client = anthropic.Anthropic(timeout=600.0, max_retries=12)
        kwargs: Dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": user}],
            tools=anthropic_tools(),
        )
        if supports_temperature(model):
            kwargs["temperature"] = 1.0
        msg = client.messages.create(**kwargs)
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        tool_calls = [
            {"name": b.name, "input": dict(b.input or {})}
            for b in msg.content
            if getattr(b, "type", "") == "tool_use"
        ]
        p = getattr(msg.usage, "input_tokens", 0)
        c = getattr(msg.usage, "output_tokens", 0)

    elif endpoint == "openai":
        from openai import OpenAI

        client = OpenAI(timeout=600.0)
        kwargs = dict(
            model=model,
            messages=[{"role": "user", "content": user}],
            tools=openai_tools(),
            tool_choice="auto",
        )
        if is_gpt5_family(model):
            kwargs["max_completion_tokens"] = max_tokens
            kwargs["temperature"] = 1.0
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = 1.0
        resp = client.chat.completions.create(**kwargs)
        choice = resp.choices[0].message
        text = choice.content or ""
        tool_calls = []
        for tc in getattr(choice, "tool_calls", None) or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append({"name": tc.function.name, "input": args})
        u = resp.usage
        p = getattr(u, "prompt_tokens", 0) if u else 0
        c = getattr(u, "completion_tokens", 0) if u else 0
    elif endpoint == "gemini":
        from google import genai
        from google.genai import types

        client = genai.Client(
            http_options=types.HttpOptions(timeout=600_000)
        )
        cfg = types.GenerateContentConfig(
            temperature=1.0,
            max_output_tokens=max_tokens,
            tools=[types.Tool(function_declarations=gemini_tools())],
        )
        resp = client.models.generate_content(
            model=model,
            contents=user,
            config=cfg,
        )
        text = (resp.text or "") if hasattr(resp, "text") else ""
        tool_calls = []
        try:
            parts = resp.candidates[0].content.parts or []
        except Exception:  # noqa: BLE001
            parts = []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc is None:
                continue
            name = getattr(fc, "name", None)
            if not isinstance(name, str) or not name:
                continue
            args = getattr(fc, "args", None) or {}
            try:
                args = dict(args)
            except Exception:  # noqa: BLE001
                args = {}
            tool_calls.append({"name": name, "input": args})
        um = getattr(resp, "usage_metadata", None)
        p = int(getattr(um, "prompt_token_count", 0) or 0) if um else 0
        c = int(getattr(um, "candidates_token_count", 0) or 0) if um else 0
    else:
        raise ValueError(
            f"orchestrator endpoint {endpoint!r} unsupported — route the "
            "orchestrator through anthropic/openai/gemini (set method_cfg."
            "orchestrator_endpoint)."
        )

    cost = agent.cost_usd(model, p, c)
    agent.record_trace_event({
        "kind": "skillorchestra_orchestrate",
        "model": model,
        "endpoint": endpoint,
        "prompt": user,
        "response": text,
        "tool_calls": tool_calls,
        "tokens_in": p,
        "tokens_out": c,
    })
    return text, tool_calls, p, c, cost


# ---------------------------------------------------------------------------
# Context assembly  —  eval_frames.py:1305-1351
# ---------------------------------------------------------------------------

def _build_context(
    doc_list: List[Tuple[str, str]],
    code_list: List[Tuple[str, str]],
    attempt_list: List[Tuple[str, str]],
    *,
    char_cap: int,
) -> str:
    parts: List[str] = []
    if doc_list:
        blk = ["## Retrieved Information"]
        for i, (query, txt) in enumerate(doc_list):
            blk.append(f"### Search {i + 1} — query: {query}\n{txt}")
        parts.append("\n\n".join(blk))
    if code_list:
        blk = ["## Code Execution Results"]
        for i, (code, out) in enumerate(code_list):
            blk.append(
                f"### Code {i + 1}\n```python\n{code}\n```\n"
                f"Output:\n{out if out else '(no output)'}"
            )
        parts.append("\n\n".join(blk))
    if attempt_list:
        blk = ["## Previous Answer Attempts"]
        for who, ans in attempt_list:
            blk.append(f"- {who}: {ans}")
        parts.append("\n".join(blk))
    ctx = "\n\n".join(parts)
    if len(ctx) > char_cap:
        # Keep the tail — most recent docs/code/attempts matter most.
        ctx = "...[earlier context truncated]...\n" + ctx[-char_cap:]
    return ctx


# ---------------------------------------------------------------------------
# Main loop  —  eval_frames.py:run_single
# ---------------------------------------------------------------------------

def run_orchestrator(
    agent: Any,
    problem: str,
    *,
    cfg: Dict[str, Any],
    handbook: Optional[StageSkillHandbook],
    strategy: str,
) -> Tuple[str, Dict[str, Any]]:
    """Run the eval orchestrator on one problem. Returns (answer, metadata)."""
    max_rounds = int(cfg.get("max_rounds", 6))
    char_cap = int(cfg.get("context_char_cap", 24000))
    retriever_url = cfg.get("retriever_url")
    code_timeout = int(cfg.get("code_timeout_s", 60))
    answer_max_tokens = int(cfg.get("answer_max_tokens", 40000))
    ws_max_uses = int(cfg.get("web_search_max_uses", 5))
    search_backend = str(cfg.get("search_backend", "provider")).lower()
    tavily_max_results = int(cfg.get("tavily_max_results", 5))

    # The orchestrator model: a fixed model per run (the original's
    # MODEL_NAME). Defaults to the cell's cloud model when that endpoint
    # supports tool calls, else Opus. ``router_model`` / ``router_endpoint``
    # are accepted as back-compat aliases (pre-restructure cfg key names).
    orch_endpoint = (cfg.get("orchestrator_endpoint")
                     or cfg.get("router_endpoint")
                     or agent._cloud_endpoint).lower()
    orch_model = (cfg.get("orchestrator_model")
                  or cfg.get("router_model")
                  or agent._cloud_model)
    if orch_endpoint not in ("anthropic", "openai", "gemini"):
        orch_endpoint, orch_model = "anthropic", "claude-opus-4-7"
    orch_max_tokens = int(cfg.get("orchestrator_max_tokens", 4096))

    pool = build_pool(
        local_model=agent._local_model,
        local_endpoint=agent._local_endpoint,
        cloud_model=agent._cloud_model,
        cloud_endpoint=agent._cloud_endpoint,
        overrides=cfg.get("model_pool"),
    )

    doc_list: List[Tuple[str, str]] = []
    code_list: List[Tuple[str, str]] = []
    attempt_list: List[Tuple[str, str]] = []
    route_log: List[Dict[str, Any]] = []

    tokens_local = 0
    tokens_cloud = 0
    cost_usd = 0.0
    tool_calls_n = 0
    web_uses = 0
    final_pred = ""
    used_rounds = 0

    def _route(stage: str, tool_alias: Optional[str], orch_text: str) -> str:
        """Resolve the worker alias for ``stage`` via the routing strategy."""
        if handbook is not None and strategy != "none":
            sa = parse_skill_analysis(orch_text)
            rr = get_routing_strategy(strategy, handbook).select_model(
                stage, sa, tool_call_model=tool_alias,
            )
            return rr.model_alias
        return tool_alias or _STAGE_DEFAULT_ALIAS[stage]

    for step in range(max_rounds):
        used_rounds = step + 1
        is_last = step == max_rounds - 1
        context_str = _build_context(
            doc_list, code_list, attempt_list, char_cap=char_cap,
        )

        if handbook is not None and strategy != "none":
            user = build_skill_orchestrator_prompt(
                problem=problem,
                context_str=context_str,
                strategy=strategy,
                handbook=handbook,
            )
        else:
            user = (
                f"Problem: {problem}\n\n{context_str}\n\n"
                "Choose an appropriate tool."
            )

        text, tcalls, p, c, ocost = _orchestrate_step(
            agent, user=user, model=orch_model,
            endpoint=orch_endpoint, max_tokens=orch_max_tokens,
        )
        tokens_cloud += p + c
        cost_usd += ocost

        # The orchestrator may answer directly in <answer> tags.
        if not tcalls and "<answer>" in text and "</answer>" in text:
            final_pred = text.split("<answer>")[-1].split("</answer>")[0].strip()
            break

        # Last round: force the answer tool (eval_frames.py:1373-1380).
        if is_last:
            ans_alias = None
            for tc in tcalls:
                if tc["name"] == "answer":
                    ans_alias = (tc.get("input") or {}).get("model")
            tcalls = [{"name": "answer", "input": {"model": ans_alias or "answer-1"}}]
        elif not tcalls:
            # No tool, no answer — record the text and continue.
            if text.strip():
                attempt_list.append(("orchestrator", text.strip()[:2000]))
            continue

        finish = False
        for tc in tcalls:
            tool = tc["name"]
            tool_alias = (tc.get("input") or {}).get("model")
            stage = _TOOL_STAGE.get(tool, "answer")
            chosen_alias = _route(stage, tool_alias, text)
            spec: ModelSpec = pool.get(chosen_alias) or pool[
                _STAGE_DEFAULT_ALIAS[stage]
            ]
            route_log.append({
                "step": step,
                "tool": tool,
                "orchestrator_alias": tool_alias,
                "routed_alias": chosen_alias,
                "routed_model": spec.model,
                "is_local": spec.is_local,
            })
            tool_calls_n += 1

            if tool == "search":
                res = run_search(
                    agent, spec, context_str=context_str, problem=problem,
                    retriever_url=retriever_url, web_search_max_uses=ws_max_uses,
                    search_backend=search_backend,
                    tavily_max_results=tavily_max_results,
                )
                docs = res["search_results_data"]
                joined = "\n---\n".join(d for d in docs if d)[:char_cap]
                doc_list.append((res["query"], joined or "(no results)"))
                web_uses += res.get("web_search_uses", 0)
            elif tool in ("enhance_reasoning", "code"):
                res = run_code(
                    agent, spec, context_str=context_str, problem=problem,
                    bash_timeout_s=code_timeout,
                )
                code_list.append((res["generated_code"], res["exec_result"]))
            else:  # answer
                res = run_answer(
                    agent, spec, context_str=context_str, problem=problem,
                    max_tokens=answer_max_tokens,
                )
                final_pred = res["pred"]
                attempt_list.append((res["alias"], final_pred))
                finish = True

            if res["is_local"]:
                tokens_local += res["tokens_in"] + res["tokens_out"]
            else:
                tokens_cloud += res["tokens_in"] + res["tokens_out"]
            cost_usd += res["cost_usd"]

        if finish:
            break

    agent.record_trace_event({
        "kind": "skillorchestra_route_log",
        "strategy": strategy,
        "rounds_used": used_rounds,
        "routes": route_log,
    })

    meta = {
        "tokens_local": tokens_local,
        "tokens_cloud": tokens_cloud,
        "cost_usd": cost_usd,
        "turns": used_rounds,
        "tool_calls": tool_calls_n,
        "web_search_uses": web_uses,
        "traces": {
            "strategy": strategy,
            "handbook_loaded": handbook is not None,
            "rounds_used": used_rounds,
            "routes": route_log,
        },
    }
    return final_pred, meta
