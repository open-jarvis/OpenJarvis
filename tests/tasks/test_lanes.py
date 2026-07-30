from __future__ import annotations

import asyncio

import pytest

from openjarvis.tasks import ExecutionLane, ExecutionLaneScheduler


@pytest.mark.asyncio
async def test_model_lane_runs_while_interactive_lane_is_blocked() -> None:
    lanes = ExecutionLaneScheduler(model_concurrency=2)
    interactive_started = asyncio.Event()
    release_interactive = asyncio.Event()

    async def blocked_interactive() -> str:
        interactive_started.set()
        await release_interactive.wait()
        return "interactive"

    interactive = asyncio.create_task(
        lanes.run(ExecutionLane.INTERACTIVE, blocked_interactive)
    )
    await interactive_started.wait()

    model = await asyncio.wait_for(
        lanes.run(ExecutionLane.MODEL, lambda: asyncio.sleep(0, result="model")),
        timeout=0.2,
    )
    assert model == "model"
    assert interactive.done() is False

    release_interactive.set()
    assert await interactive == "interactive"


@pytest.mark.asyncio
async def test_interactive_lane_is_exclusive() -> None:
    lanes = ExecutionLaneScheduler()
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()

    async def first() -> None:
        first_started.set()
        await release_first.wait()

    async def second() -> None:
        second_started.set()

    first_task = asyncio.create_task(lanes.run(ExecutionLane.INTERACTIVE, first))
    await first_started.wait()
    second_task = asyncio.create_task(lanes.run(ExecutionLane.INTERACTIVE, second))
    await asyncio.sleep(0.01)
    assert second_started.is_set() is False

    release_first.set()
    await first_task
    await second_task
    assert second_started.is_set() is True


def test_lane_snapshot_contains_no_task_or_credential_data() -> None:
    assert ExecutionLaneScheduler(model_concurrency=3).snapshot() == {
        "model_lane": {"limit": 3, "active": 0},
        "interactive_lane": {"limit": 1, "active": 0},
    }
