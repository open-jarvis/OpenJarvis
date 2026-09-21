"""Regressions for blocking work exposed through async server routes."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("fastapi", reason="openjarvis[server] not installed")

from openjarvis.cli.scan_cmd import PrivacyScanner  # noqa: E402
from openjarvis.server.api_routes import _iterate_sync_stream  # noqa: E402
from openjarvis.server.routes import security_scan  # noqa: E402


def test_security_scan_runs_on_worker_thread() -> None:
    calls: list[int] = []

    def run_all(_self):
        calls.append(threading.get_ident())
        return [
            SimpleNamespace(
                name="test",
                status="ok",
                message="safe",
                platform="all",
            )
        ]

    async def exercise():
        loop_thread = threading.get_ident()
        result = await security_scan()
        return loop_thread, result

    with patch.object(PrivacyScanner, "run_all", run_all):
        loop_thread, result = asyncio.run(exercise())

    assert calls and calls[0] != loop_thread
    assert result["findings"][0]["name"] == "test"


def test_sync_stream_cancellation_waits_for_next_before_close() -> None:
    started = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    executing = threading.Event()

    class BlockingIterator:
        def __iter__(self):
            return self

        def __next__(self):
            executing.set()
            started.set()
            release.wait(timeout=2)
            executing.clear()
            return "late token"

        def close(self):
            assert not executing.is_set()
            closed.set()

    async def exercise() -> None:
        stream = _iterate_sync_stream(BlockingIterator())
        pending = asyncio.create_task(anext(stream))
        while not started.is_set():
            await asyncio.sleep(0)

        pending.cancel()
        timer = threading.Timer(0.05, release.set)
        timer.start()
        try:
            with pytest.raises(asyncio.CancelledError):
                await pending
        finally:
            timer.cancel()

        assert closed.is_set()

    asyncio.run(exercise())
