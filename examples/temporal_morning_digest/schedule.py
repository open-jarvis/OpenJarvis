"""Register a Temporal Schedule for the daily digest.

Replaces the in-process ``AgentScheduler`` thread + ``croniter`` in
``src/openjarvis/agents/scheduler.py``. Schedules survive worker
restarts, are visible in ``temporal schedule list``, and never
double-fire.
"""

from __future__ import annotations

import asyncio
import os

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
)
from datetime import timedelta

from examples.temporal_morning_digest.activities import DigestInput
from examples.temporal_morning_digest.workflow import MorningDigestWorkflow

SCHEDULE_ID = os.environ.get("DIGEST_SCHEDULE_ID", "morning-digest-daily")
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

    # Demo: every 24h. Swap for ScheduleCalendarSpec for a real cron
    # expression like "every weekday at 7:00am America/Los_Angeles".
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            MorningDigestWorkflow.run,
            inp,
            id=SCHEDULE_ID + "-run",
            task_queue=TASK_QUEUE,
        ),
        spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=timedelta(days=1))]),
    )

    handle = await client.create_schedule(SCHEDULE_ID, schedule)
    print(f"created schedule {handle.id}")


if __name__ == "__main__":
    asyncio.run(main())
