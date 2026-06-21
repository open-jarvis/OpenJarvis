from openjarvis.core.config import JarvisConfig
from openjarvis.server.research_router import _resolve_planner


def test_legacy_fallback_when_nothing_configured():
    cfg = JarvisConfig()
    cfg.engine.default = "ollama"
    cfg.intelligence.default_model = ""
    assert _resolve_planner(cfg) == ("ollama", "gemma4:31b")


def test_uses_configured_chat_engine_and_model():
    cfg = JarvisConfig()
    cfg.engine.default = "lmstudio"
    cfg.intelligence.default_model = "qwen3.5-9b-uncensored-hauhaucs-aggressive"
    assert _resolve_planner(cfg) == (
        "lmstudio",
        "qwen3.5-9b-uncensored-hauhaucs-aggressive",
    )


def test_explicit_override_wins():
    cfg = JarvisConfig()
    cfg.engine.default = "lmstudio"
    cfg.intelligence.default_model = "chat-model"
    cfg.deep_research.engine = "vllm"
    cfg.deep_research.model = "research-model"
    assert _resolve_planner(cfg) == ("vllm", "research-model")
