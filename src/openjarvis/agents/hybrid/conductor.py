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
import os
import re
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import (
    GEMINI_SEARCH_COST_PER_CALL,
    OPENAI_WEB_SEARCH_COST_PER_CALL,
    WEB_SEARCH_COST_PER_CALL,
    LocalCloudAgent,
    build_web_search_tool,
    tavily_search_context,
    web_search_cfg,
)
from openjarvis.agents.hybrid._prices import (
    PRICES,
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
    """Default worker pool — faithful to the Sakana Conductor paper (arXiv 2512.04388).

    The paper composes a heterogeneous 7-worker pool spanning three frontier
    cloud models (Gemini-2.5-Pro, Claude Sonnet-4, GPT-5) and four open-weights
    workers routed via OpenRouter (DeepSeek-R1-Distill-Qwen-32B, Gemma3-27B-it,
    Qwen3-32B with reasoning off, Qwen3-32B with reasoning on). No local vLLM
    worker is in the paper's default — cells that want one should supply it
    explicitly via ``cfg["worker_pool"]``.

    Each provider is gated by an ``OJ_CONDUCTOR_DISABLE_*`` env var so a cell
    that lacks one set of credentials can still run the rest of the pool. If
    every provider is disabled the result is the empty list — the caller's
    "empty worker pool" check will surface it.

    ``local_model`` / ``local_endpoint`` are accepted for signature stability
    (callers still pass them) but no longer consulted here; the local vLLM is
    only included when the user opts in via ``cfg["worker_pool"]``.
    """
    del local_model, local_endpoint  # paper default carries no local worker
    pool: List[Dict[str, Any]] = []
    if not os.environ.get("OJ_CONDUCTOR_DISABLE_GEMINI"):
        pool.append({
            "id": len(pool),
            "name": "gemini-pro",
            "endpoint": "gemini",
            "model": "gemini-2.5-pro",
            "description": (
                "Google Gemini 2.5 Pro. Frontier multimodal reasoner with a "
                "very large context window. Strong at long-document synthesis, "
                "multi-hop factual reasoning, and tasks that benefit from "
                "wide retrieval. Slower and pricier than mid-tier workers."
            ),
        })
    if not os.environ.get("OJ_CONDUCTOR_DISABLE_ANTHROPIC"):
        pool.append({
            "id": len(pool),
            "name": "claude-sonnet-4",
            "endpoint": "anthropic",
            "model": "claude-sonnet-4-6",
            "description": (
                "Anthropic Claude Sonnet 4. Strong general-purpose reasoner "
                "with careful instruction following and reliable formatting. "
                "Good default for code, structured writing, and decisive "
                "steps where accuracy matters more than raw throughput."
            ),
        })
    if not os.environ.get("OJ_CONDUCTOR_DISABLE_OPENAI"):
        pool.append({
            "id": len(pool),
            "name": "gpt-5",
            "endpoint": "openai",
            "model": "gpt-5",
            "description": (
                "OpenAI GPT-5. Frontier-tier broad-knowledge model. Best for "
                "open-domain factual recall, creative generation, and "
                "ambiguous questions where coverage matters. Expensive; use "
                "for steps where breadth of world knowledge is the bottleneck."
            ),
        })
    if not os.environ.get("OJ_CONDUCTOR_DISABLE_OPENROUTER"):
        pool.append({
            "id": len(pool),
            "name": "deepseek-r1-distill-qwen-32b",
            "endpoint": "openrouter",
            "model": "deepseek/deepseek-r1-distill-qwen-32b",
            "description": (
                "DeepSeek R1 distilled into Qwen-32B (open weights via "
                "OpenRouter). Specialized for chain-of-thought math, logic, "
                "and competitive-programming-style problems. Verbose; "
                "produces extensive reasoning traces before the final answer."
            ),
        })
        pool.append({
            "id": len(pool),
            "name": "gemma3-27b-it",
            "endpoint": "openrouter",
            "model": "google/gemma-3-27b-it",
            "description": (
                "Google Gemma 3 27B Instruct (open weights via OpenRouter). "
                "Mid-size instruction-tuned model. Cheap and fast; solid at "
                "concise summarization, extraction, and short-form Q&A on "
                "given context. Weaker than the frontier workers on multi-step "
                "reasoning."
            ),
        })
        pool.append({
            "id": len(pool),
            "name": "qwen3-32b",
            "endpoint": "openrouter",
            "model": "qwen/qwen3-32b",
            "description": (
                "Qwen3-32B in non-thinking mode (open weights via OpenRouter). "
                "Fast general-purpose dialogue and instruction following. "
                "Use when the step is straightforward generation, "
                "summarization, or formatting — does NOT spend tokens on "
                "internal reasoning."
            ),
        })
        pool.append({
            "id": len(pool),
            "name": "qwen3-32b-thinking",
            "endpoint": "openrouter",
            "model": "qwen/qwen3-32b",
            "extra_body": {"reasoning": {"effort": "medium"}},
            "description": (
                "Qwen3-32B with reasoning enabled (open weights via "
                "OpenRouter). Same backbone as 'qwen3-32b' but spends tokens "
                "on an internal chain of thought before answering. Stronger "
                "on math, code, and multi-step logic; slower and consumes "
                "more completion tokens. Prefer this for hard reasoning "
                "steps; prefer the non-thinking variant for plain dialogue."
            ),
        })
    # Reassign ids contiguously in case env-gates skipped some entries.
    for new_id, entry in enumerate(pool):
        entry["id"] = new_id
    return pool


# Endpoints conductor's `_call_worker` actually knows how to dispatch to.
# Web-search is NOT supported here — toolorchestra has the web-search
# dispatcher. OpenRouter is OpenAI-compatible; Gemini is text-only (no
# tool-call parity with Anthropic — see `_base._call_gemini`). Both are
# opt-in via cfg["worker_pool"] (not added to _default_pool).
_CONDUCTOR_VALID_ENDPOINTS = ("vllm", "openai", "anthropic", "openrouter", "gemini")


def _resolve_worker_pool(
    cfg: Dict[str, Any],
    local_model: Optional[str],
    local_endpoint: Optional[str],
    cloud_model: str,
) -> List[Dict[str, Any]]:
    """Return the worker pool for this run.

    Strict replace, not merge: if ``cfg["worker_pool"]`` is set, the
    default pool is ignored entirely. Falls back to ``_default_pool`` when
    the override is absent.

    Each user-supplied entry must be a dict with keys ``id``, ``name``,
    ``endpoint``, and ``model``. ``endpoint`` must be one of
    ``vllm`` / ``openai`` / ``anthropic`` / ``openrouter`` / ``gemini`` —
    conductor does not wire web-search workers. OpenRouter workers route
    through the OpenAI-compatible OpenRouter proxy; Gemini workers call
    the google-genai SDK (text-only, no tool use). Both are opt-in via
    ``cfg["worker_pool"]`` (not in the default pool).

    Substitution: ``model = "$local"`` (or ``"<local>"``) resolves to
    ``local_model``; ``model = "$cloud"`` / ``"<cloud>"`` to ``cloud_model``.

    On any validation failure, raises ``ValueError`` with the message
    ``"Invalid worker_pool entry [<id>]: <reason>"``. Fails fast at agent
    init rather than mid-task.
    """
    override = cfg.get("worker_pool")
    if override is None:
        return _default_pool(local_model, local_endpoint)
    if not isinstance(override, list) or not override:
        raise ValueError(
            "Invalid worker_pool entry [-]: worker_pool must be a non-empty list"
        )

    resolved: List[Dict[str, Any]] = []
    seen_ids: set = set()
    has_non_search = False
    for raw in override:
        wid_repr = raw.get("id", "?") if isinstance(raw, dict) else "?"
        if not isinstance(raw, dict):
            raise ValueError(
                f"Invalid worker_pool entry [{wid_repr}]: entry must be a dict"
            )
        entry = dict(raw)
        wid = entry.get("id")
        if not isinstance(wid, int):
            raise ValueError(
                f"Invalid worker_pool entry [{wid_repr}]: 'id' must be an int"
            )
        if wid in seen_ids:
            raise ValueError(
                f"Invalid worker_pool entry [{wid}]: duplicate id"
            )
        seen_ids.add(wid)
        if not entry.get("name") or not isinstance(entry["name"], str):
            raise ValueError(
                f"Invalid worker_pool entry [{wid}]: 'name' must be a non-empty string"
            )
        endpoint = entry.get("endpoint") or entry.get("type")
        if not isinstance(endpoint, str) or endpoint.lower() not in _CONDUCTOR_VALID_ENDPOINTS:
            raise ValueError(
                f"Invalid worker_pool entry [{wid}]: 'endpoint' must be one of "
                f"{_CONDUCTOR_VALID_ENDPOINTS} (got {endpoint!r})"
            )
        endpoint = endpoint.lower()
        entry["endpoint"] = endpoint
        # Substitute $local / $cloud placeholders.
        model = entry.get("model")
        if isinstance(model, str) and model in ("$local", "<local>"):
            if not local_model:
                raise ValueError(
                    f"Invalid worker_pool entry [{wid}]: model='{model}' "
                    "requires a local_model to be configured for this cell"
                )
            model = local_model
            entry["model"] = model
        elif isinstance(model, str) and model in ("$cloud", "<cloud>"):
            model = cloud_model
            entry["model"] = model
        if not isinstance(model, str) or not model:
            raise ValueError(
                f"Invalid worker_pool entry [{wid}]: 'model' must be a non-empty string"
            )
        if endpoint == "vllm":
            if not entry.get("base_url"):
                # Default to the local endpoint if not specified — matches
                # how _default_pool wires it.
                if not local_endpoint:
                    raise ValueError(
                        f"Invalid worker_pool entry [{wid}]: vllm worker needs "
                        "'base_url' (or a configured local_endpoint to fall back to)"
                    )
                entry["base_url"] = local_endpoint
            entry.setdefault("api_key", "EMPTY")
            # Local also counts as a non-search worker for the
            # "must have at least one solver" check.
            has_non_search = True
        else:
            # Cloud workers: model must be priced (any unknown model would
            # silently cost $0, which masks billing mistakes downstream).
            # OpenRouter is exempt — its model space is huge and varies
            # per-provider; cost reporting for openrouter workers is 0
            # (same as vllm). Cells that need accurate billing for an
            # openrouter worker should add it to PRICES themselves.
            if endpoint != "openrouter" and model not in PRICES:
                raise ValueError(
                    f"Invalid worker_pool entry [{wid}]: model {model!r} is "
                    f"not in PRICES (known: {sorted(PRICES)})"
                )
            has_non_search = True
        entry.setdefault(
            "description",
            f"User-supplied {endpoint} worker ({model}).",
        )
        resolved.append(entry)

    if not has_non_search:
        raise ValueError(
            "Invalid worker_pool entry [-]: worker_pool must contain at least "
            "one non-search worker (vllm / openai / anthropic / openrouter / gemini)"
        )

    # The planner picks a worker by its `id` (it sees "Model <id> (<name>)"),
    # but execution dispatches via `workers[model_id]` — list *position*. If a
    # config supplies non-contiguous or out-of-order ids those two diverge and
    # a plan that names worker N silently runs a different worker. Enforce
    # contiguous 0..N-1 ids that equal list position so id == index always.
    expected = list(range(len(resolved)))
    actual = [w["id"] for w in resolved]
    if actual != expected:
        raise ValueError(
            f"Invalid worker_pool entry [-]: worker ids must be contiguous "
            f"0..{len(resolved) - 1} in list order so the planner's model_id "
            f"matches the dispatch index (got ids {actual}, expected {expected})"
        )
    return resolved


def _format_worker_pool(workers: List[Dict[str, Any]]) -> str:
    return "\n".join(
        f"Model {w['id']} ({w['name']}): {w['description']}" for w in workers
    )


def _search_capable_indices(
    workers: List[Dict[str, Any]],
    *,
    search_backend: str = "provider",
) -> List[int]:
    """Indices of workers whose endpoint can run server-side web search."""
    if search_backend == "tavily":
        return [w["id"] for w in workers]
    return [
        w["id"] for w in workers
        if (w.get("endpoint") or "openai").lower()
        in _SEARCH_CAPABLE_WORKER_ENDPOINTS
    ]


def _build_conductor_prompt(
    question: str,
    workers: List[Dict[str, Any]],
    *,
    web_search_enabled: bool = False,
    search_backend: str = "provider",
) -> str:
    """Build the planner prompt.

    When ``web_search_enabled`` is set (GAIA cells with web_search on),
    append an explicit routing constraint: only the listed model indices
    can perform web research, so any step that needs to look something up
    on the web MUST be routed to one of them. Steps routed elsewhere
    answer blind from parametric memory.
    """
    base = (
        f"Available models:\n{_format_worker_pool(workers)}\n\n"
        f"User question:\n{question}\n"
    )
    if not web_search_enabled:
        return base
    capable = _search_capable_indices(workers, search_backend=search_backend)
    if capable:
        cap_str = ", ".join(str(i) for i in capable)
        if search_backend == "tavily":
            capability = "External Tavily search results will be prepended to worker prompts"
        else:
            capability = "Only these model indices can perform live web search"
        constraint = (
            "\n\nWEB SEARCH CONSTRAINT:\n"
            f"{capability}: [{cap_str}]. "
            "Any step that needs to look up facts, current events, or other "
            "information not reliably known from memory MUST be routed to one "
            "of those indices. Steps routed to any other model can only use "
            "their parametric memory and will answer such questions blind.\n"
        )
    else:
        # No search-capable worker at all — the run-level guard raises
        # before we get here, but keep the prompt honest just in case.
        constraint = (
            "\n\nWEB SEARCH CONSTRAINT:\n"
            "No model in this pool can perform live web search; rely on the "
            "models' own knowledge.\n"
        )
    return base + constraint


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

# Worker endpoints that can run server-side web search via a `_base`
# agent loop. openrouter / vllm cannot ground.
_SEARCH_CAPABLE_WORKER_ENDPOINTS = ("anthropic", "openai", "gemini")


def _worker_search_cost_per_call(endpoint: str) -> float:
    """Per-search-call USD cost for a worker's cloud endpoint."""
    if endpoint == "openai":
        return OPENAI_WEB_SEARCH_COST_PER_CALL
    if endpoint == "gemini":
        return GEMINI_SEARCH_COST_PER_CALL
    return WEB_SEARCH_COST_PER_CALL


def _call_worker(
    worker: Dict[str, Any],
    prompt: str,
    cfg: Dict[str, Any],
    *,
    web_search_tool: Optional[Dict[str, Any]] = None,
    web_search_max_uses: int = 8,
) -> Tuple[str, int, int, bool, int, float]:
    """Returns (text, p_tok, c_tok, is_local, n_web_searches, extra_cost).

    ``web_search_tool``: a truthy marker that web_search is enabled for
    this run. When set AND the worker endpoint is search-capable
    (anthropic / openai / gemini), the worker call is routed through the
    matching ``_base`` agent loop so the worker can ground its answer.
    ``n_web_searches`` is the actual count the provider ran.
    ``web_search_max_uses`` caps the Anthropic search tool.
    Search-incapable workers (openrouter, vllm) ignore it and return 0.
    """
    ep = (worker.get("endpoint") or "openai").lower()
    max_tok = int(cfg.get("worker_max_tokens", 4096))
    temp = float(cfg.get("worker_temperature", 0.2))
    use_ws = web_search_tool is not None
    search_backend = str(cfg.get("search_backend", "provider")).lower()
    extra_cost = 0.0
    if use_ws and search_backend == "tavily":
        res = tavily_search_context(
            prompt,
            max_results=int(cfg.get("tavily_max_results", 5)),
        )
        prompt = (
            f"Web search results:\n{res['text']}\n\n"
            f"Using the search results above, answer this request:\n{prompt}"
        )
        extra_cost = float(res["cost_usd"])
        use_ws = False
        tavily_searches = int(res["n_searches"])
    else:
        tavily_searches = 0

    if ep == "vllm":
        text, p, c = LocalCloudAgent._call_vllm(
            worker["model"],
            worker["base_url"],
            user=prompt,
            max_tokens=max_tok,
            temperature=temp,
            enable_thinking=False,
        )
        return text, p, c, True, tavily_searches, extra_cost
    if ep == "openai":
        if use_ws:
            text, p, c, n_searches, _ = LocalCloudAgent._call_openai_agent(
                worker["model"],
                user=prompt,
                max_tokens=max_tok,
                temperature=(1.0 if is_gpt5_family(worker["model"]) else temp),
            )
            return text, p, c, False, n_searches, 0.0
        text, p, c = LocalCloudAgent._call_openai(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=(1.0 if is_gpt5_family(worker["model"]) else temp),
        )
        return text, p, c, False, tavily_searches, extra_cost
    if ep == "openrouter":
        # OpenRouter is OpenAI-compatible; the helper handles the
        # base_url + OPENROUTER_API_KEY plumbing. No server-side web
        # search wired here. is_local=False so tokens count as cloud.
        # ``worker["extra_body"]`` (e.g. {"reasoning": {"effort": "medium"}})
        # is forwarded to the SDK so paper-faithful workers like
        # "qwen3-32b-thinking" can toggle reasoning per-call.
        extra_body = worker.get("extra_body")
        text, p, c = LocalCloudAgent._call_openrouter(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=temp,
            extra_body=extra_body if isinstance(extra_body, dict) else None,
        )
        return text, p, c, False, tavily_searches, extra_cost
    if ep == "anthropic":
        eff_temp = temp if supports_temperature(worker["model"]) else 0.0
        anthropic_kwargs: Dict[str, Any] = dict(
            user=prompt,
            max_tokens=max_tok,
            temperature=eff_temp,
        )
        if web_search_tool is not None:
            anthropic_kwargs["tools"] = [web_search_tool]
        text, p, c, n_searches = LocalCloudAgent._call_anthropic(
            worker["model"], **anthropic_kwargs
        )
        return text, p, c, False, n_searches or tavily_searches, extra_cost
    if ep == "gemini":
        # Gemini Developer API via google-genai. With web_search on, route
        # through the Google-Search-grounded agent loop; otherwise plain
        # text generation. is_local=False so tokens count as cloud.
        if use_ws:
            text, p, c, n_searches, _ = LocalCloudAgent._call_gemini_agent(
                worker["model"],
                user=prompt,
                max_tokens=max_tok,
                temperature=temp,
            )
            return text, p, c, False, n_searches, 0.0
        text, p, c = LocalCloudAgent._call_gemini(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=temp,
        )
        return text, p, c, False, tavily_searches, extra_cost
    raise ValueError(f"unsupported worker endpoint: {ep!r}")


def _swe_worker_step(
    worker: Dict[str, Any],
    task: Dict[str, Any],
    prompt: str,
    cfg: Dict[str, Any],
    workdir: Path,
    step_idx: int,
) -> Tuple[str, int, int, bool, int, int]:
    """Run one Conductor worker step as a mini-SWE-agent subloop on a shared
    workdir. Returns (final_summary_or_diff, tokens_in, tokens_out, is_local,
    n_web_searches, bash_turns). SWE workers don't use web_search (the bash
    tool is the only tool they need); ``bash_turns`` counts the agent-loop
    turns so the caller can surface ``tool_calls``."""
    ep = (worker.get("endpoint") or "openai").lower()
    if ep == "vllm":
        backbone, model, endpoint, is_local = (
            "local", worker["model"], worker.get("base_url"), True,
        )
        cloud_endpoint = "anthropic"  # unused on the local path
    elif ep == "anthropic":
        backbone, model, endpoint, is_local = (
            "cloud", worker["model"], None, False,
        )
        cloud_endpoint = "anthropic"
    else:
        # OpenAI workers (gpt-5-mini etc.) aren't supported as agent-loop
        # backbones today (the loop's tool-call format is Anthropic- or
        # OpenAI-via-vllm-shaped only). Fall back to one-shot for those —
        # SWE-bench-wise they were already weak; this preserves behavior.
        text, p, c, is_local, n_searches, _extra = _call_worker(worker, prompt, cfg)
        return text, p, c, is_local, n_searches, 0
    out = run_swe_agent_loop(
        task,
        backbone=backbone,
        backbone_model=model,
        cloud_endpoint=cloud_endpoint,
        local_endpoint=endpoint,
        initial_prompt=prompt,
        max_turns=int(cfg.get("swe_max_turns", 30)),
        bash_timeout=int(cfg.get("swe_bash_timeout_s", 120)),
        output_cap=int(cfg.get("swe_output_cap", 10_000)),
        turn_max_tokens=int(cfg.get("swe_turn_max_tokens", 4096)),
        trace_prefix=f"conductor_step{step_idx}",
        workdir=workdir,
    )
    return (
        out["final_summary"] or out["answer"],
        out["tokens_in"], out["tokens_out"], is_local, 0, int(out["turns"]),
    )


@AgentRegistry.register("conductor")
class ConductorAgent(LocalCloudAgent):
    """Plan-then-execute static DAG over a worker pool. See module docstring."""

    agent_id = "conductor"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Validate `method_cfg.worker_pool` early — surfaces config errors
        # at agent construction rather than on the first task. No-op when
        # the override is absent (default pool is built later, lazily,
        # because `_vllm_alive` needs a live network probe).
        if self._cfg.get("worker_pool") is not None:
            _resolve_worker_pool(
                self._cfg,
                self._local_model,
                self._local_endpoint,
                self._cloud_model,
            )

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        question = input
        cfg = self._cfg
        # Resolution order (strict replace, no merge):
        #   1. `cfg["workers"]` — legacy direct override, used by tests.
        #   2. `cfg["worker_pool"]` — cell-config override; validated +
        #      $local/$cloud substituted.
        #   3. `_default_pool(...)` — heterogeneous default (Opus +
        #      gpt-5-mini + optional local Qwen).
        if cfg.get("workers"):
            workers = cfg["workers"]
        else:
            workers = _resolve_worker_pool(
                cfg,
                self._local_model,
                self._local_endpoint,
                self._cloud_model,
            )
        if not workers:
            raise RuntimeError("conductor: empty worker pool")

        # Determine swe_mode up front — needed so the planner prompt can
        # carry the GAIA web-search routing constraint (Task 3). SWE tasks
        # use the bash tool, not web_search, so the constraint is GAIA-only.
        task_meta_early = (
            context.metadata.get("task") if context is not None else {}
        ) or {}
        swe_mode_early = (
            bool(cfg.get("swe_use_agent_loop"))
            and bool(task_meta_early.get("problem_statement"))
            and bool(task_meta_early.get("repo"))
            and bool(task_meta_early.get("base_commit"))
        )
        ws_enabled, ws_max_uses = web_search_cfg(cfg)
        search_backend = str(cfg.get("search_backend", "provider")).lower()
        planner_ws = ws_enabled and not swe_mode_early

        # 1. Plan — when web_search is on (GAIA), the prompt names which
        # worker indices can actually search, so the planner routes
        # research steps to a search-capable worker.
        user = _build_conductor_prompt(
            question,
            workers,
            web_search_enabled=planner_ws,
            search_backend=search_backend,
        )
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
        # ``task_meta`` / ``swe_mode`` were computed up front (see Task-3
        # planner constraint above) — reuse them.
        task_meta = task_meta_early
        swe_mode = swe_mode_early
        steps: List[Dict[str, Any]] = []
        tokens_local = 0
        tokens_cloud = 0
        cost = 0.0
        final_answer = ""
        shared_workdir: Optional[Path] = None
        n_web_searches_total = 0
        # tool_calls aggregator: bash turns on SWE (per worker subloop) +
        # web_search uses on GAIA. Conductor planner is text-only.
        tool_calls = 0

        # Web_search opt-in: when enabled, search-capable workers
        # (anthropic / openai / gemini) route through their `_base` agent
        # loop in `_call_worker` and ground their answers. GAIA-only — SWE
        # workers use bash not web_search. openrouter / vllm workers can't
        # ground and ignore the flag. If the worker pool has NO
        # search-capable worker, web_search can never run on any step —
        # every step would answer the GAIA question blind from parametric
        # memory. Fail loud instead of degrading silently.
        # ``ws_enabled`` / ``ws_max_uses`` computed up front for the planner
        # constraint — reuse them here.
        if ws_enabled and search_backend != "tavily" and not swe_mode:
            search_workers = [
                w for w in workers
                if (w.get("endpoint") or "openai").lower()
                in _SEARCH_CAPABLE_WORKER_ENDPOINTS
            ]
            if not search_workers:
                endpoints = sorted({
                    (w.get("endpoint") or "openai").lower() for w in workers
                })
                raise ValueError(
                    f"web_search.enabled=true but the worker pool has no "
                    f"search-capable worker (endpoints present: {endpoints}); "
                    "server-side web_search is wired only for anthropic / "
                    "openai / gemini workers in conductor's _call_worker. "
                    "Add one of those to the pool or disable web_search — "
                    "otherwise every step answers blind from parametric memory."
                )
        # ``ws_tool`` doubles as the enable marker passed to `_call_worker`
        # (truthy => route search-capable workers through their agent loop).
        ws_tool = (
            build_web_search_tool(ws_max_uses) if ws_enabled else None
        )

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

                worker_ep = (worker.get("endpoint") or "openai").lower()
                # Post-hoc routing check: if web_search is on but the
                # planner routed this step to a search-incapable worker,
                # record a warning into the trace (don't crash — the step
                # may legitimately not need search; see Task-3 planner
                # constraint that tries to prevent this upfront).
                if (
                    ws_enabled and search_backend != "tavily" and not swe_mode
                    and worker_ep not in _SEARCH_CAPABLE_WORKER_ENDPOINTS
                ):
                    self.record_trace_event({
                        "kind": "conductor_search_routing_warning",
                        "step_idx": i,
                        "worker_id": mid,
                        "worker_name": worker["name"],
                        "worker_endpoint": worker_ep,
                        "warning": (
                            f"web_search enabled but step {i} routed to "
                            f"search-incapable worker {worker['name']!r} "
                            f"(endpoint {worker_ep!r}); this step cannot "
                            "ground and may answer blind."
                        ),
                    })

                extra_cost = 0.0
                if swe_mode:
                    text, w_in, w_out, is_local, n_searches, bash_turns = (
                        _swe_worker_step(
                            worker, task_meta, prompt, cfg, shared_workdir, i,
                        )
                    )
                    tool_calls += bash_turns
                else:
                    (
                        text, w_in, w_out, is_local, n_searches, extra_cost
                    ) = _call_worker(
                        worker, prompt, cfg,
                        web_search_tool=ws_tool,
                        web_search_max_uses=ws_max_uses,
                    )

                if is_local:
                    tokens_local += w_in + w_out
                else:
                    tokens_cloud += w_in + w_out
                    cost += self.cost_usd(worker["model"], w_in, w_out)
                    if search_backend != "tavily":
                        cost += n_searches * _worker_search_cost_per_call(worker_ep)
                if search_backend == "tavily":
                    cost += extra_cost
                n_web_searches_total += n_searches
                tool_calls += n_searches
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
            "web_search_uses": n_web_searches_total,
            "tool_calls": int(tool_calls),
            "traces": {
                "steps": traces,
                "plan": plan,
                "fallback_used": fallback_used,
                "web_search_enabled": ws_enabled,
                "search_backend": search_backend,
                "n_web_searches": n_web_searches_total,
                "parse_attempts": parse_attempts,
                "workers": [
                    {k: v for k, v in w.items() if k != "api_key"}
                    for w in workers
                ],
            },
        }
        return final_answer, meta


__all__ = ["ConductorAgent"]
