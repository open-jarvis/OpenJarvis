"""Data-driven registration of OpenAI-compatible inference engines."""

from openjarvis.core.registry import EngineRegistry
from openjarvis.engine._openai_compat import _OpenAICompatibleEngine

_ENGINES = {
    "vllm": ("VLLMEngine", "http://127.0.0.1:8000", "/v1"),
    "sglang": ("SGLangEngine", "http://127.0.0.1:30000", "/v1"),
    "llamacpp": ("LlamaCppEngine", "http://127.0.0.1:8080", "/v1"),
    "mlx": ("MLXEngine", "http://127.0.0.1:8080", "/v1"),
    "lmstudio": ("LMStudioEngine", "http://127.0.0.1:1234", "/v1"),
    "exo": ("ExoEngine", "http://127.0.0.1:52415", "/v1"),
    "nexa": ("NexaEngine", "http://127.0.0.1:18181", "/v1"),
    "uzu": ("UzuEngine", "http://127.0.0.1:8000", ""),
    "apple_fm": ("AppleFmEngine", "http://127.0.0.1:8079", "/v1"),
    "lemonade": ("LemonadeEngine", "http://127.0.0.1:13305", "/v1"),
}

for _key, (_cls_name, _default_host, _api_prefix) in _ENGINES.items():
    _cls = type(
        _cls_name,
        (_OpenAICompatibleEngine,),
        {"engine_id": _key, "_default_host": _default_host, "_api_prefix": _api_prefix},
    )
    EngineRegistry.register(_key)(_cls)
    globals()[_cls_name] = _cls

__all__ = [name for name, _, _ in _ENGINES.values()]
