"""Inference Engine primitive — LLM runtime management."""

from __future__ import annotations

import importlib
import logging

# Import engine modules to trigger @EngineRegistry.register() decorators
import openjarvis.engine.nim  # noqa: F401
import openjarvis.engine.ollama  # noqa: F401
import openjarvis.engine.openai_compat_engines  # noqa: F401
from openjarvis.engine._base import (
    EngineConnectionError,
    EngineContextLengthError,
    InferenceEngine,
    looks_like_context_length_error,
    messages_to_dicts,
)
from openjarvis.engine._discovery import discover_engines, discover_models, get_engine

logger = logging.getLogger(__name__)


def _register_optional_engines() -> None:
    """Register available optional engines and retain import diagnostics."""

    for optional in ("cloud", "litellm", "gemma_cpp"):
        try:
            importlib.import_module(f".{optional}", __name__)
        except ImportError as exc:
            logger.debug("Optional engine %r unavailable: %s", optional, exc)


# Optional engines — only register if their SDK deps are present
_register_optional_engines()

__all__ = [
    "EngineConnectionError",
    "EngineContextLengthError",
    "InferenceEngine",
    "discover_engines",
    "discover_models",
    "get_engine",
    "looks_like_context_length_error",
    "messages_to_dicts",
]
