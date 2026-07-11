"""Worker pool resolution + dispatch for ToolOrchestraAgent."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents.hybrid._base import (
    ANTHROPIC_WEB_SEARCH_TOOL,
    GEMINI_SEARCH_COST_PER_CALL,
    OPENAI_WEB_SEARCH_COST_PER_CALL,
    WEB_SEARCH_COST_PER_CALL,
    LocalCloudAgent,
)
from openjarvis.agents.hybrid._prices import (
    PRICES,
    is_gpt5_family,
    supports_temperature,
)
from openjarvis.agents.hybrid.mini_swe_agent import run_swe_agent_loop
from openjarvis.agents.hybrid.toolorchestra.experts import (
    _PAPER_CODER_OPENROUTER,
    _PAPER_GENERALIST_TIER3_OPENROUTER,
)
from openjarvis.agents.hybrid.toolorchestra.sandbox import (
    _call_modal_python,
    _call_tavily_search,
)


def _paper_pool(
    local_model: Optional[str],
    local_endpoint: Optional[str],
) -> List[Dict[str, Any]]:
    """Paper-match worker pool (registered for traces / inspection).

    NOTE: in RL mode the orchestrator dispatches via tool/slot rather than
    worker_id, so this list is purely informational — `_paper_expert_for`
    is the actual routing function. We still return a list here so the
    paradigm's trace metadata has something concrete to log.
    """
    pool: List[Dict[str, Any]] = []
    if local_model and local_endpoint:
        pool.append(
            {
                "id": len(pool),
                "name": "local-qwen",
                "type": "vllm",
                "model": local_model,
                "base_url": local_endpoint,
                "description": "Local Qwen vLLM (paper uses Qwen3-32B).",
            }
        )
    pool.append(
        {
            "id": len(pool),
            "name": "tavily-search",
            "type": "tavily-search",
            "model": "tavily",
            "description": "Tavily web search.",
        }
    )
    pool.append(
        {
            "id": len(pool),
            "name": "modal-python",
            "type": "modal-python",
            "model": "modal-python",
            "description": "Modal Sandbox for one-shot Python exec.",
        }
    )
    pool.append(
        {
            "id": len(pool),
            "name": "code-specialist",
            "type": "openrouter",
            "model": _PAPER_CODER_OPENROUTER,
            "description": "Qwen-2.5-Coder-32B via OpenRouter (paper).",
        }
    )
    pool.append(
        {
            "id": len(pool),
            "name": "generalist-llama",
            "type": "openrouter",
            "model": _PAPER_GENERALIST_TIER3_OPENROUTER,
            "description": "Llama-3.3-70B-Instruct via OpenRouter (paper tier-3).",
        }
    )
    pool.append(
        {
            "id": len(pool),
            "name": "generalist-gpt5",
            "type": "openai",
            "model": "gpt-5",
            "description": "GPT-5 frontier generalist.",
        }
    )
    pool.append(
        {
            "id": len(pool),
            "name": "generalist-gpt5-mini",
            "type": "openai",
            "model": "gpt-5-mini",
            "description": "GPT-5-mini mid generalist.",
        }
    )
    return pool


def _default_pool(
    local_model: Optional[str],
    local_endpoint: Optional[str],
    cloud_model: str = "claude-opus-4-7",
    cloud_endpoint: str = "anthropic",
) -> List[Dict[str, Any]]:
    """Default heterogeneous worker pool.

    The frontier worker's ``type`` + ``model`` track the cell's resolved
    ``(cloud_model, cloud_endpoint)`` pair so non-Anthropic cells (gpt-5,
    gemini-2.5-pro, …) route their frontier slot to the right SDK.
    """
    ep = (cloud_endpoint or "anthropic").lower()
    if ep not in ("anthropic", "openai", "gemini"):
        ep = "anthropic"
    pool: List[Dict[str, Any]] = []
    if local_model and local_endpoint:
        pool.append(
            {
                "id": len(pool),
                "name": "local-qwen",
                "type": "vllm",
                "model": local_model,
                "base_url": local_endpoint,
                "description": (
                    "Open-weights Qwen3.5 served locally. Cheap and fast. Good at "
                    "concise extraction, formatting, arithmetic on given data."
                ),
            }
        )
    if ep == "openai":
        search_type = "openai-web-search"
        search_model = cloud_model
        search_desc = "OpenAI hosted web search on the configured frontier model."
    elif ep == "gemini":
        search_type = "gemini-web-search"
        search_model = cloud_model
        search_desc = "Gemini Google Search grounding on the configured frontier model."
    else:
        search_type = "anthropic-web-search"
        search_model = _DEFAULT_WEB_SEARCH_MODEL
        search_desc = "Anthropic server-side web_search."
    pool.append(
        {
            "id": len(pool),
            "name": "web-search",
            "type": search_type,
            "model": search_model,
            "description": (
                f"{search_desc} Use for facts that need a lookup "
                "(recent events, rare names/dates, niche sources). Returns a digest."
            ),
        }
    )
    pool.append(
        {
            "id": len(pool),
            "name": f"frontier-{ep}",
            "type": ep,
            "model": cloud_model,
            "description": (
                "Frontier reasoning model. Use for hard multi-step reasoning, "
                "code review, or a final synthesis pass. Expensive — use sparingly."
            ),
        }
    )
    pool.append(
        {
            "id": len(pool),
            "name": "frontier-openai-mini",
            "type": "openai",
            "model": "gpt-5-mini",
            "description": (
                "Mid-tier OpenAI model. Solid general knowledge and reasoning at a "
                "fraction of frontier cost."
            ),
        }
    )
    return pool


# Worker types toolorchestra's `_call_worker` actually dispatches.
#
# Paper-match additions (2026-05-19) — opt in via `method_cfg.pool = "paper"`:
#   `tavily-search`  — Tavily API search (the paper's web tool).
#   `openrouter`     — OpenAI-compatible client at openrouter.ai/api/v1.
#                      Used for the code/math specialists and Llama-3.3-70B /
#                      Qwen3-32B generalists.
#   `modal-python`   — One-shot Python exec in a fresh Modal Sandbox (the
#                      paper's "Python sandbox" inside `enhance_reasoning`).
_TOOLORCH_VALID_TYPES = (
    "vllm",
    "openai",
    "anthropic",
    "anthropic-web-search",
    "openai-web-search",
    "gemini",
    "gemini-web-search",
    "tavily-search",
    "openrouter",
    "modal-python",
)
_TOOLORCH_SEARCH_TYPES = (
    "anthropic-web-search",
    "openai-web-search",
    "gemini-web-search",
    "tavily-search",
)

# Default model used when an `anthropic-web-search` entry omits `model`.
_DEFAULT_WEB_SEARCH_MODEL = "claude-haiku-4-5"


def _resolve_worker_pool(
    cfg: Dict[str, Any],
    local_model: Optional[str],
    local_endpoint: Optional[str],
    cloud_model: str,
    cloud_endpoint: str = "anthropic",
) -> List[Dict[str, Any]]:
    """Return the worker pool for this run.

    Strict replace, not merge: if ``cfg["worker_pool"]`` is set, the
    default pool is ignored entirely. Falls back to ``_default_pool`` when
    the override is absent.

    Each user-supplied entry must be a dict with keys ``id``, ``name``,
    ``type``, and (for non-search types) ``model``. Search worker types are
    ``anthropic-web-search``, ``openai-web-search``, ``gemini-web-search``,
    and ``tavily-search``. ``anthropic-web-search`` entries may omit
    ``model`` — it defaults to ``claude-haiku-4-5``. OpenAI and Gemini
    search workers default to the configured cloud model. Tavily does not
    require a model.

    Substitution: ``model = "$local"`` (or ``"<local>"``) resolves to
    ``local_model``; ``model = "$cloud"`` / ``"<cloud>"`` to ``cloud_model``.

    On any validation failure, raises ``ValueError`` with the message
    ``"Invalid worker_pool entry [<id>]: <reason>"``. Fails fast at agent
    init rather than mid-task.
    """
    override = cfg.get("worker_pool")
    if override is None:
        return _default_pool(local_model, local_endpoint, cloud_model, cloud_endpoint)
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
            raise ValueError(f"Invalid worker_pool entry [{wid}]: duplicate id")
        seen_ids.add(wid)
        if not entry.get("name") or not isinstance(entry["name"], str):
            raise ValueError(
                f"Invalid worker_pool entry [{wid}]: 'name' must be a non-empty string"
            )
        wtype = entry.get("type") or entry.get("endpoint")
        if not isinstance(wtype, str) or wtype.lower() not in _TOOLORCH_VALID_TYPES:
            raise ValueError(
                f"Invalid worker_pool entry [{wid}]: 'type' must be one of "
                f"{_TOOLORCH_VALID_TYPES} (got {wtype!r})"
            )
        wtype = wtype.lower()
        entry["type"] = wtype
        # Substitute $local / $cloud placeholders (before any model check).
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
        if wtype in _TOOLORCH_SEARCH_TYPES:
            if model in (None, ""):
                if wtype == "anthropic-web-search":
                    model = _DEFAULT_WEB_SEARCH_MODEL
                elif wtype in ("openai-web-search", "gemini-web-search"):
                    model = cloud_model
                else:
                    model = wtype
                entry["model"] = model
            elif not isinstance(model, str):
                raise ValueError(
                    f"Invalid worker_pool entry [{wid}]: 'model' must be a string when set"
                )
            if (
                wtype in ("openai-web-search", "gemini-web-search")
                and model not in PRICES
            ):
                raise ValueError(
                    f"Invalid worker_pool entry [{wid}]: model {model!r} "
                    f"is not in PRICES (known: {sorted(PRICES)})"
                )
            # Search workers don't satisfy the "needs a solver" requirement.
        else:
            if not isinstance(model, str) or not model:
                raise ValueError(
                    f"Invalid worker_pool entry [{wid}]: 'model' must be a non-empty string"
                )
            if wtype == "vllm":
                if not entry.get("base_url"):
                    if not local_endpoint:
                        raise ValueError(
                            f"Invalid worker_pool entry [{wid}]: vllm worker needs "
                            "'base_url' (or a configured local_endpoint to fall back to)"
                        )
                    entry["base_url"] = local_endpoint
                entry.setdefault("api_key", "EMPTY")
            else:
                if model not in PRICES:
                    raise ValueError(
                        f"Invalid worker_pool entry [{wid}]: model {model!r} "
                        f"is not in PRICES (known: {sorted(PRICES)})"
                    )
            has_non_search = True
        entry.setdefault(
            "description",
            f"User-supplied {wtype} worker ({model}).",
        )
        resolved.append(entry)

    if not has_non_search:
        raise ValueError(
            "Invalid worker_pool entry [-]: worker_pool must contain at least "
            "one non-search worker (vllm / openai / anthropic / gemini)"
        )
    return resolved


def _call_worker(
    worker: Dict[str, Any], prompt: str, cfg: Dict[str, Any]
) -> Tuple[str, int, int, bool, float, int]:
    """Returns (text, p_tok, c_tok, is_local, extra_cost, n_web_searches)."""
    wtype = worker.get("type", "openai")
    max_tok = int(
        cfg.get("worker_max_tokens") or os.environ.get("OJ_WORKER_MAX_TOKENS", "4096")
    )
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
        is_gpt5 = is_gpt5_family(worker["model"])
        eff_temp = 1.0 if is_gpt5 else temp
        # GPT-5 is a reasoning model: hidden reasoning tokens count against
        # `max_completion_tokens`, so a 4096 cap can be fully consumed by
        # reasoning and leave 0 visible content (empty answer). Give the
        # reasoning headroom on top of the answer budget.
        eff_max_tok = max(max_tok, 16384) if is_gpt5 else max_tok
        text, p, c = LocalCloudAgent._call_openai(
            worker["model"],
            user=prompt,
            max_tokens=eff_max_tok,
            temperature=eff_temp,
        )
        return text, p, c, False, 0.0, 0
    if wtype == "gemini":
        text, p, c = LocalCloudAgent._call_gemini(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=temp,
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
    if wtype == "openai-web-search":
        eff_temp = 1.0 if is_gpt5_family(worker["model"]) else temp
        text, p, c, n_searches, _ = LocalCloudAgent._call_openai_agent(
            worker["model"],
            user=prompt,
            max_tokens=max(max_tok, 16384)
            if is_gpt5_family(worker["model"])
            else max_tok,
            temperature=eff_temp,
        )
        extra = n_searches * OPENAI_WEB_SEARCH_COST_PER_CALL
        return text, p, c, False, extra, n_searches
    if wtype == "gemini-web-search":
        text, p, c, n_searches, _ = LocalCloudAgent._call_gemini_agent(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=temp,
        )
        extra = n_searches * GEMINI_SEARCH_COST_PER_CALL
        return text, p, c, False, extra, n_searches
    if wtype == "tavily-search":
        # Tavily costs are flat per call; charge `WEB_SEARCH_COST_PER_CALL`
        # for parity with the Anthropic web-search worker. One call = one
        # "n_search" for accounting.
        max_results = int(cfg.get("tavily_max_results", 5))
        text, p, c = _call_tavily_search(str(prompt), max_results=max_results)
        return text, p, c, False, WEB_SEARCH_COST_PER_CALL, 1
    if wtype == "openrouter":
        text, p, c = LocalCloudAgent._call_openrouter(
            worker["model"],
            user=prompt,
            max_tokens=max_tok,
            temperature=temp,
        )
        return text, p, c, False, 0.0, 0
    if wtype == "modal-python":
        # `prompt` is the python code string to exec.
        timeout_s = int(cfg.get("modal_python_timeout_s", 60))
        out, _rc = _call_modal_python(str(prompt), timeout_s=timeout_s)
        # No LLM tokens consumed; report 0 in/out. Cost is whatever Modal
        # charges per sandbox-second — not tracked here.
        return out, 0, 0, False, 0.0, 0
    raise ValueError(f"unsupported worker type: {wtype!r}")


def _swe_call_worker(
    worker: Dict[str, Any],
    prompt: str,
    cfg: Dict[str, Any],
    task: Dict[str, Any],
    workdir: Path,
    turn: int,
) -> Tuple[str, int, int, bool, float, int, int]:
    """SWE-bench worker dispatch: route solver workers through
    run_swe_agent_loop on a shared workdir. Web-search workers fall back
    to the regular one-shot dispatch (search isn't an agent loop).

    Trailing ``bash_turns`` (last element) counts agent-loop turns so the
    caller can surface ``tool_calls`` per row. Fallbacks to one-shot
    workers return 0 bash turns (no agent loop ran)."""
    wtype = worker.get("type", "openai")
    if wtype in _TOOLORCH_SEARCH_TYPES:
        # Search workers stay one-shot.
        text, p, c, is_local, extra, n_searches = _call_worker(worker, prompt, cfg)
        return text, p, c, is_local, extra, n_searches, 0
    if wtype == "vllm":
        backbone = "local"
        endpoint = worker.get("base_url")
        loop_cloud_endpoint = "anthropic"  # unused when backbone=local
    elif wtype in ("anthropic", "openai", "gemini"):
        backbone = "cloud"
        endpoint = None
        loop_cloud_endpoint = wtype
    else:
        # Unknown type — one-shot fallback.
        text, p, c, is_local, extra, n_searches = _call_worker(worker, prompt, cfg)
        return text, p, c, is_local, extra, n_searches, 0
    out = run_swe_agent_loop(
        task,
        backbone=backbone,
        backbone_model=worker["model"],
        cloud_endpoint=loop_cloud_endpoint,
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
        out["tokens_in"],
        out["tokens_out"],
        is_local,
        0.0,
        0,
        int(out["turns"]),
    )
