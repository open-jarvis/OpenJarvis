"""gemma.cpp inference engine backend via pygemma pybind11 bindings."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

from openjarvis.core.registry import EngineRegistry
from openjarvis.core.types import Message, Role
from openjarvis.engine._base import InferenceEngine, estimate_prompt_tokens

logger = logging.getLogger(__name__)


def _import_pygemma():
    """Import and return the pygemma.Gemma class. Raises ImportError if unavailable."""
    from pygemma import Gemma

    return Gemma


@EngineRegistry.register("gemma_cpp")
class GemmaCppEngine(InferenceEngine):
    """gemma.cpp backend via pygemma pybind11 bindings (in-process, CPU)."""

    engine_id = "gemma_cpp"

    def __init__(
        self,
        model_path: str | None = None,
        tokenizer_path: str | None = None,
        model_type: str | None = None,
        num_threads: int = 0,
    ) -> None:
        self._model_path = model_path or os.environ.get("GEMMA_CPP_MODEL_PATH", "")
        self._tokenizer_path = tokenizer_path or os.environ.get(
            "GEMMA_CPP_TOKENIZER_PATH", ""
        )
        self._model_type = model_type or os.environ.get("GEMMA_CPP_MODEL_TYPE", "")
        self._num_threads = num_threads or int(
            os.environ.get("GEMMA_CPP_NUM_THREADS", "0")
        )
        self._gemma: Any = None  # lazy-loaded pygemma.Gemma instance

    def _messages_to_prompt(self, messages: Sequence[Message]) -> str:
        """Format messages into Gemma's chat template."""
        parts: list[str] = []
        system_prefix = ""
        for msg in messages:
            if msg.role == Role.SYSTEM:
                system_prefix += msg.content + "\n\n"
            elif msg.role == Role.USER:
                content = system_prefix + msg.content if system_prefix else msg.content
                system_prefix = ""
                parts.append(f"<start_of_turn>user\n{content}<end_of_turn>\n")
            elif msg.role == Role.ASSISTANT:
                parts.append(f"<start_of_turn>model\n{msg.content}<end_of_turn>\n")
        parts.append("<start_of_turn>model\n")
        return "".join(parts)

    def _ensure_loaded(self) -> None:
        """Lazy model loading — called before inference."""
        if self._gemma is None:
            if not self._model_path:
                raise FileNotFoundError(
                    "gemma.cpp model_path not configured. Download weights "
                    "from Kaggle and set GEMMA_CPP_MODEL_PATH or configure "
                    "[engine.gemma_cpp] in ~/.openjarvis/config.toml"
                )
            if not self._tokenizer_path:
                raise FileNotFoundError(
                    "gemma.cpp tokenizer_path not configured. Set "
                    "GEMMA_CPP_TOKENIZER_PATH or configure "
                    "[engine.gemma_cpp] in ~/.openjarvis/config.toml"
                )
            Gemma = _import_pygemma()
            self._gemma = Gemma()
            self._gemma.load_model(
                self._tokenizer_path, self._model_path, self._model_type
            )

    def prepare(self, model: str) -> None:
        """Load model into memory."""
        self._ensure_loaded()

    def close(self) -> None:
        """Unload model and free memory."""
        self._gemma = None

    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        self._ensure_loaded()
        if model != self._model_type:
            logger.warning(
                "gemma_cpp: requested model %r but loaded model is %r; "
                "proceeding with loaded model",
                model,
                self._model_type,
            )
        prompt = self._messages_to_prompt(messages)
        try:
            # pygemma v0.1.3 completion() does not accept temperature/max_tokens;
            # these params are accepted in the signature for ABC compliance but
            # not forwarded until pygemma or a vendored wrapper supports them.
            raw = self._gemma.completion(prompt)
        except Exception as exc:
            raise RuntimeError(f"gemma.cpp inference failed: {exc}") from exc

        prompt_tokens = estimate_prompt_tokens(messages)
        completion_tokens = max(1, len(raw) // 4)
        return {
            "content": raw,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
            "model": self._model_type,
            "finish_reason": "stop",
        }

    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        self._ensure_loaded()
        if model != self._model_type:
            logger.warning(
                "gemma_cpp: requested model %r but loaded model is %r; "
                "proceeding with loaded model",
                model,
                self._model_type,
            )
        prompt = self._messages_to_prompt(messages)
        try:
            raw = self._gemma.completion(prompt)
        except Exception as exc:
            raise RuntimeError(f"gemma.cpp inference failed: {exc}") from exc
        yield raw

    def _paths_valid(self) -> bool:
        """Check that model and tokenizer paths are configured and exist."""
        return bool(
            self._model_path
            and self._tokenizer_path
            and os.path.isfile(self._model_path)
            and os.path.isfile(self._tokenizer_path)
        )

    def list_models(self) -> List[str]:
        if self._model_type and self._paths_valid():
            return [self._model_type]
        return []

    def health(self) -> bool:
        if not self._paths_valid():
            return False
        try:
            _import_pygemma()
            return True
        except ImportError:
            return False


__all__ = ["GemmaCppEngine"]
