"""Faithful ToolOrchestra "unified tool calling" registry (arXiv:2511.21689 §3.1).

The paper exposes **every tool AND every model through a single flat tool
interface** — each is its own named function with a description and a typed
parameter schema, and for each training instance a *random subset* of tools is
sampled with *randomized pricing* (§3.3, "General tool configuration"). This is
unlike the eval-port shortcut in ``toolorchestra.py``, which collapses the whole
catalog into three meta-tools (``search``/``enhance_reasoning``/``answer``) with
a ``model`` slot. This module restores the faithful design.

Each :class:`ExpertTool` knows:

* the orchestrator-visible ``name`` / ``description`` / param schema (what goes
  into the tools JSON the policy conditions on), and
* the concrete backend (``backend_type`` + ``model`` + ``base_url``) so a caller
  can turn it into the worker dict that ``toolorchestra._call_worker`` dispatches.

Everything here is pure data + deterministic transforms (no network, no model
calls), so the spec building, sampling, and pricing logic is offline-testable.
Dispatch stays in ``toolorchestra.py`` (via :func:`to_worker_dict`) to avoid a
circular import.
"""

from __future__ import annotations

import os
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

from openjarvis.agents.hybrid._prices import PRICES

# Kinds of tool in the unified interface.
KIND_MODEL = "model"  # an LLM exposed as a tool (the paper's "models as tools")
KIND_WEB_SEARCH = "web_search"
KIND_LOCAL_SEARCH = "local_search"
KIND_CODE = "code_interpreter"
KIND_TOOL = "tool"  # a bridged real OpenJarvis tool (custom param schema)

VALID_KINDS = (KIND_MODEL, KIND_WEB_SEARCH, KIND_LOCAL_SEARCH, KIND_CODE, KIND_TOOL)

# Flat-catalog category label, surfaced in each tool's spec so the orchestrator
# can tell tool types apart without us imposing any hierarchy (the menu stays
# flat — this is just a tag).
CATEGORY_BASIC = "basic_tool"
# Two-model-class taxonomy for the orchestrator catalog — the only model tiers.
# (The legacy default_catalog still uses CATEGORY_GENERALIST/SPECIALIZED below.)
CATEGORY_CLOUD_FRONTIER = "cloud_frontier"
CATEGORY_LOCAL_OSS = "local_open_source"
# Legacy tiers kept only for default_catalog (build_unified_sft.py); not used by
# orchestrator_catalog. Superseded by the two-class taxonomy above.
CATEGORY_GENERALIST = "generalist_model"
CATEGORY_SPECIALIZED = "specialized_model"

# Backend dispatch types understood by ``toolorchestra._call_worker`` (plus the
# ``openjarvis-tool`` bridge, dispatched in ``unified.make_dispatch`` via the
# OpenJarvis ToolExecutor rather than ``_call_worker``).
VALID_BACKENDS = (
    "vllm",
    "openai",
    "anthropic",
    "gemini",
    "openrouter",
    "anthropic-web-search",
    "tavily-search",
    "modal-python",
    "openjarvis-tool",
)


@dataclass(frozen=True)
class ExpertTool:
    """One entry in the unified tool catalog.

    ``price_in`` / ``price_out`` are USD per 1M tokens (0.0 for local / non-LLM
    tools). ``latency_s`` is a rough average used only to populate the
    description's cost/latency line — the orchestrator was trained to read that
    table, so we surface it verbatim in the spec.
    """

    name: str
    kind: str
    backend_type: str
    summary: str
    model: Optional[str] = None
    base_url: Optional[str] = None
    price_in: float = 0.0
    price_out: float = 0.0
    latency_s: float = 5.0
    category: str = ""  # cloud_frontier | local_open_source | basic_tool
    # Optional explicit JSON-schema for the tool's arguments. Set for bridged
    # real OpenJarvis tools (``openjarvis-tool`` backend) whose params don't fit
    # the fixed kind-based schemas; takes precedence over the kind default.
    param_schema: Optional[dict] = None
    # When True, ``description()`` omits the price/latency line — used by the
    # anonymized catalog so the orchestrator can't route on cost/identity.
    hide_cost: bool = False

    def __post_init__(self) -> None:
        if self.kind not in VALID_KINDS:
            raise ValueError(f"{self.name}: invalid kind {self.kind!r}")
        if self.backend_type not in VALID_BACKENDS:
            raise ValueError(f"{self.name}: invalid backend {self.backend_type!r}")
        if self.kind == KIND_MODEL and not self.model:
            raise ValueError(f"{self.name}: model-kind tool needs a concrete model")

    # ---- orchestrator-visible spec -------------------------------------

    def _param_schema(self) -> Dict[str, object]:
        """JSON-schema for the tool's arguments (one typed param per kind).

        An explicit ``param_schema`` (set by :func:`openjarvis_tool` for bridged
        real tools) overrides the kind-based default.
        """
        if self.param_schema is not None:
            return self.param_schema
        if self.kind == KIND_WEB_SEARCH or self.kind == KIND_LOCAL_SEARCH:
            return {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query string.",
                    }
                },
                "required": ["query"],
            }
        if self.kind == KIND_CODE:
            return {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Python code to execute. Print results.",
                    }
                },
                "required": ["code"],
            }
        # model tool
        return {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "The sub-question or instruction for this model.",
                }
            },
            "required": ["input"],
        }

    def description(self) -> str:
        """Full description incl. the price/latency line (paper bakes this in)."""
        if self.hide_cost:
            return self.summary
        if self.kind == KIND_MODEL:
            cost_line = (
                f" Pricing: ${self.price_in:.2f}/1M input, "
                f"${self.price_out:.2f}/1M output; avg latency ~{self.latency_s:.0f}s."
            )
        else:
            cost_line = f" Avg latency ~{self.latency_s:.0f}s."
        return self.summary.rstrip(".") + "." + cost_line

    def to_spec(self) -> Dict[str, object]:
        """OpenAI-style tool spec the orchestrator conditions on.

        Flat list, but each function carries a ``category`` tag so the policy can
        distinguish generalist vs specialized models vs basic tools.
        """
        fn: Dict[str, object] = {
            "name": self.name,
            "description": self.description(),
            "parameters": self._param_schema(),
        }
        if self.category:
            fn["category"] = self.category
        return {"type": "function", "function": fn}


def _price(model: str) -> tuple[float, float]:
    return PRICES.get(model, (0.0, 0.0))


def _tool_name(model: str) -> str:
    """Tool-safe function name derived from a model id (``qwen3-8b`` -> ``qwen3_8b``).

    Strips any provider prefix and replaces non-alphanumerics with underscores so
    the catalog exposes one named tool per concrete model.
    """
    base = model.split("/")[-1].lower()
    safe = re.sub(r"[^a-z0-9]+", "_", base).strip("_")
    return safe or "local_model"


_ANON_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

# Rough size/scale hint per model — a capability signal WITHOUT the brand name,
# so the orchestrator can route big-vs-small on task difficulty but can't route on
# a proprietary name/tier prior. Closed models have no public param count, so they
# get a scale tier; open models get their param count (else parsed from the name).
_MODEL_SIZE = {
    # The real orchestrator_catalog: 2 cloud frontier + 4 local OSS Qwen.
    "gpt-5.5": "frontier-scale",
    "claude-opus-4-8": "frontier-scale",
    "Qwen/Qwen3.5-9B": "~9B params",
    "Qwen/Qwen3.6-27B-FP8": "~27B params",
    "Qwen/Qwen3.5-122B-A10B-FP8": "~122B total, ~10B active (MoE)",
    "Qwen/Qwen3.5-397B-A17B-FP8": "~397B total, ~17B active (MoE)",
    # OpenRouter slugs (the tool.model id when these route through OpenRouter).
    "qwen/qwen3.5-122b-a10b": "~122B total, ~10B active (MoE)",
    "qwen/qwen3.5-397b-a17b": "~397B total, ~17B active (MoE)",
}


def _size_hint(model: str) -> str:
    """Anonymized scale descriptor for an expert (no brand). Falls back to a
    param count parsed from the model id (``...-9b`` -> ``~9B params``)."""
    if model in _MODEL_SIZE:
        return _MODEL_SIZE[model]
    m = re.search(r"(\d+(?:\.\d+)?)\s*b\b", model.lower())
    return f"~{m.group(1)}B params" if m else "unspecified scale"


def _class_hint(tool) -> str:
    """Which of the two model classes this expert belongs to (anonymized)."""
    cat = getattr(tool, "category", "")
    if cat == CATEGORY_CLOUD_FRONTIER:
        return "cloud frontier"
    if cat == CATEGORY_LOCAL_OSS:
        return "local open-source"
    return ""


def _cost_tier_hint(tool) -> str:
    """Coarse cost tier (not exact pricing — that's the bias we anonymize away).
    Shown so the policy learns the strong-but-expensive vs cheap tradeoff instead
    of always delegating to the biggest model. Driven by class: cloud frontier is
    expensive, self-hosted open-source is cheap."""
    cat = getattr(tool, "category", "")
    if cat == CATEGORY_CLOUD_FRONTIER:
        return "expensive"
    if cat == CATEGORY_LOCAL_OSS:
        return "cheap"
    if getattr(tool, "backend_type", "") == "vllm" or (tool.price_out or 0) <= 0:
        return "cheap"
    po = tool.price_out
    return "cheap" if po < 5 else "moderate" if po < 20 else "expensive"


def anonymize_tools(tools, rng):
    """Strip model identity for unbiased routing data.

    Each MODEL expert is replaced with an opaque random label
    (``expert_<4 rand>``), a uniform description, a uniform category and no
    price/latency line — so the orchestrator cannot route on a model's name,
    position, cost, or tier (all of which we found dominate the choice). The full
    list is shuffled to kill position bias. Basic tools (calculator, web_search,
    …) keep their real names — the policy must still know what they do.

    Returns ``(anon_tools, anon_to_real)`` where ``anon_to_real`` maps each opaque
    label back to the real tool name (for offline analysis only; never shown to
    the model). ``.model`` is preserved on each tool so dispatch still reaches the
    right backend. Pass a fresh ``rng`` per rollout so labels don't stabilise.
    """
    from dataclasses import replace

    anon_to_real: Dict[str, str] = {}
    experts: List[ExpertTool] = []
    basics: List[ExpertTool] = []
    for t in tools:
        if t.kind == KIND_MODEL:
            tag = "model_" + "".join(rng.choice(_ANON_ALPHABET) for _ in range(4))
            while tag in anon_to_real:
                tag = "model_" + "".join(rng.choice(_ANON_ALPHABET) for _ in range(4))
            anon_to_real[tag] = t.name
            bits = [
                b
                for b in (_class_hint(t), _size_hint(t.model), _cost_tier_hint(t))
                if b
            ]
            experts.append(
                replace(
                    t,
                    name=tag,
                    summary="Another model — "
                    + ", ".join(bits)
                    + ". Send it a sub-question.",
                    category="model",
                    hide_cost=True,
                )
            )
        else:
            basics.append(t)
    # Shuffle WITHIN the experts to kill per-expert position bias, but keep all
    # experts as a block on top and the basic tools underneath — a clean split
    # (experts first) rather than experts and utilities interleaved.
    rng.shuffle(experts)
    out = experts + basics
    return out, anon_to_real


# Default catalog: the paper's tool categories, mapped onto the models/tools
# OpenJarvis can actually call. One named tool per model (faithful §3.1).
def default_catalog(
    *,
    local_model: Optional[str] = None,
    local_endpoint: Optional[str] = None,
) -> List[ExpertTool]:
    """Return the full unified tool catalog.

    ``local_model`` / ``local_endpoint`` wire the on-device vLLM tool when a
    local backbone is served; omitted → the local model tool is left out.
    """
    cat: List[ExpertTool] = []

    # ---- generalist / frontier models (one named tool per model VERSION) ----
    for model, summary, lat in [
        (
            "gpt-5",
            "Frontier generalist (GPT-5). Strongest reasoning across domains.",
            30.0,
        ),
        (
            "gpt-5-mini",
            "Mid-tier generalist (GPT-5-mini). Solid reasoning, much cheaper.",
            15.0,
        ),
        (
            "gpt-4o",
            "Fast generalist (GPT-4o). Good for simple steps and formatting.",
            8.0,
        ),
        (
            "claude-opus-4-7",
            "Frontier generalist (Claude Opus 4.7). Strong long-horizon reasoning.",
            26.0,
        ),
        (
            "claude-sonnet-4-6",
            "Strong generalist (Claude Sonnet 4.6). Balanced cost/capability.",
            15.0,
        ),
        (
            "gemini-2.5-pro",
            "Frontier generalist (Gemini 2.5 Pro). Strong multimodal reasoning.",
            20.0,
        ),
        ("gemini-2.5-flash", "Cheap fast generalist (Gemini 2.5 Flash).", 8.0),
        (
            "meta-llama/llama-3.3-70b-instruct",
            "Open generalist (Llama-3.3-70B). Decent general knowledge, low cost.",
            10.0,
        ),
        (
            "qwen/qwen3-32b",
            "Open generalist (Qwen3-32B). Strong math/science reasoning, low cost.",
            9.0,
        ),
    ]:
        ep = (
            "openai"
            if model.startswith("gpt")
            else "anthropic"
            if model.startswith("claude")
            else "gemini"
            if model.startswith("gemini")
            else "openrouter"
        )
        pi, po = _price(model)
        cat.append(
            ExpertTool(
                name=_tool_name(model),
                kind=KIND_MODEL,
                backend_type=ep,
                summary=summary,
                model=model,
                price_in=pi,
                price_out=po,
                latency_s=lat,
                category=CATEGORY_GENERALIST,
            )
        )

    # ---- specialized: code ----
    coder = "qwen/qwen-2.5-coder-32b-instruct"
    pi, po = _price(coder)
    cat.append(
        ExpertTool(
            name=_tool_name(coder),
            kind=KIND_MODEL,
            backend_type="openrouter",
            summary="Specialized code model (Qwen2.5-Coder-32B). Writes/debugs code.",
            model=coder,
            price_in=pi,
            price_out=po,
            latency_s=9.0,
            category=CATEGORY_SPECIALIZED,
        )
    )

    # ---- local backbone as a tool (on-device vLLM), if served ----
    # Named after the actual served model (faithful "one named tool per model"),
    # not a generic "local_model" — e.g. "qwen3-8b" -> tool "qwen3_8b".
    if local_model and local_endpoint:
        cat.append(
            ExpertTool(
                name=_tool_name(local_model),
                kind=KIND_MODEL,
                backend_type="vllm",
                summary=(
                    f"On-device open model ({local_model}) served locally. Cheap "
                    "and private; good for extraction, formatting, arithmetic on "
                    "given data."
                ),
                model=local_model,
                base_url=local_endpoint,
                price_in=0.0,
                price_out=0.0,
                latency_s=2.0,
                category=CATEGORY_GENERALIST,
            )
        )

    # ---- basic tools ----
    cat.append(
        ExpertTool(
            name="web_search",
            kind=KIND_WEB_SEARCH,
            backend_type="tavily-search",
            summary="Web search (Tavily). Use for facts that need a live lookup.",
            model="tavily",
            latency_s=8.0,
            category=CATEGORY_BASIC,
        )
    )
    cat.append(
        ExpertTool(
            name="code_interpreter",
            kind=KIND_CODE,
            backend_type="modal-python",
            summary="Python sandbox. Execute code and return stdout/stderr.",
            model="modal-python",
            latency_s=6.0,
            category=CATEGORY_BASIC,
        )
    )

    return cat


def openjarvis_tool(
    registered_name: str,
    *,
    summary: str,
    params: dict,
    latency_s: float = 5.0,
) -> ExpertTool:
    """Build an :class:`ExpertTool` that bridges a real OpenJarvis tool.

    ``registered_name`` is the tool's key in ``ToolRegistry`` (e.g. ``calculator``,
    ``shell_exec``). ``params`` is the JSON-schema *properties*-style dict for the
    tool's arguments; it is surfaced verbatim by :meth:`ExpertTool.to_spec`. The
    resulting tool dispatches through the OpenJarvis ``ToolExecutor`` (backend
    ``openjarvis-tool``) rather than ``_call_worker``.
    """
    return ExpertTool(
        name=registered_name,
        kind=KIND_TOOL,
        backend_type="openjarvis-tool",
        summary=summary,
        model=registered_name,
        latency_s=latency_s,
        category=CATEGORY_BASIC,
        param_schema=params,
    )


# Real OpenJarvis tools bridged into the orchestrator catalog as basic tools.
# Names must match the ``ToolRegistry`` keys (confirmed present: calculator,
# shell_exec, file_read, file_write, http_request).
def _openjarvis_basic_tools() -> List[ExpertTool]:
    def obj(properties: dict, required: List[str]) -> dict:
        return {"type": "object", "properties": properties, "required": required}

    return [
        openjarvis_tool(
            "calculator",
            summary="Evaluate an arithmetic / math expression and return the result.",
            params=obj(
                {
                    "expression": {
                        "type": "string",
                        "description": "Math expression to evaluate.",
                    }
                },
                ["expression"],
            ),
            latency_s=1.0,
        ),
        openjarvis_tool(
            "shell_exec",
            summary=(
                "Run a shell command and return its stdout/stderr. Critical "
                "for terminal / TerminalBench-style tasks."
            ),
            params=obj(
                {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    }
                },
                ["command"],
            ),
            latency_s=4.0,
        ),
        openjarvis_tool(
            "file_read",
            summary="Read the contents of a file at the given path.",
            params=obj(
                {
                    "path": {
                        "type": "string",
                        "description": "Path of the file to read.",
                    }
                },
                ["path"],
            ),
            latency_s=1.0,
        ),
        openjarvis_tool(
            "file_write",
            summary="Write content to a file at the given path.",
            params=obj(
                {
                    "path": {
                        "type": "string",
                        "description": "Path of the file to write.",
                    },
                    "content": {"type": "string", "description": "Content to write."},
                },
                ["path", "content"],
            ),
            latency_s=1.0,
        ),
        openjarvis_tool(
            "http_request",
            summary="Make an HTTP request to a URL and return the response body.",
            params={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Request URL."},
                    "method": {
                        "type": "string",
                        "description": "HTTP method (GET, POST, ...). Default GET.",
                    },
                },
                "required": ["url"],
            },
            latency_s=4.0,
        ),
        openjarvis_tool(
            "think",
            summary=(
                "Record a private reasoning step (scratchpad). No external "
                "effect; use to plan before acting on hard reasoning tasks."
            ),
            params=obj(
                {
                    "thought": {
                        "type": "string",
                        "description": "Your reasoning or thought process.",
                    }
                },
                ["thought"],
            ),
            latency_s=0.5,
        ),
        openjarvis_tool(
            "apply_patch",
            summary=(
                "Apply a unified-diff patch to a file. Use to edit code for "
                "terminal / SWE-style tasks."
            ),
            params=obj(
                {
                    "patch": {
                        "type": "string",
                        "description": "The unified diff patch text to apply.",
                    },
                    "path": {
                        "type": "string",
                        "description": "Target file path (auto-detected from the "
                        "patch header if omitted).",
                    },
                },
                ["patch"],
            ),
            latency_s=2.0,
        ),
        openjarvis_tool(
            "pdf_extract",
            summary=(
                "Extract text from a PDF file. Use for GAIA-style tasks with "
                "PDF attachments."
            ),
            params=obj(
                {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the PDF file.",
                    },
                    "pages": {
                        "type": "string",
                        "description": "Page range, e.g. '1-5' or '1,3,5'. "
                        "Omit for all pages.",
                    },
                },
                ["file_path"],
            ),
            latency_s=3.0,
        ),
        openjarvis_tool(
            "db_query",
            summary=(
                "Run a SQL query against a SQLite/Postgres database and return "
                "rows. Read-only by default."
            ),
            params=obj(
                {
                    "query": {"type": "string", "description": "SQL query to execute."},
                    "db_path": {
                        "type": "string",
                        "description": "Path to a SQLite DB file. Defaults to "
                        "in-memory.",
                    },
                    "read_only": {
                        "type": "boolean",
                        "description": "Restrict to SELECT/EXPLAIN/PRAGMA. "
                        "Default: true.",
                    },
                },
                ["query"],
            ),
            latency_s=3.0,
        ),
    ]


# Local-Cloud Hybrid orchestrator catalog. The menu is two model classes — cloud
# frontier models and open-source models — plus the basic tools (web search, code
# interpreter, and the bridged real OpenJarvis tools). The orchestrator model
# itself is NOT in the catalog.
#
# Routing default is OpenRouter for every model tool, so the catalog works with
# no self-hosted servers. A model is routed to local vLLM instead when its id is
# in ``local_endpoints`` or ``model_backends`` overrides it. The
# orchestrator-visible tool *name* is always derived from the canonical id, so
# routing can change (vLLM <-> OpenRouter <-> native API) without shifting the
# menu the policy was trained on.
_LOCAL_OSS_MODELS = (
    # (canonical_id, openrouter_slug)
    ("Qwen/Qwen3.5-9B", "qwen/qwen3.5-9b"),
    ("Qwen/Qwen3.6-27B-FP8", "qwen/qwen3.6-27b"),
    ("Qwen/Qwen3.5-122B-A10B-FP8", "qwen/qwen3.5-122b-a10b"),
    ("Qwen/Qwen3.5-397B-A17B-FP8", "qwen/qwen3.5-397b-a17b"),
)

_CLOUD_FRONTIER_MODELS = (
    # (canonical, native_backend, openrouter_slug, summary, latency_s)
    # Neutral, uniform summaries (no capability ranking) so the orchestrator
    # doesn't just pick whichever model is labelled "strongest" — routing should
    # be learned from the reward, not hand-labelled here.
    ("gpt-5.5", "openai", "openai/gpt-5.5", "Expert model (GPT-5.5).", 30.0),
    (
        "claude-opus-4-8",
        "anthropic",
        "anthropic/claude-opus-4.8",
        "Expert model (Claude Opus 4.8).",
        26.0,
    ),
)


def _model_tool(
    canonical: str,
    *,
    native_backend: str,
    or_slug: str,
    summary: str,
    lat: float,
    category: str,
    local_endpoints: Dict[str, str],
    model_backends: Dict[str, str],
    openrouter_slugs: Dict[str, str],
) -> ExpertTool:
    """Build one model tool, resolving its backend.

    Backend precedence: explicit ``model_backends[canonical]`` > vLLM if the model
    has a ``local_endpoints`` entry > the model's NATIVE provider (openai /
    anthropic / gemini) when it has one > OpenRouter. Frontier models thus hit
    their first-party API by default (OpenRouter's gpt-5.5 was returning 400s);
    OSS Qwen experts (native_backend="vllm") fall through to OpenRouter.
    """
    backend = (
        model_backends.get(canonical)
        or ("vllm" if canonical in local_endpoints else None)
        or (
            native_backend
            if native_backend in ("openai", "anthropic", "gemini")
            else "openrouter"
        )
    )
    name = _tool_name(canonical)
    if backend == "vllm":
        # Self-hosted: free per the cost model.
        return ExpertTool(
            name=name,
            kind=KIND_MODEL,
            backend_type="vllm",
            summary=summary,
            model=canonical,
            base_url=local_endpoints.get(canonical),
            price_in=0.0,
            price_out=0.0,
            latency_s=lat,
            category=category,
        )
    if backend == "openrouter":
        slug = openrouter_slugs.get(canonical, or_slug)
        pi, po = _price(slug)
        if (pi, po) == (0.0, 0.0):  # fall back to the canonical id's price
            pi, po = _price(canonical)
        return ExpertTool(
            name=name,
            kind=KIND_MODEL,
            backend_type="openrouter",
            summary=summary,
            model=slug,
            base_url=None,
            price_in=pi,
            price_out=po,
            latency_s=lat,
            category=category,
        )
    # native provider API (openai / anthropic / gemini)
    pi, po = _price(canonical)
    return ExpertTool(
        name=name,
        kind=KIND_MODEL,
        backend_type=backend,
        summary=summary,
        model=canonical,
        price_in=pi,
        price_out=po,
        latency_s=lat,
        category=category,
    )


def orchestrator_catalog(
    *,
    local_endpoints: Optional[Dict[str, str]] = None,
    model_backends: Optional[Dict[str, str]] = None,
    openrouter_slugs: Optional[Dict[str, str]] = None,
    include_tools: bool = True,
) -> List[ExpertTool]:
    """Return the orchestrator's tool catalog: two model classes + basic tools.

    Routing for the model tools defaults to **OpenRouter** (so the catalog works
    with no self-hosted servers). Overrides, in precedence order:

    * ``model_backends`` maps a canonical model id -> ``"vllm" | "openrouter" |
      "openai" | "anthropic" | "gemini"`` to force that model's backend.
    * ``local_endpoints`` maps a canonical id (e.g. ``"Qwen/Qwen3.5-9B"``) to a
      vLLM ``base_url``; a model present here routes to vLLM (free) unless
      ``model_backends`` says otherwise.
    * ``openrouter_slugs`` overrides the per-model OpenRouter slug used when a
      model routes through OpenRouter.

    ``include_tools`` (default True) appends the basic tools — web search, code
    interpreter, and the bridged real OpenJarvis tools (calculator, shell_exec,
    file_read, file_write, http_request).
    """
    local_endpoints = local_endpoints or {}
    model_backends = model_backends or {}
    openrouter_slugs = openrouter_slugs or {}
    cat: List[ExpertTool] = []

    # Env-gated expert exclusion: OJ_EXCLUDE_EXPERTS is a comma-separated list of
    # case-insensitive substrings matched against a model's canonical id. Any
    # match is skipped from the catalog. Used to temporarily drop unreliable
    # experts (e.g. OpenRouter giants during a provider outage) without editing
    # the registry — unset the var to restore them.
    _excl = {
        s.strip().lower()
        for s in os.environ.get("OJ_EXCLUDE_EXPERTS", "").split(",")
        if s.strip()
    }

    def _excluded(canonical: str) -> bool:
        c = canonical.lower()
        return any(x in c for x in _excl)

    # ---- cloud frontier models ----
    for canonical, native_backend, or_slug, summary, lat in _CLOUD_FRONTIER_MODELS:
        if _excluded(canonical):
            continue
        cat.append(
            _model_tool(
                canonical,
                native_backend=native_backend,
                or_slug=or_slug,
                summary=summary,
                lat=lat,
                category=CATEGORY_CLOUD_FRONTIER,
                local_endpoints=local_endpoints,
                model_backends=model_backends,
                openrouter_slugs=openrouter_slugs,
            )
        )

    # ---- open-source models (OpenRouter by default; vLLM when an endpoint or
    #      a model_backends override is supplied) ----
    for canonical, or_slug in _LOCAL_OSS_MODELS:
        if _excluded(canonical):
            continue
        cat.append(
            _model_tool(
                canonical,
                native_backend="vllm",
                or_slug=or_slug,
                summary=f"Expert model ({canonical}).",
                lat=4.0,
                category=CATEGORY_LOCAL_OSS,
                local_endpoints=local_endpoints,
                model_backends=model_backends,
                openrouter_slugs=openrouter_slugs,
            )
        )

    if include_tools:
        # ---- basic tools ----
        cat.append(
            ExpertTool(
                name="web_search",
                kind=KIND_WEB_SEARCH,
                backend_type="tavily-search",
                summary="Web search (Tavily). Use for facts that need a live lookup.",
                model="tavily",
                latency_s=8.0,
                category=CATEGORY_BASIC,
            )
        )
        cat.append(
            ExpertTool(
                name="code_interpreter",
                kind=KIND_CODE,
                backend_type="modal-python",
                summary="Python sandbox. Execute code and return stdout/stderr.",
                model="modal-python",
                latency_s=6.0,
                category=CATEGORY_BASIC,
            )
        )
        cat.extend(_openjarvis_basic_tools())

    return cat


def build_tool_specs(tools: List[ExpertTool]) -> List[Dict[str, object]]:
    """Turn a tool list into the OpenAI-style tools JSON the policy sees."""
    return [t.to_spec() for t in tools]


def tools_by_name(tools: List[ExpertTool]) -> Dict[str, ExpertTool]:
    return {t.name: t for t in tools}


def sample_tool_config(
    catalog: List[ExpertTool],
    *,
    rng: random.Random,
    min_tools: int = 4,
    max_tools: Optional[int] = None,
    price_jitter: float = 0.0,
) -> List[ExpertTool]:
    """Sample a random tool subset with optional price randomization (§3.3).

    Guarantees at least one ``model`` tool and at least one non-model (basic)
    tool so every instance can both reason and act. ``price_jitter`` (e.g. 0.5)
    multiplies each model's prices by a per-tool factor drawn uniformly from
    ``[1-jitter, 1+jitter]``, modeling heterogeneous pricing across users.
    Deterministic given ``rng``.
    """
    if not catalog:
        raise ValueError("empty catalog")
    models = [t for t in catalog if t.kind == KIND_MODEL]
    basics = [t for t in catalog if t.kind != KIND_MODEL]
    if not models:
        raise ValueError("catalog has no model tools")

    hi = max_tools if max_tools is not None else len(catalog)
    hi = min(hi, len(catalog))
    lo = min(max(min_tools, 2), hi)
    k = rng.randint(lo, hi)

    # Always include >=1 model; include >=1 basic if any exist.
    chosen: List[ExpertTool] = [rng.choice(models)]
    if basics:
        chosen.append(rng.choice(basics))
    pool = [t for t in catalog if t not in chosen]
    rng.shuffle(pool)
    for t in pool:
        if len(chosen) >= k:
            break
        chosen.append(t)

    # Re-order to catalog order for stable specs.
    order = {t.name: i for i, t in enumerate(catalog)}
    chosen.sort(key=lambda t: order[t.name])

    if price_jitter > 0.0:
        jittered: List[ExpertTool] = []
        for t in chosen:
            if t.kind == KIND_MODEL and (t.price_in or t.price_out):
                f = rng.uniform(1.0 - price_jitter, 1.0 + price_jitter)
                jittered.append(
                    ExpertTool(
                        name=t.name,
                        kind=t.kind,
                        backend_type=t.backend_type,
                        summary=t.summary,
                        model=t.model,
                        base_url=t.base_url,
                        price_in=round(t.price_in * f, 4),
                        price_out=round(t.price_out * f, 4),
                        latency_s=t.latency_s,
                    )
                )
            else:
                jittered.append(t)
        return jittered
    return chosen


def to_worker_dict(tool: ExpertTool) -> Dict[str, object]:
    """Convert a tool into the worker dict ``toolorchestra._call_worker`` eats."""
    d: Dict[str, object] = {
        "name": tool.name,
        "type": tool.backend_type,
        "model": tool.model,
    }
    if tool.base_url:
        d["base_url"] = tool.base_url
    return d


__all__ = [
    "CATEGORY_BASIC",
    "CATEGORY_CLOUD_FRONTIER",
    "CATEGORY_GENERALIST",
    "CATEGORY_LOCAL_OSS",
    "CATEGORY_SPECIALIZED",
    "ExpertTool",
    "KIND_CODE",
    "KIND_LOCAL_SEARCH",
    "KIND_MODEL",
    "KIND_TOOL",
    "KIND_WEB_SEARCH",
    "build_tool_specs",
    "default_catalog",
    "openjarvis_tool",
    "orchestrator_catalog",
    "sample_tool_config",
    "to_worker_dict",
    "tools_by_name",
]
