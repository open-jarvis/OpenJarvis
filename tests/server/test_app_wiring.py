"""Voice and kiosk hang off the same system, not a second one."""

from __future__ import annotations

import inspect


def test_voice_router_is_mounted():
    import openjarvis.server.app as app_module

    source = inspect.getsource(app_module)
    assert "voice_router" in source
    assert "include_router(voice_router" in source


def test_kiosk_is_set_up():
    import openjarvis.server.app as app_module

    source = inspect.getsource(app_module)
    assert "_setup_kiosk" in source
    assert "kiosk_router" in source


def test_native_agent_runtime_wraps_the_serving_agent():
    """The realtime binding must come from the agent the system serves."""
    import openjarvis.server.app as app_module

    source = inspect.getsource(app_module)
    assert "NativeAgentRuntime(" in source
    assert "app.state.native_agent_runtime" in source


def test_voice_session_service_is_exposed():
    import openjarvis.server.app as app_module

    assert "voice_session_service" in inspect.getsource(app_module)


def test_availability_router_is_mounted_even_when_the_gate_is_closed():
    """The UI must be able to ask *why* voice is off, so this one is ungated."""
    from openjarvis.server.app import create_app

    app = create_app(engine=None, model="m", bind_host="0.0.0.0")

    assert app.state.gemini_live_poc_enabled is False
    paths = {route.path for route in app.routes}
    assert "/api/voice/availability" in paths
    assert "/api/voice/webrtc/offer" not in paths


def test_gate_closes_when_the_pipecat_runtime_is_absent(monkeypatch):
    """An open Gemini gate still must not mount a router that failed to import."""
    import openjarvis.server.app as app_module

    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(app_module, "voice_router", None)

    app = app_module.create_app(engine=None, model="m", bind_host="127.0.0.1")

    assert app.state.gemini_live_poc_enabled is False
    assert app.state.gemini_live_poc_unavailable_reason == "voice_runtime_missing"
