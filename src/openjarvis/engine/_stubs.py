"""ABC for inference engine backends.

Adapted from IPW's ``InferenceClient`` at ``src/ipw/clients/base.py``.
Phase 1 will provide concrete implementations (vLLM, Ollama, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from openjarvis.core.types import Message


@dataclass(slots=True)
class StreamChunk:
    """A single chunk from a streaming LLM response.

    Used by ``stream_full()`` to yield rich streaming data including
    semantically separate private reasoning, tool_calls fragments, and
    finish_reason, unlike ``stream()`` which only yields plain content strings.

    ``content_blocks`` and ``tool_results`` are aggregate fields emitted
    once at end-of-stream so streaming callers reach parity with the
    non-streaming ``generate()`` return shape.
    """

    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    finish_reason: Optional[str] = None
    usage: Optional[Dict[str, Any]] = None
    content_blocks: Optional[List[Dict[str, Any]]] = None
    tool_results: Optional[List[Dict[str, Any]]] = None
    reasoning_content: Optional[str] = None


@dataclass(slots=True)
class ResponseFormat:
    """Structured output configuration for inference engines.

    Attributes:
        type: The response format type. ``"json_object"`` enables JSON mode
            (the model returns valid JSON). ``"json_schema"`` enables structured
            output constrained to a specific JSON Schema.
        schema: A JSON Schema dict used when *type* is ``"json_schema"``.
            Ignored for ``"json_object"`` mode.
    """

    type: str = "json_object"
    schema: Optional[Dict[str, Any]] = field(default=None)


class InferenceEngine(ABC):
    """Base class for all inference engine backends.

    Subclasses must be registered via
    ``@EngineRegistry.register("name")`` to become discoverable.
    """

    engine_id: str
    is_cloud: bool = False

    @abstractmethod
    def generate(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Synchronous completion — returns a dict with ``content`` and ``usage``."""

    @abstractmethod
    async def stream(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Yield token strings as they are generated."""
        # NOTE: must contain a yield to satisfy the type checker
        yield ""  # pragma: no cover

    async def stream_full(
        self,
        messages: Sequence[Message],
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AsyncIterator["StreamChunk"]:
        """Yield full StreamChunks including tool_calls and finish_reason.

        Default implementation wraps ``stream()`` for backward compatibility.
        Engines with native tool-call streaming should override this.
        """
        async for token in self.stream(
            messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        ):
            yield StreamChunk(content=token)
        yield StreamChunk(finish_reason="stop")

    @abstractmethod
    def list_models(self) -> List[str]:
        """Return identifiers of models available on this engine."""

    @abstractmethod
    def health(self) -> bool:
        """Return ``True`` when the engine is reachable and healthy."""

    def can_serve(self, model: str) -> bool:
        """Return ``True`` if this engine can serve *model*.

        Defaults to ``True``: local engines accept any model id (whether a
        specific model is *installed* is a separate concern from engine
        selection). Engines that multiplex provider-specific clients (e.g.
        the cloud engine) override this so selection can skip an engine whose
        client for the model's provider isn't configured (see #532).
        """
        return True

    def supports_semantic_reasoning_stream(self, model: str) -> bool:
        """Whether streamed visible content is separate from private reasoning."""
        del model
        return False

    def close(self) -> None:
        """Release resources (HTTP clients, connections, threads, etc.)."""

    def prepare(self, model: str) -> None:
        """Optional warm-up hook called before the first request."""


def merge_tool_call_fragments(
    accumulated: Dict[int, Dict[str, Any]],
    fragments: List[Dict[str, Any]],
) -> None:
    """Merge streamed tool-call fragments into accumulated calls, in place.

    Engines disagree on how a tool call arrives. OpenAI-compatible APIs split
    one call across many fragments keyed by ``index``, each carrying a slice of
    the name and of the JSON arguments, so the slices must be concatenated.
    Ollama sends one complete fragment per call, and some engines put ``name``
    and ``arguments`` at the top level instead of under ``function``.

    Both shapes accumulate into the OpenAI wire form, which is the superset:
    ``{"id", "type", "function": {"name", "arguments"}}``.

    Fragments with no ``index`` fall back to their position in the batch, not
    to ``0`` — sharing a key would merge two distinct calls into one corrupt
    call whose arguments are the concatenation of both.
    """
    for position, fragment in enumerate(fragments):
        index = int(fragment.get("index", position))
        entry = accumulated.setdefault(
            index,
            {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        if fragment.get("id"):
            entry["id"] = fragment["id"]
        function = fragment.get("function")
        if not isinstance(function, dict):
            function = fragment
        entry["function"]["name"] += function.get("name", "") or ""
        entry["function"]["arguments"] += function.get("arguments", "") or ""


__all__ = [
    "InferenceEngine",
    "ResponseFormat",
    "StreamChunk",
    "merge_tool_call_fragments",
]
