import asyncio
import time

import httpx
import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from httpx import AsyncClient  # noqa: E402

from openjarvis.core.config import JarvisConfig  # noqa: E402
from openjarvis.server.app import create_app  # noqa: E402


@pytest.fixture
def app_with_mock_engine() -> FastAPI:
    config = JarvisConfig()
    app = create_app(engine=None, model="test_model", config=config)

    # Mock the engine so the pull route doesn't crash
    class MockEngine:
        engine_id = "ollama"
        _host = "http://localhost:11434"

    app.state.engine = MockEngine()
    app.state.engine_name = "ollama"
    return app


@pytest.mark.asyncio
async def test_pull_model_does_not_block_event_loop(
    app_with_mock_engine: FastAPI,
) -> None:
    """Test POST /v1/models/pull does not block event loop waiting for Ollama."""

    # We will mock httpx.AsyncClient.post to sleep for 1 second, simulating a
    # slow network request
    async def mock_post(*args, **kwargs):
        await asyncio.sleep(1.0)
        resp = httpx.Response(200, json={"status": "success"})
        resp.request = httpx.Request("POST", "http://localhost:11434/api/pull")
        return resp

    # We also need a fast route to call concurrently
    @app_with_mock_engine.get("/__test_fast")
    async def fast_route():
        return {"status": "fast"}

    async with AsyncClient(
        transport=httpx.ASGITransport(app=app_with_mock_engine), base_url="http://test"
    ) as client:
        with pytest.MonkeyPatch.context() as m:
            m.setattr("httpx.AsyncClient.post", mock_post)

            start_time = time.monotonic()

            # Fire both requests concurrently
            slow_req = asyncio.create_task(
                client.post("/v1/models/pull", json={"name": "test-model"})
            )
            # Give the slow request a tiny moment to start and hit the sleep
            await asyncio.sleep(0.1)

            fast_req = asyncio.create_task(client.get("/__test_fast"))

            fast_resp = await fast_req
            assert fast_resp.status_code == 200

            # The fast response should return almost instantly, well before the
            # 1 second sleep finishes
            fast_elapsed = time.monotonic() - start_time
            assert fast_elapsed < 0.5, (
                f"Fast route took {fast_elapsed}s, event loop might be blocked!"
            )

            slow_resp = await slow_req
            assert slow_resp.status_code == 200
