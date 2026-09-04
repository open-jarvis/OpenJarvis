"""Engine discovery — probe running engines and aggregate available models."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from openjarvis.core.config import JarvisConfig
from openjarvis.core.registry import EngineRegistry
from openjarvis.engine._base import InferenceEngine

logger = logging.getLogger(__name__)

# Map registry keys to config host attribute (None = no host arg)
_HOST_MAP: Dict[str, str | None] = {
    "ollama": "ollama_host",
    "vllm": "vllm_host",
    "llamacpp": "llamacpp_host",
    "sglang": "sglang_host",
    "mlx": "mlx_host",
    "lmstudio": "lmstudio_host",
    "exo": "exo_host",
    "nexa": "nexa_host",
    "uzu": "uzu_host",
    "apple_fm": "apple_fm_host",
    "lemonade": "lemonade_host",
    "cloud": None,
    "litellm": None,
    "gemma_cpp": None,
    # In-process: drives the Apple FM SDK directly, so there is no host.
    "afm": None,
}


def _make_engine(key: str, config: JarvisConfig) -> InferenceEngine:
    """Instantiate a registered engine with the appropriate config host."""
    cls = EngineRegistry.get(key)

    # LiteLLM cannot enumerate every model supported by every provider.  Its
    # list_models() contract therefore advertises the configured default
    # model, which must be supplied when discovery constructs the engine.
    if key == "litellm":
        return cls(default_model=config.intelligence.default_model or None)

    # gemma_cpp: pass config fields instead of host
    if key == "gemma_cpp":
        cfg = config.engine.gemma_cpp
        return cls(
            model_path=cfg.model_path or None,
            tokenizer_path=cfg.tokenizer_path or None,
            model_type=cfg.model_type or None,
            num_threads=cfg.num_threads,
        )

    # afm: in-process engine, configured by behaviour rather than a host
    if key == "afm":
        cfg = config.engine.afm
        return cls(
            instructions=cfg.instructions,
            use_case=cfg.use_case,
            guardrails=cfg.guardrails,
            sampling=cfg.sampling,
        )

    host_attr = _HOST_MAP.get(key)
    if host_attr is not None:
        host = getattr(config.engine, host_attr, None)
        if host:
            return cls(host=host)
    return cls()


def _maybe_register_mining_sidecar_engine() -> None:
    """If a mining sidecar exists with a ``vllm_endpoint``, register a derived
    vLLM engine class pointing at it.  Idempotent.  Quiet on error.

    The trigger is the *shape* of the sidecar (presence of ``vllm_endpoint``),
    not the value of its ``provider`` field — this leaves room for future
    non-engine-replacing providers (e.g., a hypothetical cpu-pearl) whose
    sidecars don't include ``vllm_endpoint``.
    """
    try:
        from openjarvis.mining import Sidecar
        from openjarvis.mining._constants import SIDECAR_PATH
    except ImportError:
        return

    if EngineRegistry.contains("vllm-pearl-mining"):
        return  # idempotent

    payload = Sidecar.read(SIDECAR_PATH)
    if payload is None:
        return

    endpoint = payload.get("vllm_endpoint")
    model = payload.get("model")
    if not endpoint or not model:
        return  # data-driven gate: no vllm_endpoint → don't register

    from openjarvis.engine._openai_compat import _OpenAICompatibleEngine

    # Strip a trailing "/v1" path segment so _default_host is the bare
    # base URL and _api_prefix="/v1" combines correctly in request paths.
    api_prefix = "/v1"
    base_url = endpoint.rstrip("/")
    if base_url.endswith(api_prefix):
        base_url = base_url[: -len(api_prefix)]

    _cls = type(
        "VllmPearlMiningEngine",
        (_OpenAICompatibleEngine,),
        {
            "engine_id": "vllm-pearl-mining",
            "_default_host": base_url,
            "_api_prefix": api_prefix,
        },
    )
    EngineRegistry.register_value("vllm-pearl-mining", _cls)


def discover_engines(config: JarvisConfig) -> List[Tuple[str, InferenceEngine]]:
    """Probe registered engines and return ``[(key, instance)]`` for healthy ones.

    Results are sorted with the config default engine first.
    """
    _maybe_register_mining_sidecar_engine()

    # Probe engines concurrently: each health() does a blocking network
    # check with its own timeout, so a serial loop costs the SUM of all
    # probe timeouts (dead localhost ports especially). Running them in
    # threads collapses that to roughly the slowest single probe. The
    # healthy.sort() below normalizes order, so completion order is
    # irrelevant and the result is identical to the serial version (#263).
    keys = list(EngineRegistry.keys())

    def _probe(key: str) -> Tuple[str, InferenceEngine] | None:
        try:
            engine = _make_engine(key, config)
            if engine.health():
                return (key, engine)
        except Exception as exc:
            logger.debug("Engine %r failed during discovery: %s", key, exc)
        return None

    healthy: List[Tuple[str, InferenceEngine]] = []
    if keys:
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            for result in pool.map(_probe, keys):
                if result is not None:
                    healthy.append(result)

    default_key = config.engine.default

    def sort_key(item: Tuple[str, Any]) -> Tuple[int, str]:
        return (0 if item[0] == default_key else 1, item[0])

    healthy.sort(key=sort_key)
    return healthy


def discover_models(
    engines: List[Tuple[str, InferenceEngine]],
) -> Dict[str, List[str]]:
    """Call ``list_models()`` on each engine and return a dict."""
    result: Dict[str, List[str]] = {}
    for key, engine in engines:
        try:
            result[key] = engine.list_models()
        except Exception as exc:
            logger.debug("Failed to list models for engine %r: %s", key, exc)
            result[key] = []
    return result


def get_engine(
    config: JarvisConfig,
    engine_key: str | None = None,
    model: str | None = None,
) -> Tuple[str, InferenceEngine] | None:
    """Get a specific engine by key, or the default with a named fallback.

    An explicit ``engine_key`` is authoritative and is never silently
    substituted. Default-engine fallback prefers the same local/cloud class
    and logs the selected replacement.

    When *model* is given, an engine is selected only if it can actually
    serve that model (``engine.can_serve(model)``). This stops the cloud
    fallback from being chosen — when the local engine is down — for a model
    whose provider client is missing, which otherwise surfaces as a confusing
    "OpenAI client not available" instead of a helpful "start your local
    engine" message (see #532). When *model* is ``None`` selection stays
    model-agnostic (unchanged behaviour).

    Returns ``(key, engine_instance)`` or ``None`` if no engine is available.
    """

    def _usable(engine: InferenceEngine) -> bool:
        return engine.health() and (model is None or engine.can_serve(model))

    if engine_key:
        if not EngineRegistry.contains(engine_key):
            logger.warning("Requested engine %r is not registered", engine_key)
            return None
        try:
            engine = _make_engine(engine_key, config)
            if _usable(engine):
                return (engine_key, engine)
        except Exception as exc:
            logger.debug("Engine %r health check failed: %s", engine_key, exc)
        logger.warning(
            "Requested engine %r is unavailable%s; no substitute was selected",
            engine_key,
            f" for model {model!r}" if model else "",
        )
        return None

    default_key = config.engine.default
    default_is_cloud: bool | None = None
    if default_key and EngineRegistry.contains(default_key):
        default_cls = EngineRegistry.get(default_key)
        default_is_cloud = bool(getattr(default_cls, "is_cloud", False))
        try:
            engine = _make_engine(default_key, config)
            default_is_cloud = bool(getattr(engine, "is_cloud", default_is_cloud))
            if _usable(engine):
                return (default_key, engine)
        except Exception as exc:
            logger.debug("Engine %r health check failed: %s", default_key, exc)

    candidates = [
        (key, engine)
        for key, engine in discover_engines(config)
        if key != default_key and (model is None or engine.can_serve(model))
    ]
    if not candidates:
        return None

    chosen: Tuple[str, InferenceEngine] | None = None
    if default_is_cloud is not None:
        chosen = next(
            (
                candidate
                for candidate in candidates
                if bool(getattr(candidate[1], "is_cloud", False)) == default_is_cloud
            ),
            None,
        )
    chosen = chosen or candidates[0]
    chosen_is_cloud = bool(getattr(chosen[1], "is_cloud", False))
    boundary = (
        " across the local/cloud boundary"
        if (default_is_cloud is not None and chosen_is_cloud != default_is_cloud)
        else ""
    )
    logger.warning(
        "Default engine %r is unavailable; using %r%s",
        default_key,
        chosen[0],
        boundary,
    )
    return chosen


__all__ = ["discover_engines", "discover_models", "get_engine"]
