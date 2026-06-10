"""Trigger one digest run on demand.

Usage::

    uv run python -m examples.temporal_morning_digest.starter
"""

from __future__ import annotations

import asyncio
import os
import uuid

from temporalio.client import Client

from examples.temporal_morning_digest.activities import DigestInput
from examples.temporal_morning_digest.workflow import MorningDigestWorkflow

TASK_QUEUE = os.environ.get("DIGEST_TASK_QUEUE", "morning-digest")


async def main() -> None:
    client = await Client.connect(os.environ.get("TEMPORAL_ADDRESS", "localhost:7233"))

    inp = DigestInput(
        persona=os.environ.get("DIGEST_PERSONA", "jarvis"),
        timezone=os.environ.get("DIGEST_TIMEZONE", "America/Los_Angeles"),
        voice_id=os.environ.get("DIGEST_VOICE_ID", ""),
        tts_backend=os.environ.get("DIGEST_TTS_BACKEND", "cartesia"),
        engine=os.environ.get("DIGEST_ENGINE", "ollama"),
        model=os.environ.get("DIGEST_MODEL", "qwen3.5:4b"),
    )

    handle = await client.start_workflow(
        MorningDigestWorkflow.run,
        inp,
        id=f"morning-digest-{uuid.uuid4()}",
        task_queue=TASK_QUEUE,
    )
    print(f"started workflow {handle.id}")

    result = await handle.result()
    print(f"audio: {result.audio_path}")
    print(f"sources: {result.sources_used}")
    print(f"quality: {result.quality_score:.1f}")
    print()
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
