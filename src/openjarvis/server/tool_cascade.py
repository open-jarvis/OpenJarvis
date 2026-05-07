"""Tool-capable mini-cascade — race tool-reliable models with `tools=` plumbed.

Why a parallel cascade
----------------------
The text-only :mod:`tier_cascade` carries plain strings through its queue
and does not forward ``tools=`` to providers. Reshaping it would touch
every existing caller. This module is a sibling implementation that
yields :class:`StreamChunk` (content + tool_calls + finish_reason) so
function-calling can stream end-to-end without disrupting the existing
plain-chat path.

Tier composition (env-overridable):
  TIER1_TOOL_PROVIDERS  — race fast tool-reliable models (3s deadline)
  TIER2_TOOL_PROVIDERS  — fallback tool-capable models   (5s deadline)
  TIER3_TOOL_PROVIDERS  — premium fallback              (no deadline)

Default lists deliberately exclude small llamas (groq/cerebras 8B,
sambanova llama-3.x) which cannot be relied on to call tools — they
hallucinate prose API documentation instead.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openjarvis.core.types import Message
from openjarvis.engine._stubs import StreamChunk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolTierSpec:
    name: str
    providers: tuple[str, ...]
    deadline_s: Optional[float]


def _split(env_name: str, default: str) -> tuple[str, ...]:
    raw = os.environ.get(env_name, default)
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def _float_env(env_name: str, default: float) -> float:
    try:
        return float(os.environ.get(env_name, str(default)))
    except ValueError:
        return default


# Mapping from cascade-member id to the env var that must be set for it
# to be reachable. Used to filter unreachable providers before racing —
# saves us from wasting a deadline on guaranteed-failure tasks.
_PROVIDER_KEY_ENVS: Dict[str, tuple[str, ...]] = {
    "claude-sonnet-4-6": ("ANTHROPIC_API_KEY",),
    "claude-opus-4-7": ("ANTHROPIC_API_KEY",),
    "claude-haiku-4-5": ("ANTHROPIC_API_KEY",),
    "deepseek-chat": ("DEEPSEEK_API_KEY",),
    "deepseek-reasoner": ("DEEPSEEK_API_KEY",),
    "gpt-4o": ("OPENAI_API_KEY",),
    "gpt-4o-mini": ("OPENAI_API_KEY",),
    "gpt-5": ("OPENAI_API_KEY",),
    "gemini-2.5-flash": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "gemini-2.5-pro": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}


def _provider_reachable(model: str) -> bool:
    """Best-effort check that the model's API key is in the environment."""
    envs = _PROVIDER_KEY_ENVS.get(model)
    if not envs:
        # Unknown provider id — let it through; the race will surface the error
        return True
    return any(os.environ.get(e) for e in envs)


def load_tool_tiers() -> tuple[ToolTierSpec, ...]:
    """Load tool-capable tiers, refreshed at call time so env edits land live."""
    return (
        ToolTierSpec(
            name="TT1",
            providers=_split(
                "TIER1_TOOL_PROVIDERS",
                "claude-sonnet-4-6,deepseek-chat",
            ),
            deadline_s=_float_env("TIER1_TOOL_DEADLINE_S", 3.0),
        ),
        ToolTierSpec(
            name="TT2",
            providers=_split(
                "TIER2_TOOL_PROVIDERS",
                "gpt-4o,gemini-2.5-flash",
            ),
            deadline_s=_float_env("TIER2_TOOL_DEADLINE_S", 5.0),
        ),
        ToolTierSpec(
            name="TT3",
            providers=_split(
                "TIER3_TOOL_PROVIDERS",
                "claude-opus-4-7,gpt-5",
            ),
            deadline_s=None,
        ),
    )


# ---------------------------------------------------------------------------
# Race
# ---------------------------------------------------------------------------


# Queue payload: (kind, producer_name, chunk_or_repr)
#   ("first", name, StreamChunk) — the first usable chunk from this producer
#   ("chunk", name, StreamChunk) — subsequent chunks
#   ("done",  name, None)         — end of this producer's stream
#   ("error", name, str_repr)     — failure
_QueueItem = tuple[str, str, Optional[Any]]


def _is_usable(chunk: StreamChunk) -> bool:
    """A chunk is the "first usable" if it carries content, tool_calls,
    or a finish_reason. Empty whitespace-only chunks are skipped."""
    if chunk.tool_calls:
        return True
    if chunk.content and chunk.content.strip():
        return True
    if chunk.finish_reason:
        return True
    return False


async def _producer_to_queue(
    name: str,
    gen: AsyncIterator[StreamChunk],
    queue: asyncio.Queue[_QueueItem],
) -> None:
    """Drain a provider's StreamChunk stream into the shared queue."""
    seen_first = False
    try:
        async for chunk in gen:
            if not _is_usable(chunk):
                continue
            if not seen_first:
                seen_first = True
                await queue.put(("first", name, chunk))
            else:
                await queue.put(("chunk", name, chunk))
        await queue.put(("done", name, None))
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Tool race producer %r failed: %s", name, exc)
        try:
            await queue.put(("error", name, repr(exc)))
        except Exception:
            pass


async def _race_within_tier(
    tier: ToolTierSpec,
    engine: Any,
    messages: Sequence[Message],
    tools: List[Dict[str, Any]],
    *,
    temperature: float,
    max_tokens: int,
) -> Optional[AsyncIterator[StreamChunk]]:
    """Race the providers in ``tier``; return the winner's stream or None.

    Each producer calls ``engine.stream_full(messages, model=name,
    tools=tools, ...)``. The first to yield a usable :class:`StreamChunk`
    wins; losers are cancelled.
    """
    # Filter to providers whose keys are present.
    candidates = [p for p in tier.providers if _provider_reachable(p)]
    if not candidates:
        logger.info(
            "Tool tier %s: no reachable providers (none of %s have keys set)",
            tier.name, list(tier.providers),
        )
        return None

    queue: asyncio.Queue[_QueueItem] = asyncio.Queue()
    tasks: dict[str, asyncio.Task] = {}

    for name in candidates:
        gen = engine.stream_full(
            messages,
            model=name,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        tasks[name] = asyncio.create_task(_producer_to_queue(name, gen, queue))

    winner: Optional[str] = None
    first_chunk: Optional[StreamChunk] = None
    failed_or_done = 0

    deadline = tier.deadline_s
    deadline_at = (
        asyncio.get_event_loop().time() + deadline
        if deadline is not None else None
    )

    while winner is None and failed_or_done < len(tasks):
        try:
            timeout = (
                max(0.0, deadline_at - asyncio.get_event_loop().time())
                if deadline_at is not None else None
            )
            if timeout is not None and timeout <= 0:
                break
            kind, name, payload = await asyncio.wait_for(
                queue.get(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            break

        if kind == "first":
            winner = name
            first_chunk = payload  # type: ignore[assignment]
            break
        elif kind in ("error", "done"):
            failed_or_done += 1

    if winner is None:
        for t in tasks.values():
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        logger.info(
            "Tool tier %s: no first chunk within %s; falling through",
            tier.name, deadline,
        )
        return None

    # Cancel losers immediately — every running provider costs real money.
    cancelled = 0
    for name, t in tasks.items():
        if name != winner and not t.done():
            t.cancel()
            cancelled += 1
    logger.info(
        "Tool tier %s: winner=%s, cancelled %d loser(s)",
        tier.name, winner, cancelled,
    )

    winner_task = tasks[winner]

    async def relay() -> AsyncIterator[StreamChunk]:
        assert first_chunk is not None
        yield first_chunk
        try:
            while True:
                kind, name, payload = await queue.get()
                if name != winner:
                    continue
                if kind == "chunk":
                    yield payload  # type: ignore[misc]
                elif kind == "done":
                    return
                elif kind == "error":
                    logger.warning(
                        "Tool race winner %s errored mid-stream: %s",
                        winner, payload,
                    )
                    return
        finally:
            if not winner_task.done():
                winner_task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    return relay()


async def cascade_tools(
    engine: Any,
    messages: Sequence[Message],
    tools: List[Dict[str, Any]],
    *,
    temperature: float = 0.7,
    max_tokens: int = 1024,
) -> AsyncIterator[StreamChunk]:
    """Run TT1 → TT2 → TT3 in sequence; yield StreamChunks from the first
    tier that produces a usable chunk within its deadline.

    Each provider receives ``tools=`` so function-calls happen natively.
    """
    tiers = load_tool_tiers()

    for tier in tiers:
        logger.info(
            "Tool cascade entering %s (providers=%s deadline=%s)",
            tier.name, list(tier.providers), tier.deadline_s,
        )
        stream = await _race_within_tier(
            tier,
            engine,
            messages,
            tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if stream is None:
            continue
        async for chunk in stream:
            yield chunk
        return

    logger.warning("Tool cascade: all tiers exhausted with no usable response")
    yield StreamChunk(
        content=(
            "[no tool-capable provider responded — set ANTHROPIC_API_KEY, "
            "DEEPSEEK_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY in env]"
        ),
        finish_reason="stop",
    )


__all__ = [
    "ToolTierSpec",
    "cascade_tools",
    "load_tool_tiers",
]
