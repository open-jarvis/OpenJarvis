"""Background worker: poll Claude-CLI, compare to spoken answer, surface banner.

For each chat request that opts into elaboration, `_handle_stream` calls
`spawn_elaboration()` which:
  1. Submits the prompt to inspiring-cat (Claude-CLI worker).
  2. Creates an Elaboration record in the store.
  3. Launches an asyncio task that polls until done, then runs the diff
     heuristic, and either marks PROPOSED (broadcast over SSE) or DISCARDED.

The chat handler keeps a reference to the Elaboration record so it can write
the spoken_answer back into it when the immediate stream finishes.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import os
from typing import Any, Optional

from openjarvis.server import claude_cli_client
from openjarvis.server.elaboration_store import (
    Elaboration,
    get_store,
)

logger = logging.getLogger(__name__)


def _length_ratio_threshold() -> float:
    try:
        return float(os.environ.get("ELABORATION_DIFF_LENGTH_RATIO", "1.5"))
    except ValueError:
        return 1.5


def _similarity_threshold() -> float:
    try:
        return float(os.environ.get("ELABORATION_DIFF_LEVENSHTEIN", "0.6"))
    except ValueError:
        return 0.6


def _timeout_s() -> float:
    try:
        return float(os.environ.get("CLAUDE_CLI_TIMEOUT_S", "180"))
    except ValueError:
        return 180.0


def is_enabled() -> bool:
    return os.environ.get("ELABORATION_ENABLED", "true").strip().lower() in (
        "true", "1", "yes", "on",
    )


def _is_materially_different(spoken: str, claude: str) -> bool:
    """Heuristic: claude answer is meaningfully different from the spoken one.

    Both checks must trigger to avoid false positives:
      - length ratio: claude/spoken > threshold (default 1.5x)
      - similarity:   SequenceMatcher.ratio() < threshold (default 0.6)
    """
    spoken = (spoken or "").strip()
    claude = (claude or "").strip()
    if not claude:
        return False
    if not spoken:
        # No spoken answer to compare against — surface anyway, user may want it
        return True

    length_ratio = len(claude) / max(len(spoken), 1)
    similarity = difflib.SequenceMatcher(a=spoken, b=claude).ratio()

    materially = (
        length_ratio > _length_ratio_threshold()
        and similarity < _similarity_threshold()
    )
    logger.info(
        "Elaboration diff: len_ratio=%.2f sim=%.2f -> materially_different=%s",
        length_ratio, similarity, materially,
    )
    return materially


async def _run(elab_id: str, messages: list[dict[str, Any]]) -> None:
    """The actual background coroutine."""
    store = get_store()
    try:
        task_id = await claude_cli_client.submit(messages)
    except Exception as exc:
        logger.warning("Claude-CLI submit failed for %s: %s", elab_id, exc)
        await store.mark_failed(elab_id, error=f"submit failed: {exc}")
        return

    try:
        result = await claude_cli_client.await_completion(
            task_id,
            timeout_s=_timeout_s(),
        )
    except asyncio.TimeoutError:
        await store.mark_failed(elab_id, error="claude-cli timeout")
        return
    except Exception as exc:
        logger.warning("Claude-CLI poll failed for %s: %s", elab_id, exc)
        await store.mark_failed(elab_id, error=f"poll failed: {exc}")
        return

    if result.status != "done" or not result.result:
        await store.mark_failed(
            elab_id,
            error=result.error or f"claude-cli returned status={result.status}",
        )
        return

    claude_text = result.result.strip()

    # Wait briefly for the immediate stream to finish writing the spoken_answer.
    # In practice the stream finishes within ~1-2s; we wait up to 10s so the
    # diff has a real comparison target.
    spoken_answer: Optional[str] = None
    for _ in range(20):
        elab = await store.get(elab_id)
        if elab is not None and elab.spoken_answer is not None:
            spoken_answer = elab.spoken_answer
            break
        await asyncio.sleep(0.5)

    if _is_materially_different(spoken_answer or "", claude_text):
        await store.mark_proposed(elab_id, claude_answer=claude_text)
    else:
        await store.mark_discarded(elab_id, claude_answer=claude_text)


async def spawn_elaboration(
    *,
    messages: list[dict[str, Any]],
    original_question: str,
    conversation_id: Optional[str] = None,
) -> Optional[Elaboration]:
    """Create an Elaboration record + launch the background worker.

    Returns the Elaboration so the caller (chat handler) can later write
    spoken_answer back into it. Returns None if elaboration is disabled.
    """
    if not is_enabled():
        return None

    store = get_store()
    elab = await store.create(
        original_question=original_question,
        conversation_id=conversation_id,
    )

    # Fire-and-forget the worker. asyncio holds a strong reference for as long
    # as the task is running.
    asyncio.create_task(_run(elab.id, messages))
    return elab


__all__ = [
    "is_enabled",
    "spawn_elaboration",
]
