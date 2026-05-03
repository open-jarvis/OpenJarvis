"""Durable Morning Digest workflow.

The workflow only sequences activities and decides retry policy. It
contains *no* network or filesystem I/O so it stays deterministic and
can be replayed on worker restart without redoing completed steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from examples.temporal_morning_digest.activities import (
        DigestInput,
        collect_sources,
        generate_narrative,
        store_artifact,
        synthesize_audio,
    )


# Per-step retry policies sized for what each step actually does.
#
# Connectors (Step 1): many flaky third-party APIs. Worth retrying for a
# while on transient errors, with backoff so we don't hammer rate limits.
COLLECT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2),
    maximum_attempts=6,
    non_retryable_error_types=["ValueError", "TypeError"],
)

# LLM generation (Step 2): expensive. Retry sparingly. Long timeout so a
# slow local model doesn't get prematurely killed.
GENERATE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    backoff_coefficient=2.0,
    maximum_attempts=3,
    non_retryable_error_types=["ValueError"],
)

# TTS (Step 3): external rate-limited API. Several retries with longer
# backoff handles 429s gracefully.
TTS_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
    maximum_attempts=5,
)

# SQLite write (Step 4): local, fast, mostly never fails. Cheap to retry.
STORE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_attempts=4,
)


@dataclass
class DigestRunResult:
    text: str
    audio_path: str
    sources_used: list[str]
    quality_score: float


@workflow.defn
class MorningDigestWorkflow:
    """One run of the Morning Digest pipeline as a durable workflow.

    Compared to ``MorningDigestAgent.run()``:

    * Each step is a separately retryable activity, so a TTS hiccup no
      longer wastes the connector + LLM work that already succeeded.
    * The evaluator's silent ``except: pass`` is gone — failures are
      logged and the run still completes with the un-evaluated draft.
    * Workflow restarts are durable: if the worker dies after Step 2,
      Step 1 and Step 2 are *not* re-executed on resume.
    """

    @workflow.run
    async def run(self, inp: DigestInput) -> DigestRunResult:
        workflow.logger.info("morning digest starting")

        collected = await workflow.execute_activity(
            collect_sources,
            inp,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=COLLECT_RETRY,
        )

        narrative = await workflow.execute_activity(
            generate_narrative,
            args=[inp, collected],
            start_to_close_timeout=timedelta(minutes=10),
            retry_policy=GENERATE_RETRY,
        )

        tts = await workflow.execute_activity(
            synthesize_audio,
            args=[inp, narrative],
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=TTS_RETRY,
        )

        meta: dict[str, Any] = await workflow.execute_activity(
            store_artifact,
            args=[inp, collected, narrative, tts],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=STORE_RETRY,
        )

        return DigestRunResult(
            text=narrative.text,
            audio_path=meta.get("audio_path", ""),
            sources_used=meta.get("sources_used", []),
            quality_score=meta.get("quality_score", 0.0),
        )
