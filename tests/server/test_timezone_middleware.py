"""X-OpenJarvis-Timezone is visible to code handling the request."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.prompt.time_context import (
    reset_request_timezone,
    resolve_timezone,
    set_request_timezone,
)
from openjarvis.server.timezone_middleware import TimezoneMiddleware


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TimezoneMiddleware)

    @app.get("/tz")
    async def tz():
        # Work moved to a thread (as chat and agents do) keeps the zone.
        name = await asyncio.to_thread(lambda: resolve_timezone("Europe/Paris")[0])
        return {"zone": name}

    return app


def test_header_sets_zone_for_the_request() -> None:
    client = TestClient(_app())
    r = client.get("/tz", headers={"X-OpenJarvis-Timezone": "Africa/Cairo"})
    assert r.json() == {"zone": "Africa/Cairo"}


def test_missing_or_bad_header_falls_back_to_config(monkeypatch) -> None:
    client = TestClient(_app())
    assert client.get("/tz").json() == {"zone": "Europe/Paris"}
    bad = client.get("/tz", headers={"X-OpenJarvis-Timezone": "Mars/Base"})
    assert bad.json() == {"zone": "Europe/Paris"}


def test_previous_request_cannot_override_the_configured_zone() -> None:
    client = TestClient(_app())
    assert client.get(
        "/tz", headers={"X-OpenJarvis-Timezone": "Asia/Tokyo"}
    ).json() == {"zone": "Asia/Tokyo"}
    assert client.get("/tz").json() == {"zone": "Europe/Paris"}
    assert client.get("/tz", headers={"X-OpenJarvis-Timezone": "Mars/Base"}).json() == {
        "zone": "Europe/Paris"
    }


def test_managed_workers_keep_their_own_request_context() -> None:
    from openjarvis.server.agent_manager_routes import _start_managed_worker

    state = SimpleNamespace()
    release = threading.Event()
    observed = {}
    workers = []

    def read_zone(name):
        assert release.wait(2)
        observed[name] = resolve_timezone("Europe/Paris")[0]

    try:
        for zone in ("Asia/Tokyo", "Africa/Cairo"):
            token = set_request_timezone(zone)
            try:
                workers.append(
                    _start_managed_worker(
                        state, lambda name=zone: read_zone(name), name="timezone-test"
                    )
                )
            finally:
                reset_request_timezone(token)
    finally:
        release.set()
        for worker in workers:
            worker.join(timeout=2)
    assert all(not worker.is_alive() for worker in workers)
    assert observed == {"Asia/Tokyo": "Asia/Tokyo", "Africa/Cairo": "Africa/Cairo"}
    assert resolve_timezone("Europe/Paris")[0] == "Europe/Paris"


@pytest.mark.asyncio
async def test_concurrent_requests_keep_their_own_zone() -> None:
    import httpx

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            client.get("/tz", headers={"X-OpenJarvis-Timezone": "Asia/Tokyo"}),
            client.get("/tz", headers={"X-OpenJarvis-Timezone": "Africa/Cairo"}),
            client.get("/tz"),
        )
    assert [r.json()["zone"] for r in responses] == [
        "Asia/Tokyo",
        "Africa/Cairo",
        "Europe/Paris",
    ]
