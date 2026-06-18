"""MinionsAgent — port of HazyResearch Minions protocol.

Cloud supervisor decomposes the task and reads back local-worker output;
local worker(s) do the bulk reading/extraction. Multi-turn loop until the
supervisor commits to a final answer.

Two modes (``cfg["mode"]``):

- ``"minion"`` — single local worker, one cloud supervisor (cheaper).
  Default.
- ``"minions"`` — parallel local workers, cloud aggregator.

Hybrid harness result: ``minions-swebenchverified-qwen27b-opus-500`` =
0.274 acc / $0.09 per task — beats baseline-cloud's 0.236 / $0.95 on
**both** accuracy and cost. GAIA at n=165 ties baseline-cloud at 0.576
acc / $0.67 (vs $1.09).

Requires the ``minions`` library from
https://github.com/HazyResearch/minions installed in the same env (e.g.
``uv pip install -e path/to/minions``). Import is lazy — the agent class
registers without ``minions`` available, and the import error only fires
on ``run()``.

Compatibility patches applied at first ``run()`` (idempotent):

- Strip ``temperature`` for Opus 4.7+ (rejected with 400).
- Inject server-side ``output_config`` JSON schema on supervisor turns
  so Opus replies in the shape Minions's parser expects (per-turn schema
  picked by sniffing the prompt for ``"decision": "provide_final_answer"``).
- Replace Minions's ``_extract_json`` with a wrapper that short-circuits
  when the response is already valid JSON.
- Inject ``timeout=600``/``max_retries=5`` defaults into
  ``anthropic.Anthropic()`` — Minions builds bare clients which 60s-timeout
  under SWE-bench concurrency=8.

Ported from ``hybrid-local-cloud-compute/adapters/minions_adapter.py``.
"""

from __future__ import annotations

import json as _json
import sys
import types
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import (
    WEB_SEARCH_COST_PER_CALL,
    LocalCloudAgent,
    build_web_search_tool,
    tavily_search_context,
    web_search_cfg,
)
from openjarvis.agents.hybrid._openai_retry import (
    patch_openai_globally as _patch_openai_globally,
)
from openjarvis.agents.hybrid._prices import NO_TEMP_PREFIXES, default_max_output_tokens
from openjarvis.agents.hybrid.mini_swe_agent import run_swe_agent_loop
from openjarvis.core.registry import AgentRegistry

MINIONS_SWE_PLANNER_SYS = (
    "You are the cloud supervisor in a Minions setup. The small local model "
    "is about to run an agent loop (with shell access) against a Python "
    "repository to fix a bug. Read the issue and write a concise plan: "
    "what files the local model should look at first, what tests are most "
    "relevant, and 1-3 concrete approaches it should try. Be specific — "
    "this is the local model's only briefing from you. Reply in 8 bullet "
    "points or fewer."
)


# ---------- Per-turn JSON schemas (server-side enforcement) ----------
#
# Minions's supervisor produces different JSON shapes per turn:
#   turn 1 (decompose):     {reasoning, message}
#   turn 2+ (continue):     {decision="request_additional_info", message}
#   turn 2+ (final answer): {decision="provide_final_answer", answer}
#
# Anthropic strict mode requires additionalProperties:false + all-props
# required, so we pick the schema PER TURN by sniffing the prompt for
# Minions's turn-2 template marker.

MINIONS_FIRST_TURN_SCHEMA = {
    "format": {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
                "message":   {"type": "string"},
            },
            "required": ["reasoning", "message"],
            "additionalProperties": False,
        },
    }
}

MINIONS_CONVERSATION_SCHEMA = {
    "format": {
        "type": "json_schema",
        "schema": {
            "anyOf": [
                {
                    "type": "object",
                    "properties": {
                        "decision": {"const": "request_additional_info"},
                        "message":  {"type": "string"},
                    },
                    "required": ["decision", "message"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "decision": {"const": "provide_final_answer"},
                        "answer":   {"type": "string"},
                    },
                    "required": ["decision", "answer"],
                    "additionalProperties": False,
                },
            ],
        },
    }
}

# Markers from Minions's supervisor prompts (prompts/minion.py). Any one
# being present in the call's messages/system is a strong Minions signal.
MINIONS_PROMPT_MARKERS = (
    "small language model that has read",   # SUPERVISOR_INITIAL_PROMPT
    "provide_final_answer",                  # SUPERVISOR_CONVERSATION_PROMPT
    "request_additional_info",
)


def _looks_like_minions_call(kwargs: Dict[str, Any]) -> bool:
    blob_parts = [str(kwargs.get("system", ""))]
    for msg in kwargs.get("messages", []) or []:
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        blob_parts.append(str(content))
    blob = "\n".join(blob_parts)
    return any(m in blob for m in MINIONS_PROMPT_MARKERS)


def _minions_turn_schema(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Pick the schema by sniffing the prompt — see module docstring."""
    blob_parts = [str(kwargs.get("system", ""))]
    for msg in kwargs.get("messages", []) or []:
        content = msg.get("content", "") if isinstance(msg, dict) else ""
        blob_parts.append(str(content))
    blob = "\n".join(blob_parts)
    if (
        '"decision": "provide_final_answer"' in blob
        or '"decision":"provide_final_answer"' in blob
    ):
        return MINIONS_CONVERSATION_SCHEMA
    return MINIONS_FIRST_TURN_SCHEMA


# ---------- Compatibility patches (idempotent) ----------

_PATCHES_APPLIED = False


def _stub_missing_imports() -> None:
    """Minions's clients/__init__.py eager-imports every provider client.

    Two annoyances:
    1. ``mistralai`` 2.x dropped top-level ``Mistral`` → ImportError.
    2. The secure-chat path imports ``nv_attestation_sdk`` which writes a log
       file to CWD at import-time. We don't use secure chat.
    """
    try:
        import mistralai
        if not hasattr(mistralai, "Mistral"):
            mistralai.Mistral = type("Mistral", (), {})  # type: ignore[attr-defined]
    except ImportError:
        sys.modules["mistralai"] = types.ModuleType("mistralai")
        sys.modules["mistralai"].Mistral = type("Mistral", (), {})  # type: ignore[attr-defined]
    sys.modules.setdefault("nv_attestation_sdk", None)  # type: ignore[arg-type]


def _patch_anthropic_globally() -> None:
    import anthropic as _anth_mod
    from anthropic.resources.beta.messages import messages as _beta_msgs_mod
    from anthropic.resources.messages import messages as _msgs_mod

    # External Minions builds bare anthropic.Anthropic() clients (no timeout
    # / max_retries). Under concurrency=8 SWE-bench load those default to
    # ~60s and timeout in droves. Inject sane defaults at the constructor.
    if not getattr(_anth_mod.Anthropic.__init__, "_hybrid_patched", False):
        _orig_init = _anth_mod.Anthropic.__init__

        def _patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            kwargs.setdefault("timeout", 600.0)
            kwargs.setdefault("max_retries", 5)
            return _orig_init(self, *args, **kwargs)

        _patched_init._hybrid_patched = True  # type: ignore[attr-defined]
        _anth_mod.Anthropic.__init__ = _patched_init  # type: ignore[assignment]

    for cls in (_msgs_mod.Messages, _beta_msgs_mod.Messages):
        if getattr(cls.create, "_hybrid_patched", False):
            continue
        orig = cls.create

        def make_patched(orig):  # type: ignore[no-untyped-def]
            def patched(self, **kwargs):  # type: ignore[no-untyped-def]
                # External Minions's AnthropicClient.chat passes
                # `cache_control={"type":"ephemeral"}` as a top-level kwarg
                # (clients/anthropic.py:207). Newer Anthropic SDKs reject that
                # — cache_control belongs on individual content blocks, not on
                # Messages.create itself. Strip it; we're not relying on the
                # ephemeral hint for correctness in these short minions turns.
                kwargs.pop("cache_control", None)
                model = kwargs.get("model", "")
                if model.startswith(NO_TEMP_PREFIXES):
                    kwargs.pop("temperature", None)
                    if (
                        "output_config" not in kwargs
                        and _looks_like_minions_call(kwargs)
                    ):
                        kwargs["output_config"] = _minions_turn_schema(kwargs)
                return orig(self, **kwargs)
            patched._hybrid_patched = True  # type: ignore[attr-defined]
            return patched

        cls.create = make_patched(orig)  # type: ignore[assignment]


def _patch_gemini_client_usage() -> None:
    """Patch vendored ``GeminiClient.schat`` for Gemini 2.5 quirks.

    Two issues in the upstream client:

    1. ``response.usage_metadata.candidates_token_count`` is sometimes ``None``
       (empty / thinking-only responses on 2.5 Pro), and the upstream code
       does ``total_token_count - candidates_token_count`` raw → ``TypeError``.

    2. ``response.text`` raises if the model only emitted a non-text part
       (e.g. safety block, thinking-only). We swallow it as empty.

    Both fixes are idempotent and bypass the original ``schat`` body only
    on the value-extraction lines — the API call itself is unchanged.
    """
    from minions.clients.gemini import GeminiClient  # type: ignore[import-not-found]
    from minions.usage import Usage  # type: ignore[import-not-found]

    if getattr(GeminiClient.schat, "_hybrid_patched", False):
        return

    _orig_schat = GeminiClient.schat

    def _safe_int(x):  # type: ignore[no-untyped-def]
        try:
            return int(x) if x is not None else 0
        except (TypeError, ValueError):
            return 0

    def patched_schat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
        # Mirror the upstream "native" branch by hand, but defensively.
        # Skip the OpenAI-compat branch — Minions paradigm never sets that.
        if self.use_openai_api:
            return _orig_schat(self, messages, **kwargs)
        if isinstance(messages, dict):
            messages = [messages]
        contents, system_instruction = self._format_content(messages)
        if not system_instruction:
            system_instruction = self.system_instruction
        tools = self._prepare_tools(messages=messages)
        config_kwargs = {
            "temperature": self.temperature,
            "max_output_tokens": self.max_tokens,
        }
        if self.thinking_budget is not None or self.thinking_level is not None:
            tc = {}
            if self.thinking_budget is not None:
                tc["thinking_budget"] = self.thinking_budget
            if self.thinking_level is not None:
                tc["thinking_level"] = self.thinking_level
            config_kwargs["thinking_config"] = self.types.ThinkingConfig(**tc)
        if tools:
            config_kwargs["tools"] = tools
        config_kwargs["system_instruction"] = system_instruction
        config = self.types.GenerateContentConfig(**config_kwargs)

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=contents,
            config=config,
        )

        # Defensive text accessor — upstream `response.text` can raise when
        # the model only emitted a non-text part.
        try:
            text = response.text or ""
        except Exception:
            try:
                parts = response.candidates[0].content.parts or []
                text = "".join(getattr(p, "text", "") or "" for p in parts)
            except Exception:
                text = ""

        um = getattr(response, "usage_metadata", None)
        total = _safe_int(getattr(um, "total_token_count", 0)) if um else 0
        comp = _safe_int(getattr(um, "candidates_token_count", 0)) if um else 0
        prompt = _safe_int(getattr(um, "prompt_token_count", 0)) if um else 0
        # Prefer the explicit prompt count if present; fall back to (total - comp).
        if not prompt and total:
            prompt = max(total - comp, 0)
        usage = Usage(prompt_tokens=prompt, completion_tokens=comp)

        if self.local:
            return [text], usage, ["stop"]
        return [text], usage

    patched_schat._hybrid_patched = True  # type: ignore[attr-defined]
    GeminiClient.schat = patched_schat  # type: ignore[assignment]


def _patch_minions_extract_json() -> None:
    """Minions's ``_extract_json`` uses a non-greedy regex that grabs the
    first short bracket pair and prefers ```json``` fences. With structured
    outputs the entire response IS valid JSON, so short-circuit on that.
    """
    from minions import minion as _minion_mod  # type: ignore[import-not-found]

    if getattr(_minion_mod._extract_json, "_hybrid_patched", False):
        return
    _orig = _minion_mod._extract_json

    def patched(text):  # type: ignore[no-untyped-def]
        s = (text or "").strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                return _json.loads(s)
            except _json.JSONDecodeError:
                pass
        return _orig(text)

    patched._hybrid_patched = True  # type: ignore[attr-defined]
    _minion_mod._extract_json = patched  # type: ignore[assignment]


def _apply_patches_once() -> None:
    global _PATCHES_APPLIED
    if _PATCHES_APPLIED:
        return
    _stub_missing_imports()
    _patch_anthropic_globally()
    # Mirror the Anthropic patch for OpenAI so the Minions library's own
    # ``OpenAIClient`` instances pick up retry + per-org concurrency caps.
    # Idempotent — also applied at ``_base`` import time.
    _patch_openai_globally()
    _patch_gemini_client_usage()
    _patch_minions_extract_json()
    _PATCHES_APPLIED = True


# ---------- Pre-fetch helper (GAIA only) ----------

def _prefetch_context(
    question: str,
    cloud_endpoint: str,
    cloud_model: str,
    max_uses: int = 8,
    search_backend: str = "provider",
    tavily_max_results: int = 5,
) -> Dict[str, Any]:
    """Use Anthropic web_search to fetch real source material the worker can read.

    Minions's premise is "worker reads a doc, asks cloud for help" — but GAIA
    tasks ship with no doc, so we synthesize one by having Opus do an actual
    web search first and dump the results back as the worker's context.

    Returns {text, tokens, cost_usd, n_searches}. On any failure: empty text
    and zeros — the protocol still runs.
    """
    out: Dict[str, Any] = {
        "text": "", "tokens": 0, "cost_usd": 0.0, "n_searches": 0,
    }
    if search_backend == "tavily":
        try:
            res = tavily_search_context(question, max_results=tavily_max_results)
            out.update(
                text=res["text"],
                cost_usd=float(res["cost_usd"]),
                n_searches=int(res["n_searches"]),
                tokens=0,
                engine=res.get("engine"),
                credits=res.get("credits"),
            )
            if res.get("error"):
                out["error"] = res["error"]
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
        return out
    if cloud_endpoint != "anthropic" or not (question or "").strip():
        return out
    try:
        prompt = (
            "Research the following question using web_search. Do NOT answer it. "
            "Instead, gather all relevant facts, numbers, names, dates, sources, "
            "and direct quotes you find, and report them as a dense reference "
            "document with URLs. The downstream reader is a small LLM that "
            "needs raw material to reason over.\n\nQUESTION:\n" + question
        )
        text, p, c, n_searches = LocalCloudAgent._call_anthropic(
            cloud_model,
            user=prompt,
            max_tokens=8192,
            tools=[build_web_search_tool(max_uses)],
            tool_choice={"type": "any"},
        )
        from openjarvis.agents.hybrid._prices import cost as _cost_usd
        out.update(
            text=text,
            tokens=p + c,
            cost_usd=_cost_usd(cloud_model, p, c) + n_searches * WEB_SEARCH_COST_PER_CALL,
            n_searches=n_searches,
        )
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def _context_for(
    task: Optional[Dict[str, Any]], prefetched: str = ""
) -> List[str]:
    """Minions wants a context list."""
    bits: List[str] = []
    task = task or {}
    if task.get("hints_text"):
        bits.append(task["hints_text"])
    if task.get("problem_statement") and not task.get("question"):
        bits.append(task["problem_statement"])
    if prefetched:
        bits.append(prefetched)
    return bits or [""]


# ---------- Main agent ----------

@AgentRegistry.register("minions")
class MinionsAgent(LocalCloudAgent):
    """HazyResearch Minions supervisor/worker protocol. See module docstring."""

    agent_id = "minions"

    def _is_soft_failure(self, exc: BaseException) -> Optional[str]:
        # Known soft-failure modes: Qwen worker JSON malformed, Anthropic
        # 400/529, KeyError on missing schema fields.
        try:
            import anthropic
            if isinstance(exc, anthropic.BadRequestError):
                return f"{type(exc).__name__}: {str(exc)[:120]}"
        except Exception:
            pass
        if isinstance(exc, (_json.JSONDecodeError, ValueError, KeyError)):
            return f"{type(exc).__name__}: {str(exc)[:120]}"
        if "JSONDecodeError" in type(exc).__name__:
            return f"{type(exc).__name__}: {str(exc)[:120]}"
        if "prompt is too long" in str(exc):
            return f"{type(exc).__name__}: {str(exc)[:120]}"
        return None

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        cfg = self._cfg
        task_meta: Dict[str, Any] = {}
        if context is not None:
            task_meta = context.metadata.get("task", {}) or {}

        # SWE-bench branch: the upstream Minions library doesn't fit
        # SWE-bench (it's "small model reads docs, big model summarizes").
        # Instead, mirror Minions's "cloud supervises, local does the
        # work" pattern: cloud writes a high-level fix plan, local Qwen
        # runs mini-SWE-agent with that plan as additional context.
        swe_mode = (
            bool(cfg.get("swe_use_agent_loop"))
            and bool(task_meta.get("problem_statement"))
            and bool(task_meta.get("repo"))
            and bool(task_meta.get("base_commit"))
        )
        if swe_mode:
            return self._run_swe(input, task_meta, cfg)

        _apply_patches_once()
        from minions.clients.anthropic import (
            AnthropicClient,  # type: ignore[import-not-found]
        )
        from minions.clients.gemini import (
            GeminiClient,  # type: ignore[import-not-found]
        )
        from minions.clients.openai import (
            OpenAIClient,  # type: ignore[import-not-found]
        )
        from minions.minion import Minion  # type: ignore[import-not-found]
        from minions.minions import Minions  # type: ignore[import-not-found]

        mode = cfg.get("mode", "minion")

        if not self._local_endpoint or not self._local_model:
            raise ValueError(
                "MinionsAgent needs local_model + local_endpoint; got "
                f"model={self._local_model!r} endpoint={self._local_endpoint!r}"
            )

        local_client = OpenAIClient(
            model_name=self._local_model,
            base_url=self._local_endpoint,
            api_key="EMPTY",
            temperature=cfg.get("local_temperature", 0.0),
            max_tokens=cfg.get("worker_max_tokens", 4096),
            local=True,
        )
        cloud_max_tokens = int(
            cfg.get("cloud_max_tokens")
            or default_max_output_tokens(self._cloud_model)
        )
        if self._cloud_endpoint == "openai":
            cloud_client = OpenAIClient(
                model_name=self._cloud_model,
                temperature=0.0,
                max_tokens=cloud_max_tokens,
            )
        elif self._cloud_endpoint == "anthropic":
            # Temperature stripping is handled by the global patch above for Opus 4.7+.
            cloud_client = AnthropicClient(
                model_name=self._cloud_model,
                temperature=0.0,
                max_tokens=cloud_max_tokens,
            )
        elif self._cloud_endpoint == "gemini":
            # The vendored Minion library already special-cases GeminiClient
            # in minion.py: it passes response_mime_type=application/json plus
            # a Pydantic response_schema so the supervisor reply parses with
            # the same {decision, message, answer} shape Opus/GPT use. We just
            # have to hand it a GeminiClient instance — no extra plumbing.
            cloud_client = GeminiClient(
                model_name=self._cloud_model,
                temperature=0.0,
                max_tokens=cloud_max_tokens,
            )
        else:
            raise ValueError(f"unsupported cloud endpoint: {self._cloud_endpoint!r}")

        cls = Minions if mode == "minions" else Minion
        log_dir = cfg.get("log_dir") or "/tmp/minions_logs"
        protocol = cls(
            local_client=local_client,
            remote_client=cloud_client,
            max_rounds=cfg.get("max_rounds", 3),
            log_dir=log_dir,
        )

        # GAIA-shape only: prefetch a web_search digest so the worker has
        # something real to read. SWE-bench (problem_statement only) already
        # ships its own doc.
        #
        # Honors the new ``method_cfg.web_search`` schema:
        #   - omitted          → prefetch ON (legacy default for minions GAIA)
        #   - enabled = false  → prefetch OFF
        #   - enabled = true   → prefetch ON (honors max_uses)
        prefetch: Dict[str, Any] = {
            "text": "", "tokens": 0, "cost_usd": 0.0, "n_searches": 0,
        }
        ws_block = cfg.get("web_search") if isinstance(cfg.get("web_search"), dict) else None
        ws_enabled, ws_max_uses = web_search_cfg(cfg)
        # If the cell explicitly set web_search.enabled = false, honor that.
        # If it set web_search.enabled = true, honor max_uses. If it didn't
        # set a web_search block at all, keep legacy prefetch ON.
        prefetch_on = (
            ws_block is None  # legacy default
            or ws_enabled
        )
        if task_meta.get("question") and prefetch_on:
            prefetch = _prefetch_context(
                task_meta["question"],
                self._cloud_endpoint,
                self._cloud_model,
                max_uses=ws_max_uses,
                search_backend=str(cfg.get("search_backend", "provider")).lower(),
                tavily_max_results=int(cfg.get("tavily_max_results", 5)),
            )

        if prefetch.get("text"):
            self.record_trace_event({
                "kind": "minions_prefetch",
                "n_searches": prefetch["n_searches"],
                "tokens": prefetch["tokens"],
                "cost_usd": prefetch["cost_usd"],
                "text": prefetch["text"],
                "error": prefetch.get("error"),
            })

        out = protocol(
            task=input,  # full formatted prompt (with bench instruction)
            context=_context_for(task_meta, prefetched=prefetch["text"]),
            doc_metadata=cfg.get("doc_metadata", "task"),
            max_rounds=cfg.get("max_rounds", 3),
        )

        # The Minions library doesn't go through our SDK helpers, so the
        # auto-trace missed every turn. Record the protocol output directly —
        # supervisor_messages + worker_messages contain the full conversation.
        self.record_trace_event({
            "kind": "minions_protocol",
            "mode": mode,
            "supervisor_messages": out.get("supervisor_messages"),
            "worker_messages": out.get("worker_messages"),
            "timing": out.get("timing"),
            "log_file": out.get("log_file"),
            "final_answer": out.get("final_answer", ""),
        })

        local_usage = out.get("local_usage")
        remote_usage = out.get("remote_usage")
        lp = getattr(local_usage, "prompt_tokens", 0)
        lc = getattr(local_usage, "completion_tokens", 0)
        rp = getattr(remote_usage, "prompt_tokens", 0)
        rc = getattr(remote_usage, "completion_tokens", 0)

        meta = {
            "tokens_local": lp + lc,
            "tokens_cloud": (rp + rc) + prefetch["tokens"],
            "cost_usd": self.cost_usd(self._cloud_model, rp, rc) + prefetch["cost_usd"],
            "turns": cfg.get("max_rounds", 3),
            "web_search_uses": prefetch["n_searches"],
            # GAIA: only countable tool surface is the prefetch web_search.
            # The Minions protocol itself is supervisor↔worker text, no tools.
            "tool_calls": int(prefetch["n_searches"]),
            "traces": {
                "mode": mode,
                "supervisor_messages": out.get("supervisor_messages"),
                "worker_messages": out.get("worker_messages"),
                "timing": out.get("timing"),
                "log_file": out.get("log_file"),
                "prefetch": {
                    "n_searches": prefetch["n_searches"],
                    "tokens": prefetch["tokens"],
                    "cost_usd": prefetch["cost_usd"],
                    "chars": len(prefetch["text"]),
                    "error": prefetch.get("error"),
                },
            },
        }
        return out.get("final_answer", ""), meta


    # ------------------------------------------------------------------
    # SWE-bench variant
    # ------------------------------------------------------------------

    def _run_swe(
        self,
        input: str,
        task: Dict[str, Any],
        cfg: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:
        if not self._local_endpoint or not self._local_model:
            raise ValueError(
                "MinionsAgent (swe mode) still needs local_model + local_endpoint"
            )
        # 1. Cloud supervisor writes a high-level plan (no tools).
        plan_text, p_in, p_out = self._call_cloud(
            user=(
                f"Issue:\n{task.get('problem_statement','')}\n\n"
                f"Repo: {task.get('repo','')}\n"
                f"Base commit: {task.get('base_commit','')}\n\n"
                f"{task.get('hints_text','')}"
            ),
            system=MINIONS_SWE_PLANNER_SYS,
            max_tokens=int(cfg.get("supervisor_max_tokens", 1024)),
            temperature=0.0,
        )
        self.record_trace_event({
            "kind": "minions_swe_plan",
            "plan": plan_text,
            "tokens_in": p_in,
            "tokens_out": p_out,
        })
        supervisor_cost = self.cost_usd(self._cloud_model, p_in, p_out)

        # 2. Local worker runs mini-SWE-agent with the plan as context.
        worker_prompt = (
            f"{input}\n\n"
            f"-----\n"
            f"A cloud supervisor reviewed this issue and wrote a fix plan "
            f"for you. Use it as guidance, but verify everything with the "
            f"actual code via your bash tool:\n\n{plan_text}"
        )
        out = run_swe_agent_loop(
            task,
            backbone="local",
            backbone_model=self._local_model,
            local_endpoint=self._local_endpoint,
            initial_prompt=worker_prompt,
            max_turns=int(cfg.get("swe_max_turns", 30)),
            bash_timeout=int(cfg.get("swe_bash_timeout_s", 120)),
            output_cap=int(cfg.get("swe_output_cap", 10_000)),
            turn_max_tokens=int(cfg.get("swe_turn_max_tokens", 4096)),
            trace_prefix="minions_worker",
        )

        meta = {
            "tokens_local": out["tokens_in"] + out["tokens_out"],
            "tokens_cloud": p_in + p_out,
            "cost_usd": supervisor_cost,
            "turns": 1 + out["turns"],
            # SWE: only the worker invokes tools (bash); supervisor is text-only.
            "tool_calls": int(out["turns"]),
            "traces": {
                "swe_mode": True,
                "supervisor_plan": plan_text,
                "worker_final_summary": out["final_summary"],
                "worker_patch_chars": len(out["patch"]),
                "max_turns_hit": out["max_turns_hit"],
            },
        }
        return out["answer"], meta


__all__ = ["MinionsAgent"]
