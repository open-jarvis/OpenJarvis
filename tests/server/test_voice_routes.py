"""Focused protocol tests for the Pipecat WebRTC routes."""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="openjarvis[server] not installed")
pytest.importorskip("pipecat", reason="openjarvis[voice] not installed")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.voice import routes


def test_voice_offer_patch_forwards_trickle_ice_candidates(monkeypatch):
    captured = []

    class FakeHandler:
        async def handle_patch_request(self, request):
            captured.append(request)

    monkeypatch.setattr(routes, "_handler", lambda _request: FakeHandler())
    app = FastAPI()
    app.include_router(routes.router)

    response = TestClient(app).patch(
        "/api/voice/webrtc/offer",
        json={
            "pc_id": "peer-1",
            "candidates": [
                {
                    "candidate": "candidate:1 1 UDP 1 127.0.0.1 5000 typ host",
                    "sdp_mid": "0",
                    "sdp_mline_index": 0,
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "success"}
    assert captured[0].pc_id == "peer-1"
    assert captured[0].candidates[0].sdp_mid == "0"
