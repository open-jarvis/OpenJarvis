"""Data-driven registration of OpenAI-compatible inference engines."""

from openjarvis.core.registry import EngineRegistry
from openjarvis.engine._openai_compat import _OpenAICompatibleEngine

_ENGINES = {
    "vllm": ("VLLMEngine", "http://localhost:8000"),
    "sglang": ("SGLangEngine", "http://localhost:30000"),
    "llamacpp": ("LlamaCppEngine", "http://localhost:8080"),
    "mlx": ("MLXEngine", "http://localhost:8080"),
    "lmstudio": ("LMStudioEngine", "http://localhost:1234"),
}

for _key, (_cls_name, _default_host) in _ENGINES.items():
    _cls = type(
        _cls_name,
        (_OpenAICompatibleEngine,),
        {"engine_id": _key, "_default_host": _default_host},
    )
    EngineRegistry.register(_key)(_cls)
    globals()[_cls_name] = _cls

__all__ = [name for name, _ in _ENGINES.values()]
