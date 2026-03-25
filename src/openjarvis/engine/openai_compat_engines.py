"""Data-driven registration of OpenAI-compatible inference engines."""

import json

from openjarvis.core.registry import EngineRegistry
from openjarvis.engine._openai_compat import _OpenAICompatibleEngine

# ── vLLM: explicit class because it needs a tool_call arguments fix ──────

@EngineRegistry.register("vllm")
class VLLMEngine(_OpenAICompatibleEngine):
    """vLLM inference engine.

    Overrides ``_fix_tool_call_arguments`` because vLLM uses strict
    Pydantic validation and requires ``function.arguments`` to be a
    JSON-encoded string, not a parsed dict.  The OpenAI API itself
    accepts both forms, so this fix is vLLM-specific for now.  If
    other engines show the same behaviour, move this into the base
    class ``_OpenAICompatibleEngine``.
    """

    engine_id = "vllm"
    _default_host = "http://localhost:8000"
    _api_prefix = "/v1"

    @staticmethod
    def _fix_tool_call_arguments(msg_dicts: list) -> list:
        """Serialize tool_call arguments from dict to JSON string.

        vLLM (via Pydantic) rejects ``arguments`` as a dict and
        requires a JSON-encoded string.  Other OpenAI-compatible
        servers may be more lenient.
        """
        for md in msg_dicts:
            for tc in md.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments")
                if isinstance(args, dict):
                    fn["arguments"] = json.dumps(args)
        return msg_dicts


# ── Remaining engines: data-driven registration ─────────────────────────

_ENGINES = {
    "sglang": ("SGLangEngine", "http://localhost:30000", "/v1"),
    "llamacpp": ("LlamaCppEngine", "http://localhost:8080", "/v1"),
    "mlx": ("MLXEngine", "http://localhost:8080", "/v1"),
    "lmstudio": ("LMStudioEngine", "http://localhost:1234", "/v1"),
    "exo": ("ExoEngine", "http://localhost:52415", "/v1"),
    "nexa": ("NexaEngine", "http://localhost:18181", "/v1"),
    "uzu": ("UzuEngine", "http://localhost:8000", ""),
    "apple_fm": ("AppleFmEngine", "http://localhost:8079", "/v1"),
}

for _key, (_cls_name, _default_host, _api_prefix) in _ENGINES.items():
    _cls = type(
        _cls_name,
        (_OpenAICompatibleEngine,),
        {"engine_id": _key, "_default_host": _default_host, "_api_prefix": _api_prefix},
    )
    EngineRegistry.register(_key)(_cls)
    globals()[_cls_name] = _cls

__all__ = ["VLLMEngine"] + [name for name, _, _ in _ENGINES.values()]
