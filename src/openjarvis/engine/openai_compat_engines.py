"""Data-driven registration of OpenAI-compatible inference engines."""

from __future__ import annotations

import logging

from openjarvis.core.registry import EngineRegistry
from openjarvis.engine._openai_compat import _OpenAICompatibleEngine

logger = logging.getLogger(__name__)

_ENGINES = {
    "vllm": ("VLLMEngine", "http://localhost:8000", "/v1"),
    "sglang": ("SGLangEngine", "http://localhost:30000", "/v1"),
    "llamacpp": ("LlamaCppEngine", "http://localhost:8080", "/v1"),
    "mlx": ("MLXEngine", "http://localhost:8080", "/v1"),
    "lmstudio": ("LMStudioEngine", "http://localhost:1234", "/v1"),
    "exo": ("ExoEngine", "http://localhost:52415", "/v1"),
    "nexa": ("NexaEngine", "http://localhost:18181", "/v1"),
    "uzu": ("UzuEngine", "http://localhost:8000", ""),
    "apple_fm": ("AppleFmEngine", "http://localhost:8079", "/v1"),
    "lemonade": ("LemonadeEngine", "http://localhost:13305", "/v1"),
}

for _key, (_cls_name, _default_host, _api_prefix) in _ENGINES.items():
    _cls = type(
        _cls_name,
        (_OpenAICompatibleEngine,),
        {"engine_id": _key, "_default_host": _default_host, "_api_prefix": _api_prefix},
    )
    EngineRegistry.register(_key)(_cls)
    globals()[_cls_name] = _cls


@EngineRegistry.register("rapidmlx")
class RapidMLXEngine(_OpenAICompatibleEngine):
    """Rapid-MLX server, identified by its model ownership metadata."""

    engine_id = "rapidmlx"
    _default_host = "http://localhost:8000"
    _api_prefix = "/v1"

    def health(self) -> bool:
        try:
            resp = self._client.get(f"{self._api_prefix}/models", timeout=2.0)
            if resp.status_code != 200:
                return False
            data = resp.json()
            return isinstance(data, dict) and any(
                isinstance(model, dict) and model.get("owned_by") == "rapid-mlx"
                for model in data.get("data", [])
            )
        except Exception as exc:
            logger.debug(
                "%s health check failed at %s: %s",
                self.engine_id,
                self._host,
                exc,
            )
            return False


def normalize_openai_base_url(url: str) -> str:
    """Strip a single trailing ``/v1`` segment from a user-supplied base URL.

    Users habitually pass ``http://host:8000/v1`` (the full OpenAI-compatible
    prefix); the engine's ``_api_prefix`` re-appends ``/v1`` to every request
    path, so a trailing copy would double up as ``/v1/v1``. Only a literal
    trailing ``/v1`` is stripped — proxy/gateway path prefixes are preserved.
    """
    base = url.rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return base


class OpenAICompatEngine(_OpenAICompatibleEngine):
    """Generic engine for an explicitly-provided OpenAI-compatible endpoint.

    Deliberately NOT registered in ``EngineRegistry``: it is only ever
    constructed with an explicit host (e.g. ``jarvis eval --base-url``), so
    registering it would just add a useless localhost discovery probe and
    interact with the per-test registry wipe.
    """

    engine_id = "openai-compat"
    _api_prefix = "/v1"


__all__ = [name for name, _, _ in _ENGINES.values()] + [
    "RapidMLXEngine",
    "OpenAICompatEngine",
    "normalize_openai_base_url",
]
