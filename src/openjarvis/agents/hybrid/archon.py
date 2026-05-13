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
import types
from typing import Any, Dict, Optional, Tuple

from openjarvis.agents._stubs import AgentContext
from openjarvis.agents.hybrid._base import LocalCloudAgent
from openjarvis.agents.hybrid._prices import NO_TEMP_PREFIXES, cost as _cost_cloud
from openjarvis.core.registry import AgentRegistry


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
    import anthropic
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

_TOKEN_TALLY = {
    "cloud_prompt": 0, "cloud_completion": 0,
    "local_prompt": 0, "local_completion": 0,
}


def _reset_tally() -> None:
    for k in _TOKEN_TALLY:
        _TOKEN_TALLY[k] = 0


def _make_local_generator(local_endpoint: str, local_model: str):
    """Archon custom-generator signature: (model, messages, max_tokens, temperature) -> str."""
    from openai import OpenAI

    client = OpenAI(base_url=local_endpoint, api_key="EMPTY")

    def local_gen(model, messages, max_tokens=2048, temperature=0.7, **_kw):  # type: ignore[no-untyped-def]
        try:
            resp = client.chat.completions.create(
                model=local_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            return f"[local-vllm error: {e!r}]"
        u = resp.usage
        if u:
            _TOKEN_TALLY["local_prompt"] += getattr(u, "prompt_tokens", 0) or 0
            _TOKEN_TALLY["local_completion"] += getattr(u, "completion_tokens", 0) or 0
        return (resp.choices[0].message.content or "").strip()

    return local_gen


def _wrap_archon_cloud_generators() -> None:
    """Replace Archon's GENERATE_MAP entries for OpenAI_API / Anthropic_API
    with token-tallying wrappers. GENERATE_MAP holds function references;
    we update them in place so Ranker/Fuser see the wrapped versions."""
    from openai import OpenAI as _OAI
    import anthropic as _anth

    def gen_openai(model, messages, max_tokens=2048, temperature=0.7, **_kw):  # type: ignore[no-untyped-def]
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
        resp = client.chat.completions.create(**kwargs)
        u = resp.usage
        if u:
            _TOKEN_TALLY["cloud_prompt"] += getattr(u, "prompt_tokens", 0) or 0
            _TOKEN_TALLY["cloud_completion"] += getattr(u, "completion_tokens", 0) or 0
        return (resp.choices[0].message.content or "").strip()

    def gen_anthropic(model, messages, max_tokens=2048, temperature=0.7, **_kw):  # type: ignore[no-untyped-def]
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
        resp = client.messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        u = resp.usage
        if u:
            _TOKEN_TALLY["cloud_prompt"] += getattr(u, "input_tokens", 0) or 0
            _TOKEN_TALLY["cloud_completion"] += getattr(u, "output_tokens", 0) or 0
        return text.strip()

    from archon.completions.components.Generator import GENERATE_MAP as _GMAP  # type: ignore[import-not-found]
    _GMAP["OpenAI_API"] = gen_openai
    _GMAP["Anthropic_API"] = gen_anthropic


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

        _apply_patches_once()
        from archon.completions import Archon  # type: ignore[import-not-found]
        from archon.completions.components.Generator import GENERATE_MAP as _GMAP  # type: ignore[import-not-found]

        cfg = self._cfg
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

        cp = _TOKEN_TALLY["cloud_prompt"]
        cc = _TOKEN_TALLY["cloud_completion"]
        cost = _cost_cloud(ranker_model, cp, cc)
        if fuser_model != ranker_model:
            # Conservative: charge both at the more expensive of the two.
            cost = max(cost, _cost_cloud(fuser_model, cp, cc))

        meta = {
            "tokens_local": _TOKEN_TALLY["local_prompt"] + _TOKEN_TALLY["local_completion"],
            "tokens_cloud": cp + cc,
            "cost_usd": cost,
            "turns": (K + 2) if arch == "ensemble_rank_fuse" else 1,
            "traces": {
                "architecture": arch,
                "n_samples":    K,
                "ranker_model": ranker_model,
                "fuser_model":  fuser_model,
                "local_model":  self._local_model,
                "tokens_breakdown": dict(_TOKEN_TALLY),
            },
        }
        return answer, meta


__all__ = ["ArchonAgent"]
