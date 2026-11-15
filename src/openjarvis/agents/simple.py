"""SimpleAgent — single-turn query-to-response agent (no tool calling)."""

from __future__ import annotations

import asyncio
import queue
import threading
from typing import Any, AsyncIterator, Iterator, Optional

from openjarvis.agents._stubs import (
    _ALLOWED_ENGINE_OPTION_KEYS,
    AgentContext,
    AgentResult,
    BaseAgent,
)
from openjarvis.core.registry import AgentRegistry


def _iter_async(agen: AsyncIterator[str]) -> Iterator[str]:
    """Drive an async iterator from sync code, one item at a time.

    The async generator runs in its own thread with its own event loop
    and always drains to completion, so an abandoned consumer cannot
    strand the underlying HTTP stream mid-transfer.
    """
    done = object()
    items: queue.Queue = queue.Queue()

    def _runner() -> None:
        async def _consume() -> None:
            async for item in agen:
                items.put(item)

        try:
            asyncio.run(_consume())
        except BaseException as exc:  # propagated to the consumer below
            items.put(exc)
        finally:
            items.put(done)

    threading.Thread(target=_runner, daemon=True).start()
    while (item := items.get()) is not done:
        if isinstance(item, BaseException):
            raise item
        yield item


@AgentRegistry.register("simple")
class SimpleAgent(BaseAgent):
    """Single-turn agent: query -> model -> response.  No tool calling."""

    agent_id = "simple"
    supports_managed_tool_fallback = True

    def run(
        self,
        input: str,
        context: Optional[AgentContext] = None,
        **kwargs: Any,
    ) -> AgentResult:
        """Single-turn: build messages, call engine, return result."""
        self._emit_turn_start(input)

        messages = self._build_messages(input, context)
        result = self._generate(messages)
        content = result.get("content", "")

        self._emit_turn_end(content_length=len(content))

        return AgentResult(content=content, turns=1)

    def run_stream(
        self,
        input: str,
        context: Optional[AgentContext] = None,
    ) -> Iterator[str]:
        """Yield response text deltas from the engine's streaming API.

        Mirrors :meth:`run` (same messages and generation kwargs) but
        returns tokens as they are produced. Raises NotImplementedError
        when the engine has no ``stream`` method, so callers can fall
        back to :meth:`run`.
        """
        stream_method = getattr(self._engine, "stream", None)
        if stream_method is None:
            raise NotImplementedError(
                f"engine {getattr(self._engine, 'engine_id', '?')!r} "
                "does not support streaming"
            )

        self._emit_turn_start(input)
        messages = self._build_messages(input, context)
        gen_kwargs = {
            key: value
            for key, value in self._engine_options.items()
            if key in _ALLOWED_ENGINE_OPTION_KEYS
        }
        agen = stream_method(
            messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            **gen_kwargs,
        )

        def _deltas() -> Iterator[str]:
            total = 0
            for delta in _iter_async(agen):
                total += len(delta)
                yield delta
            self._emit_turn_end(content_length=total)

        return _deltas()


__all__ = ["SimpleAgent"]
