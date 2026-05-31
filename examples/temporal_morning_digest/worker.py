"""Worker for the Morning Digest workflow.

Run alongside ``temporal server start-dev`` (or against any cluster
reachable at ``TEMPORAL_ADDRESS``).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os

from temporalio.client import Client
from temporalio.worker import Worker

from examples.temporal_morning_digest.activities import (
    collect_sources,
    generate_narrative,
    store_artifact,
    synthesize_audio,
)
from examples.temporal_morning_digest.workflow import MorningDigestWorkflow

TASK_QUEUE = os.environ.get("DIGEST_TASK_QUEUE", "morning-digest")


async def main() -> None:
    address = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")
    client = await Client.connect(address)

    # Sync activities reuse a thread pool; sized for the modest fan-out
    # of one digest run at a time.
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        worker = Worker(
            client,
            task_queue=TASK_QUEUE,
            workflows=[MorningDigestWorkflow],
            activities=[
                collect_sources,
                generate_narrative,
                synthesize_audio,
                store_artifact,
            ],
            activity_executor=pool,
        )
        print(f"morning digest worker listening on {address!r} / {TASK_QUEUE!r}")
        await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
