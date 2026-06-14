"""OSINT background scheduler — ticks every minute to execute due schedules."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

_task: asyncio.Task | None = None
_bus: Any | None = None


async def scheduler_loop(interval: float = 60.0) -> None:
    """Run the schedule ticker indefinitely."""
    from openjarvis.server.osint_store import get_store

    while True:
        try:
            executed = get_store()._tick()
            if executed:
                logger.info("Scheduler tick: executed %d jobs", len(executed))
                if _bus is not None:
                    try:
                        from openjarvis.core.events import EventType

                        for job in executed:
                            _bus.publish(
                                EventType.SCHEDULER_TASK_END,
                                {
                                    "schedule_id": job.get("schedule_id"),
                                    "target": job.get("target"),
                                    "success": job.get("success"),
                                    "changed": job.get("changed"),
                                },
                            )
                    except Exception:
                        pass
        except Exception as exc:
            logger.exception("Scheduler tick failed: %s", exc)
        await asyncio.sleep(interval)


def start_scheduler(interval: float = 60.0, bus: Any | None = None) -> None:
    """Start the scheduler background task (idempotent)."""
    global _task, _bus
    _bus = bus
    if _task is None or _task.done():
        _task = asyncio.create_task(scheduler_loop(interval))
        logger.info("OSINT scheduler started (interval=%.0fs)", interval)


def stop_scheduler() -> None:
    """Cancel the scheduler background task."""
    global _task
    if _task and not _task.done():
        _task.cancel()
        logger.info("OSINT scheduler stopped")
