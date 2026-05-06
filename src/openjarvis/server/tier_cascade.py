"""Cascading-tier provider race.

Each tier is a list of provider model ids and a deadline. For each tier we
launch one asyncio task per provider in parallel; the first task to yield a
usable token wins. Remaining tasks are cancelled. If the tier deadline elapses
without any task producing a first token, we fall through to the next tier.

The "auto" model id at /v1/chat/completions activates this cascade.

Tier definitions are read from env vars at request time:
  TIER1_PROVIDERS, TIER1_DEADLINE_S
  TIER2_PROVIDERS, TIER2_DEADLINE_S
  TIER3_PROVIDERS  (no deadline)
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Optional

from openjarvis.core.types import Message
from openjarvis.server import claude_cli_client, cloud_router

logger = logging.getLogger(__name__)


# Sentinel model ids that route to the inspiring-cat task API instead of
# cloud_router. Use them inside a TIERn_PROVIDERS comma list.
CLAUDE_CLI_MODELS = {"claude-cli", "claude-pro"}


@dataclass(frozen=True)
class TierSpec:
    name: str
    providers: tuple[str, ...]
    deadline_s: Optional[float]  # None == no deadline (last resort)


def _split(env_name: str, default: str) -> tuple[str, ...]:
    raw = os.environ.get(env_name, default)
    return tuple(p.strip() for p in raw.split(",") if p.strip())


def _float_env(env_name: str, default: float) -> float:
    try:
        return float(os.environ.get(env_name, str(default)))
    except ValueError:
        return default


def load_tiers() -> tuple[TierSpec, ...]:
    """Load tier definitions from env at call time so changes take effect
    without a process restart."""
    return (
        TierSpec(
            name="T1",
            providers=_split(
                "TIER1_PROVIDERS",
                "groq/llama-3.1-8b-instant,"
                "cerebras/llama3.1-8b,"
                "sambanova/Meta-Llama-3.3-70B-Instruct",
            ),
            deadline_s=_float_env("TIER1_DEADLINE_S", 2.0),
        ),
        TierSpec(
            name="T2",
            providers=_split(
                "TIER2_PROVIDERS",
                "claude-cli,"
                "deepseek-chat,"
                "gemini-2.5-flash",
            ),
            deadline_s=_float_env("TIER2_DEADLINE_S", 5.0),
        ),
        TierSpec(
            name="T3",
            providers=_split(
                "TIER3_PROVIDERS",
                "openrouter/anthropic/claude-sonnet-4,"
                "kimi/moonshot-v1-32k,"
                "groq/llama-3.3-70b-versatile",
            ),
            deadline_s=None,
        ),
    )


def is_auto_model(model: str) -> bool:
    """Whether this model id should trigger the cascade."""
    if not model:
        return False
    m = model.strip().lower()
    return m in ("auto", "openjarvis-auto", "openjarvis/auto")


# ---------------------------------------------------------------------------
# Per-provider chunk producers
# ---------------------------------------------------------------------------


async def _stream_via_cloud_router(
    model: str,
    messages: Sequence[Message],
    *,
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[str]:
    """Adapter: cloud_router.stream_cloud (also handles local via stream_local).

    cloud_router already has dispatch for all 13 providers and proper key
    handling. We just need the model id to match its `get_provider` rules.
    """
    if cloud_router.is_cloud_model(model):
        async for tok in cloud_router.stream_cloud(
            model, messages, temperature, max_tokens,
        ):
            yield tok
    else:
        async for tok in cloud_router.stream_local(
            model, messages, temperature, max_tokens,
        ):
            yield tok


async def _stream_via_claude_cli(
    messages_json: list[dict],
) -> AsyncIterator[str]:
    """Submit to inspiring-cat and yield the result as one chunk when done.

    No streaming primitive exists upstream; we simply yield the full text
    once status=done. Submission is synchronous-ish (a few hundred ms);
    polling continues until completion or default 180s timeout.
    """
    task_id = await claude_cli_client.submit(messages_json)
    result = await claude_cli_client.await_completion(task_id)
    if result.status == "done" and result.result:
        yield result.result
    else:
        # Surface the error via empty stream — race will treat as no first token
        logger.info(
            "claude-cli race entry returned status=%s error=%s",
            result.status, result.error,
        )


# ---------------------------------------------------------------------------
# Race
# ---------------------------------------------------------------------------


async def _producer_to_queue(
    name: str,
    gen: AsyncIterator[str],
    queue: asyncio.Queue[tuple[str, str, Optional[str]]],
) -> None:
    """Drain a provider's chunk stream into a shared queue.

    Item shape: (kind, producer_name, payload)
      ("first" | "chunk", name, text)   normal flow
      ("done", name, None)              end of this provider's stream
      ("error", name, repr(exc))        failure
    """
    seen_first = False
    try:
        async for tok in gen:
            if not tok:
                continue
            if not seen_first:
                seen_first = True
                await queue.put(("first", name, tok))
            else:
                await queue.put(("chunk", name, tok))
        await queue.put(("done", name, None))
    except asyncio.CancelledError:
        # Normal cancellation — losing the race. Don't enqueue, just exit.
        raise
    except Exception as exc:
        logger.warning("Race producer %r failed: %s", name, exc)
        try:
            await queue.put(("error", name, repr(exc)))
        except Exception:
            pass


async def _race_within_tier(
    tier: TierSpec,
    messages: Sequence[Message],
    messages_json: list[dict],
    *,
    temperature: float,
    max_tokens: int,
) -> Optional[AsyncIterator[str]]:
    """Run a single tier's race; return the winning token stream or None.

    Once any provider produces its first usable token, cancel all the
    losers (they cost real money/credits if left to run) and stream from
    the winner. If the deadline elapses with no first token, cancel
    everyone and return None so the cascade falls through to the next tier.
    """
    if not tier.providers:
        return None

    queue: asyncio.Queue[tuple[str, str, Optional[str]]] = asyncio.Queue()
    tasks: dict[str, asyncio.Task] = {}

    for name in tier.providers:
        if name in CLAUDE_CLI_MODELS:
            gen = _stream_via_claude_cli(messages_json)
        else:
            gen = _stream_via_cloud_router(
                name, messages,
                temperature=temperature, max_tokens=max_tokens,
            )
        tasks[name] = asyncio.create_task(_producer_to_queue(name, gen, queue))

    winner: Optional[str] = None
    first_token: Optional[str] = None
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
            first_token = payload
            break
        elif kind in ("error", "done"):
            failed_or_done += 1
        # "chunk" before "first" cannot occur per producer logic

    if winner is None:
        # Deadline hit OR every provider failed/finished with no usable
        # token — cancel any still-running and fall through.
        for t in tasks.values():
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        logger.info(
            "Tier %s: no first token within %s; falling through",
            tier.name, deadline,
        )
        return None

    # Cancel every loser NOW so we don't burn tokens generating output
    # nobody will read.
    cancelled = 0
    for name, t in tasks.items():
        if name != winner and not t.done():
            t.cancel()
            cancelled += 1
    logger.info(
        "Tier %s: winner=%s, cancelled %d loser(s)",
        tier.name, winner, cancelled,
    )

    winner_task = tasks[winner]

    async def relay() -> AsyncIterator[str]:
        assert first_token is not None
        yield first_token
        try:
            while True:
                kind, name, payload = await queue.get()
                # Items from cancelled losers are silently dropped.
                if name != winner:
                    continue
                if kind == "chunk":
                    if payload:
                        yield payload
                elif kind == "done":
                    return
                elif kind == "error":
                    logger.warning(
                        "Race winner %s errored mid-stream: %s",
                        winner, payload,
                    )
                    return
        finally:
            # Best-effort cleanup if the consumer exits early (client
            # disconnect, etc.) — make sure the winner task isn't left
            # running indefinitely.
            if not winner_task.done():
                winner_task.cancel()
            # Also drain the gather to surface CancelledError from losers
            await asyncio.gather(*tasks.values(), return_exceptions=True)

    return relay()


async def cascade(
    messages: Sequence[Message],
    *,
    temperature: float,
    max_tokens: int,
) -> AsyncIterator[str]:
    """Run T1 -> T2 -> T3 in sequence; yield tokens from the first tier
    that produces a first token within its deadline."""
    tiers = load_tiers()
    # Build the JSON messages once (used by claude-cli adapter)
    from openjarvis.engine._base import messages_to_dicts
    messages_json = messages_to_dicts(messages)

    for tier in tiers:
        logger.info(
            "Cascade entering %s (providers=%s deadline=%s)",
            tier.name, list(tier.providers), tier.deadline_s,
        )
        stream = await _race_within_tier(
            tier,
            messages,
            messages_json,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if stream is None:
            continue
        async for tok in stream:
            yield tok
        return

    # All tiers exhausted with no first token
    logger.warning("Cascade: all tiers exhausted with no usable response")
    yield (
        "[no provider responded — check provider keys and *_ENABLED flags "
        "in Railway service variables]"
    )


__all__ = [
    "TierSpec",
    "load_tiers",
    "is_auto_model",
    "cascade",
]
