"""Multi-engine wrapper — routes requests to the right backend by model name."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any, Dict, List

from openjarvis.engine._base import InferenceEngine

logger = logging.getLogger(__name__)


class MultiEngine(InferenceEngine):
    """Wraps multiple engines and routes by model name.

    Models from each engine are discovered via ``list_models()``.
    When ``generate()`` or ``stream()`` is called, the model name
    is looked up to find which engine owns it.
    """

    engine_id = "multi"

    def __init__(self, engines: list[tuple[str, InferenceEngine]]) -> None:
        self._engines = engines
        self._model_map: Dict[str, InferenceEngine] = {}
        self._refresh_map()

    def _refresh_map(self) -> None:
        self._model_map.clear()
        for _key, engine in self._engines:
            try:
                for model_id in engine.list_models():
                    self._model_map[model_id] = engine
            except Exception as exc:
                logger.debug("Failed to list models for %s: %s", _key, exc)

    def _engine_for(self, model: str) -> InferenceEngine:
        """Find the engine that owns a model, refreshing the map once if needed."""
        engine = self._model_map.get(model)
        if engine is not None:
            return engine
        # Refresh and retry (a new model may have been pulled)
        self._refresh_map()
        engine = self._model_map.get(model)
        if engine is not None:
            return engine
        # Fall back to the first engine (usually Ollama)
        return self._engines[0][1]

    def generate(
        self,
        messages: Sequence[Any],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return self._engine_for(model).generate(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, **kwargs,
        )

    async def stream(
        self,
        messages: Sequence[Any],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        async for token in self._engine_for(model).stream(
            messages, model=model, temperature=temperature,
            max_tokens=max_tokens, **kwargs,
        ):
            yield token

    def list_models(self) -> List[str]:
        self._refresh_map()
        return list(self._model_map.keys())

    def health(self) -> bool:
        return any(engine.health() for _key, engine in self._engines)

    def close(self) -> None:
        for _key, engine in self._engines:
            engine.close()


__all__ = ["MultiEngine"]
