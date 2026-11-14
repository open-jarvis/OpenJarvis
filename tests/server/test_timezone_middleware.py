"""X-OpenJarvis-Timezone is visible to code handling the request."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.prompt import time_context
from openjarvis.prompt.time_context import resolve_timezone
from openjarvis.server.timezone_middleware import TimezoneMiddleware


@pytest.fixture(autouse=True)
def _no_remembered_zone(monkeypatch):
    monkeypatch.setattr(time_context, "_last_client_timezone", None)


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
