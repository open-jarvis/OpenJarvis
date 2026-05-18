"""ArchonAgent — port of ScalingIntelligence/Archon.

Inference-time architecture search: layered (generator → ranker → fuser)
sampling where a generator proposes K candidates, a ranker scores them,
and a fuser synthesizes a final answer. Paper: arXiv:2409.15254.

How the hybrid harness wires it (and what we mirror here):

- **Local proposers** (generator layer): K samples from vLLM via an
  OpenAI-compatible client at ``local_endpoint``. Injected as a custom
  ``vllm_local`` model_type into Archon's ``GENERATE_MAP`` — that's the
  only way Ranker/Fuser can pick up custom backends (they re-instantiate
  Generator without ``custom_generators``).
- **Cloud ranker + fuser**: Archon's built-in ``OpenAI_API`` /
  ``Anthropic_API``. Patched at import time to strip ``temperature`` for
  Opus 4.7+ and to tally token usage (Archon ignores ``usage`` by default).

``cfg`` knobs:

- ``n_samples`` (int, default 5) — K proposers
- ``architecture`` (str, default ``"ensemble_rank_fuse"``)

  - ``"ensemble_rank_fuse"`` → [K local generators, 1 cloud ranker, 1 cloud fuser]
  - ``"single_local"``       → [1 local generator] (debug)

- ``ranker_model`` / ``fuser_model`` (default: ``cloud_model`` for both)
- ``max_tokens`` (default 2048), ``temperature`` (default 0.7)

Requires the Archon library (cloned at
``hybrid-local-cloud-compute/external/Archon`` — add its ``src`` to
``PYTHONPATH`` or pip-install editable). Import is lazy.

Ported from ``hybrid-local-cloud-compute/adapters/archon_adapter.py``.
"""

from __future__ import annotations

import os
import sys
import threading
import types
from typing import Any, Dict, List, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import LocalCloudAgent, _record_event
from openjarvis.agents.hybrid._prices import (
    NO_TEMP_PREFIXES,
)
from openjarvis.agents.hybrid._prices import (
    cost as _cost_cloud,
)
from openjarvis.agents.hybrid.mini_swe_agent import run_swe_agent_loop
from openjarvis.core.registry import AgentRegistry

ARCHON_SWE_RANKER_SYS = (
    "You are ranking K candidate patches for a SWE-bench bug. For each "
    "candidate, you'll see the candidate's summary text and the unified "
    "diff. Pick the index (0-based) of the candidate most likely to "
    "actually fix the issue. Prefer minimal, targeted patches; reject "
    "candidates with no patch or with patches that touch unrelated files. "
    "Respond with a single integer on its own line — the index — "
    "followed by a one-line justification."
)


# ---------- Stubs for Archon's eager-imported heavy deps we don't need ----------

def _stub_archon_imports() -> None:
    """``utils.py`` imports groq/google/litellm/dotenv at module load. Stub
    the ones we don't use so the import chain doesn't fail when those
    libraries aren't installed in the OpenJarvis venv."""
    for name in ("groq", "google", "google.generativeai", "litellm"):
        if name in sys.modules:
            continue
        sys.modules[name] = types.ModuleType(name)
    sys.modules["groq"].Groq = type("Groq", (), {})  # type: ignore[attr-defined]
    sys.modules["litellm"].completion = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["google.generativeai"] = types.ModuleType("google.generativeai")


def _add_archon_to_path() -> None:
    """Locate Archon's ``src`` dir. The hybrid clone is the default location;
    override with ``ARCHON_SRC`` env var if Archon is installed elsewhere."""
    archon_src = os.environ.get(
        "ARCHON_SRC",
        "/matx/u/aspark/hybrid-local-cloud-compute/external/Archon/src",
    )
    if archon_src not in sys.path and os.path.isdir(archon_src):
        sys.path.insert(0, archon_src)


# ---------- Anthropic patch for Opus 4.7 ----------

def _patch_anthropic_for_opus() -> None:
    from anthropic.resources.messages import messages as _msgs_mod

    cls = _msgs_mod.Messages
    if getattr(cls.create, "_hybrid_archon_patched", False):
        return
    orig = cls.create

    def patched(self, **kwargs):  # type: ignore[no-untyped-def]
        if str(kwargs.get("model", "")).startswith(NO_TEMP_PREFIXES):
            kwargs.pop("temperature", None)
        return orig(self, **kwargs)

    patched._hybrid_archon_patched = True  # type: ignore[attr-defined]
    cls.create = patched  # type: ignore[assignment]


# ---------- Per-run token tally + custom generators ----------

# Token tallies live in thread-local storage because the runner reuses one
# ArchonAgent across a ``ThreadPoolExecutor`` (``concurrency > 1``). A plain
# module-global dict would let concurrent ``_run_paradigm`` calls reset and
# read each other's counters, producing wrong ``cost_usd`` and
# ``tokens_local`` / ``tokens_cloud`` in per-task ``meta``.
_TALLY_LOCAL = threading.local()


def _tally() -> Dict[str, int]:
    """Return the calling thread's token tally, creating it on first touch."""
    counts = getattr(_TALLY_LOCAL, "counts", None)
    if counts is None:
        counts = {
            "cloud_prompt": 0, "cloud_completion": 0,
            "local_prompt": 0, "local_completion": 0,
        }
        _TALLY_LOCAL.counts = counts
    return counts


def _reset_tally() -> None:
    _TALLY_LOCAL.counts = {
        "cloud_prompt": 0, "cloud_completion": 0,
        "local_prompt": 0, "local_completion": 0,
    }


def _make_local_generator(local_endpoint: str, local_model: str):
    """Archon custom-generator signature: (model, messages, max_tokens, temperature) -> str."""
    from openai import OpenAI

    client = OpenAI(base_url=local_endpoint, api_key="EMPTY")

    def local_gen(model, messages, max_tokens=2048, temperature=0.7, **_kw):  # type: ignore[no-untyped-def]
        import time as _time
        t0 = _time.time()
        try:
            resp = client.chat.completions.create(
                model=local_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            _record_event({
                "kind": "archon_local_gen_error",
                "model": local_model,
                "messages": messages,
                "error": f"{type(e).__name__}: {e}",
                "ts": _time.time(),
            })
            return f"[local-vllm error: {e!r}]"
        u = resp.usage
        if u:
            _tally()["local_prompt"] += getattr(u, "prompt_tokens", 0) or 0
            _tally()["local_completion"] += getattr(u, "completion_tokens", 0) or 0
        text = (resp.choices[0].message.content or "").strip()
        _record_event({
            "kind": "archon_local_gen",
            "model": local_model,
            "messages": messages,
            "response": text,
            "tokens_in": getattr(u, "prompt_tokens", 0) if u else 0,
            "tokens_out": getattr(u, "completion_tokens", 0) if u else 0,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "latency_s": _time.time() - t0,
            "ts": _time.time(),
        })
        return text

    return local_gen


def _wrap_archon_cloud_generators() -> None:
    """Replace Archon's GENERATE_MAP entries for OpenAI_API / Anthropic_API
    with token-tallying wrappers. GENERATE_MAP holds function references;
    we update them in place so Ranker/Fuser see the wrapped versions."""
    import anthropic as _anth
    from openai import OpenAI as _OAI

    def gen_openai(model, messages, max_tokens=2048, temperature=0.7, **_kw):  # type: ignore[no-untyped-def]
        import time as _time
        client = _OAI()
        kwargs: Dict[str, Any] = dict(
            model=model, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        # GPT-5/o1/o3 reject non-default temperature and use max_completion_tokens.
        if model.startswith(("gpt-5", "o1", "o3")):
            kwargs.pop("temperature", None)
            kwargs.pop("max_tokens", None)
            kwargs["max_completion_tokens"] = max_tokens
        t0 = _time.time()
        resp = client.chat.completions.create(**kwargs)
        u = resp.usage
        if u:
            _tally()["cloud_prompt"] += getattr(u, "prompt_tokens", 0) or 0
            _tally()["cloud_completion"] += getattr(u, "completion_tokens", 0) or 0
        text = (resp.choices[0].message.content or "").strip()
        _record_event({
            "kind": "archon_cloud_openai",
            "model": model,
            "messages": messages,
            "response": text,
            "tokens_in": getattr(u, "prompt_tokens", 0) if u else 0,
            "tokens_out": getattr(u, "completion_tokens", 0) if u else 0,
            "latency_s": _time.time() - t0,
            "ts": _time.time(),
        })
        return text

    def gen_anthropic(model, messages, max_tokens=2048, temperature=0.7, **_kw):  # type: ignore[no-untyped-def]
        import time as _time
        client = _anth.Anthropic(timeout=600.0)
        system = ""
        msgs = []
        for m in messages:
            if m["role"] == "system" and not system:
                system = m["content"]
            else:
                msgs.append(m)
        kwargs: Dict[str, Any] = dict(
            model=model, system=system, messages=msgs, max_tokens=max_tokens,
        )
        if not model.startswith(NO_TEMP_PREFIXES):
            kwargs["temperature"] = temperature
        t0 = _time.time()
        resp = client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        u = resp.usage
        if u:
            _tally()["cloud_prompt"] += getattr(u, "input_tokens", 0) or 0
            _tally()["cloud_completion"] += getattr(u, "output_tokens", 0) or 0
        _record_event({
            "kind": "archon_cloud_anthropic",
            "model": model,
            "system": system,
            "messages": msgs,
            "response": text.strip(),
            "tokens_in": getattr(u, "input_tokens", 0) if u else 0,
            "tokens_out": getattr(u, "output_tokens", 0) if u else 0,
            "latency_s": _time.time() - t0,
            "ts": _time.time(),
        })
        return text.strip()

    from archon.completions.components.Generator import (
        GENERATE_MAP as _GMAP,  # type: ignore[import-not-found]
    )
    _GMAP["OpenAI_API"] = gen_openai
    _GMAP["Anthropic_API"] = gen_anthropic


_FUSER_FORMAT_REMINDER = (
    "\n\nIMPORTANT — output format: your synthesized response MUST honor the "
    "output-format requirements stated in the original user query above. "
    "If the query requires ending with `FINAL ANSWER: <answer>` (GAIA), end "
    "with exactly that one line and nothing after it. If the query requires "
    "a unified diff inside a ```diff … ``` fence (SWE-bench), end with that "
    "fence and nothing after the closing ```. Do not produce free-form "
    "analysis, markdown headers, or commentary that breaks the required "
    "format — the candidate responses may have done so, but your fused "
    "answer must not."
)


def _patch_archon_prompts() -> None:
    """Make Archon's fuser bench-aware.

    ``Fuser.py`` drops the system message we hand to ``archon.generate()`` and
    builds its own user message via ``make_fuser_prompt``. That template tells
    the fuser to "synthesize into a refined, well-structured response" with
    no reminder of the format the user originally asked for, so on SWE-bench
    Opus drifts to a markdown bug report and scores 0. We append an explicit
    format-honor reminder to the fuser prompt."""
    from archon.completions.components import (
        prompts as _p,  # type: ignore[import-not-found]
    )

    if getattr(_p.make_fuser_prompt, "_hybrid_format_patched", False):
        return
    orig = _p.make_fuser_prompt

    def patched(conv, references, critiques=None, length_control=False):  # type: ignore[no-untyped-def]
        base = orig(conv, references, critiques=critiques, length_control=length_control)
        return base + _FUSER_FORMAT_REMINDER

    patched._hybrid_format_patched = True  # type: ignore[attr-defined]
    _p.make_fuser_prompt = patched
    # Fuser imports the symbol by name at class-body time — rebind there too.
    from archon.completions.components import (
        Fuser as _F,  # type: ignore[import-not-found]
    )
    _F.make_fuser_prompt = patched


_PATCHES_APPLIED = False


def _apply_patches_once() -> None:
    global _PATCHES_APPLIED
    if _PATCHES_APPLIED:
        return
    _stub_archon_imports()
    _add_archon_to_path()
    _patch_anthropic_for_opus()
    # Trigger Archon imports so GENERATE_MAP exists.
    import archon.completions.components.Generator  # type: ignore[import-not-found]  # noqa: F401
    _wrap_archon_cloud_generators()
    _patch_archon_prompts()
    _PATCHES_APPLIED = True


# ---------- Architecture presets ----------

def _presets():
    return {
        "ensemble_rank_fuse": lambda K, local_model, ranker_model, fuser_model, max_tokens, temperature: [
            [{
                "type": "generator",
                "model": local_model,
                "model_type": "vllm_local",
                "top_k": 1,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "samples": K,
            }],
            [{
                "type": "ranker",
                "model": ranker_model,
                "model_type": "Anthropic_API" if ranker_model.startswith("claude") else "OpenAI_API",
                "top_k": min(K, 5),
                "temperature": 0.0,
                "max_tokens": max_tokens,
            }],
            [{
                "type": "fuser",
                "model": fuser_model,
                "model_type": "Anthropic_API" if fuser_model.startswith("claude") else "OpenAI_API",
                "temperature": 0.0,
                "max_tokens": max_tokens,
                "samples": 1,
            }],
        ],
        "single_local": lambda K, local_model, *_a, **_kw: [
            [{
                "type": "generator",
                "model": local_model,
                "model_type": "vllm_local",
                "top_k": 1,
                "temperature": 0.0,
                "max_tokens": 2048,
                "samples": 1,
            }],
        ],
    }


@AgentRegistry.register("archon")
class ArchonAgent(LocalCloudAgent):
    """Layered (generator → ranker → fuser) inference-time search."""

    agent_id = "archon"

    def _run_paradigm(
        self,
        input: str,
        context: Optional[AgentContext],
        **kwargs: Any,
    ) -> Tuple[str, Dict[str, Any]]:
        if "OPENAI_API_KEY" not in os.environ and "ANTHROPIC_API_KEY" not in os.environ:
            raise RuntimeError("Archon needs OPENAI_API_KEY and/or ANTHROPIC_API_KEY")

        cfg = self._cfg
        task_meta = (context.metadata.get("task") if context is not None else {}) or {}
        swe_mode = (
            bool(cfg.get("swe_use_agent_loop"))
            and bool(task_meta.get("problem_statement"))
            and bool(task_meta.get("repo"))
            and bool(task_meta.get("base_commit"))
        )
        if swe_mode:
            return self._run_swe(input, task_meta, cfg)

        _apply_patches_once()
        from archon.completions import Archon  # type: ignore[import-not-found]
        from archon.completions.components.Generator import (
            GENERATE_MAP as _GMAP,  # type: ignore[import-not-found]
        )

        arch = cfg.get("architecture", "ensemble_rank_fuse")
        presets = _presets()
        if arch not in presets:
            raise ValueError(
                f"unknown archon architecture {arch!r}, choose from {sorted(presets)}"
            )
        if not self._local_endpoint or not self._local_model:
            raise ValueError(
                "ArchonAgent needs local_model + local_endpoint; got "
                f"model={self._local_model!r} endpoint={self._local_endpoint!r}"
            )

        K = int(cfg.get("n_samples", 5))
        max_tokens = int(cfg.get("max_tokens", 2048))
        temperature = float(cfg.get("temperature", 0.7))
        ranker_model = cfg.get("ranker_model", self._cloud_model)
        fuser_model = cfg.get("fuser_model", self._cloud_model)

        # Register our local-vLLM generator per-run (endpoint can vary per cell).
        _GMAP["vllm_local"] = _make_local_generator(
            self._local_endpoint, self._local_model
        )

        layers = presets[arch](
            K, self._local_model, ranker_model, fuser_model, max_tokens, temperature,
        )
        archon_cfg = {"name": f"hybrid-archon-{arch}", "layers": layers}

        _reset_tally()
        archon = Archon(archon_cfg)

        try:
            answer = archon.generate([
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": input},
            ])
        except Exception as e:
            answer = f"[archon error: {e!r}]"

        if isinstance(answer, list):
            answer = answer[-1] if answer else ""
        answer = str(answer)

        cp = _tally()["cloud_prompt"]
        cc = _tally()["cloud_completion"]
        cost = _cost_cloud(ranker_model, cp, cc)
        if fuser_model != ranker_model:
            # Conservative: charge both at the more expensive of the two.
            cost = max(cost, _cost_cloud(fuser_model, cp, cc))

        meta = {
            "tokens_local": _tally()["local_prompt"] + _tally()["local_completion"],
            "tokens_cloud": cp + cc,
            "cost_usd": cost,
            "turns": (K + 2) if arch == "ensemble_rank_fuse" else 1,
            "traces": {
                "architecture": arch,
                "n_samples":    K,
                "ranker_model": ranker_model,
                "fuser_model":  fuser_model,
                "local_model":  self._local_model,
                "tokens_breakdown": dict(_tally()),
            },
        }
        return answer, meta

    # ------------------------------------------------------------------
    # SWE-bench variant: K diverse mini-SWE-agent runs, cloud ranker picks
    # ------------------------------------------------------------------

    def _run_swe(
        self,
        input: str,
        task: Dict[str, Any],
        cfg: Dict[str, Any],
    ) -> Tuple[str, Dict[str, Any]]:
        if not self._local_endpoint or not self._local_model:
            raise ValueError(
                "ArchonAgent (swe mode) needs local_model + local_endpoint"
            )

        K = int(cfg.get("n_samples", 3))
        max_turns = int(cfg.get("swe_max_turns", 30))
        bash_timeout = int(cfg.get("swe_bash_timeout_s", 120))
        output_cap = int(cfg.get("swe_output_cap", 10_000))
        turn_max_tokens = int(cfg.get("swe_turn_max_tokens", 4096))

        # K independent runs, each on a FRESH workdir → K diverse patches.
        candidates: List[Dict[str, Any]] = []
        total_tokens_local = 0
        total_tokens_cloud = 0
        total_cost = 0.0
        for k in range(K):
            out = run_swe_agent_loop(
                task,
                backbone="local",
                backbone_model=self._local_model,
                local_endpoint=self._local_endpoint,
                initial_prompt=input,
                max_turns=max_turns,
                bash_timeout=bash_timeout,
                output_cap=output_cap,
                turn_max_tokens=turn_max_tokens,
                trace_prefix=f"archon_gen{k}",
            )
            candidates.append({
                "idx": k,
                "summary": out["final_summary"],
                "patch": out["patch"],
                "framed": out["answer"],
                "tokens_in": out["tokens_in"],
                "tokens_out": out["tokens_out"],
                "turns": out["turns"],
            })
            total_tokens_local += out["tokens_in"] + out["tokens_out"]
            self.record_trace_event({
                "kind": "archon_swe_candidate",
                "idx": k,
                "patch_chars": len(out["patch"]),
                "summary": out["final_summary"],
            })

        # Ranker: cloud picks the best candidate.
        ranker_user = (
            f"Issue:\n{task.get('problem_statement','')}\n\n"
            f"K = {K} candidate patches:\n\n"
            + "\n\n".join(
                f"=== Candidate {c['idx']} ===\nSummary: {c['summary']}\n"
                f"Patch (chars={len(c['patch'])}):\n```diff\n{c['patch']}```"
                for c in candidates
            )
        )
        ranker_text, r_in, r_out = self._call_cloud(
            user=ranker_user,
            system=ARCHON_SWE_RANKER_SYS,
            max_tokens=int(cfg.get("ranker_max_tokens", 1024)),
            temperature=0.0,
        )
        total_tokens_cloud += r_in + r_out
        total_cost += self.cost_usd(self._cloud_model, r_in, r_out)

        # Parse — first integer on its own line.
        chosen_idx = 0
        for line in ranker_text.splitlines():
            stripped = line.strip()
            if stripped.isdigit():
                chosen_idx = int(stripped)
                break
        if not (0 <= chosen_idx < K):
            chosen_idx = 0
        chosen = candidates[chosen_idx]

        self.record_trace_event({
            "kind": "archon_swe_rank",
            "chosen_idx": chosen_idx,
            "ranker_raw": ranker_text,
            "tokens_in": r_in,
            "tokens_out": r_out,
        })

        meta = {
            "tokens_local": total_tokens_local,
            "tokens_cloud": total_tokens_cloud,
            "cost_usd": total_cost,
            "turns": sum(c["turns"] for c in candidates) + 1,
            "traces": {
                "swe_mode": True,
                "K": K,
                "candidates": [
                    {"idx": c["idx"], "summary": c["summary"],
                     "patch_chars": len(c["patch"]), "turns": c["turns"]}
                    for c in candidates
                ],
                "chosen_idx": chosen_idx,
                "ranker_text": ranker_text,
            },
        }
        return chosen["framed"], meta


__all__ = ["ArchonAgent"]
