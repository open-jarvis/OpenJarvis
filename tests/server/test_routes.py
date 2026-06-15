"""Tests for the API server routes."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.app import create_app  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(content="Hello from server", models=None):
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = models or ["test-model"]
    engine.generate.return_value = {
        "content": content,
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }

    # Set up async stream
    async def mock_stream(
        messages,
        *,
        model,
        temperature=0.7,
        max_tokens=1024,
        **kwargs,
    ):
        for token in ["Hello", " ", "world"]:
            yield token

    engine.stream = mock_stream
    return engine


def _make_agent(content="Hello from agent"):
    from openjarvis.agents._stubs import AgentResult

    agent = MagicMock()
    agent.agent_id = "mock"
    agent.run.return_value = AgentResult(content=content, turns=1)
    return agent


@pytest.fixture
def client():
    engine = _make_engine()
    app = create_app(engine, "test-model")
    return TestClient(app)


@pytest.fixture
def client_with_agent():
    engine = _make_engine()
    agent = _make_agent()
    app = create_app(engine, "test-model", agent=agent)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Chat completions tests
# ---------------------------------------------------------------------------


class TestChatCompletions:
    def test_basic_completion(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert data["choices"][0]["message"]["content"] == "Hello from server"

    def test_completion_has_usage(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = resp.json()
        assert data["usage"]["total_tokens"] == 8

    def test_completion_has_id(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = resp.json()
        assert data["id"].startswith("chatcmpl-")

    def test_custom_temperature(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "temperature": 0.1,
            },
        )
        assert resp.status_code == 200

    def test_with_system_message(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "Be helpful"},
                    {"role": "user", "content": "Hello"},
                ],
            },
        )
        assert resp.status_code == 200

    def test_with_tools(self):
        engine = _make_engine()
        engine.generate.return_value = {
            "content": "",
            "tool_calls": [
                {"id": "c1", "name": "calc", "arguments": '{"expr":"2+2"}'},
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            "model": "test-model",
            "finish_reason": "tool_calls",
        }
        app = create_app(engine, "test-model")
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Calc"}],
                "tools": [{"type": "function", "function": {"name": "calc"}}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["tool_calls"] is not None

    def test_agent_mode(self, client_with_agent):
        resp = client_with_agent.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello from agent"

    def test_with_tools_bypasses_agent(self):
        """Regression for #414.

        When the client passes explicit `tools` AND an agent is
        registered, the request must go to `_handle_direct` (which
        preserves tool_calls from the engine) rather than `_handle_agent`
        (which calls `agent.run()` ignoring `request_body.tools` and
        returns only `result.content`, dropping tool_calls and
        substituting whatever generic content the agent's re-prompted
        LLM produced).
        """
        engine = _make_engine()
        engine.generate.return_value = {
            "content": "",
            "tool_calls": [
                {"id": "c1", "name": "list_files", "arguments": '{"directory":"/tmp"}'},
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            "model": "test-model",
            "finish_reason": "tool_calls",
        }
        agent = _make_agent(content="GENERIC AGENT FILLER")
        app = create_app(engine, "test-model", agent=agent)
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Use list_files on /tmp."}],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "list_files",
                            "parameters": {
                                "type": "object",
                                "properties": {"directory": {"type": "string"}},
                                "required": ["directory"],
                            },
                        },
                    },
                ],
            },
        )
        assert resp.status_code == 200
        msg = resp.json()["choices"][0]["message"]
        # The engine's tool_calls must survive — proves we bypassed
        # _handle_agent and reached _handle_direct.
        assert msg["tool_calls"] is not None
        assert msg["tool_calls"][0]["function"]["name"] == "list_files"
        # Content must be the engine's empty string, NOT the agent's
        # filler. If this assertion fails, the agent ran and produced
        # filler content while dropping the real tool_calls — exactly
        # the bug #414 reported.
        assert msg["content"] == ""
        assert "GENERIC AGENT FILLER" not in (msg["content"] or "")
        # And the engine was actually called (proves we hit _handle_direct
        # rather than short-circuiting somewhere else).
        assert engine.generate.called
        # And the agent was NOT called (proves the bypass worked).
        assert not agent.run.called

    def test_without_tools_still_uses_agent(self, client_with_agent):
        """Counterpart to test_with_tools_bypasses_agent: when no tools
        are requested, the agent path is still used (preserves existing
        behavior for plain chat through an agent)."""
        resp = client_with_agent.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # No tools → agent path → agent's content surfaces.
        assert data["choices"][0]["message"]["content"] == "Hello from agent"

    def test_instrumented_engine_unwrapped_to_avoid_dual_telemetry(self):
        """Regression for the leaderboard wonky-values bug.

        When `app.state.engine` is already an `InstrumentedEngine` (which is
        the common case when the server was constructed with telemetry
        wired in), `_handle_direct` MUST NOT wrap it again with
        `instrumented_generate`. Both layers publish `TELEMETRY_RECORD`
        events, so wrapping twice would double-count every call into the
        leaderboard pipeline and inflate per-token energy / FLOPs metrics
        by 2× on every request — the dominant contributor to the bimodal
        Wh/token distribution on the public leaderboard.

        The fix unwraps the engine via `engine._inner` before passing it
        to `instrumented_generate`. This test pins that contract.
        """
        from openjarvis.core.events import EventBus, EventType
        from openjarvis.telemetry.instrumented_engine import InstrumentedEngine

        # Build a fresh engine + bus and explicitly wrap with
        # InstrumentedEngine (mirrors the production app construction).
        inner_engine = _make_engine(content="Telemetry test")
        bus = EventBus()
        wrapped = InstrumentedEngine(inner_engine, bus=bus)

        received_records = []
        bus.subscribe(
            EventType.TELEMETRY_RECORD,
            lambda data: received_records.append(data),
        )

        app = create_app(wrapped, "test-model")
        app.state.bus = bus
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 200

        # Exactly ONE telemetry record — not two. Pre-fix this asserted 2.
        assert len(received_records) == 1, (
            f"Expected exactly one TELEMETRY_RECORD event per request "
            f"(got {len(received_records)}). When `app.state.engine` is "
            f"already an InstrumentedEngine, routes.py must not also fire "
            f"`instrumented_generate` — both layers publish and double "
            f"the leaderboard's per-request counts."
        )

        # And the surviving record must be the InstrumentedEngine's
        # FULL record (with token_counting_version stamped, ready for
        # the leaderboard's current_methodology_only=True filter).
        # If routes.py had instead unwrapped engine._inner and routed
        # through the lightweight `instrumented_generate`, the record
        # would carry no version stamp and `current_methodology_only`
        # would drop it from leaderboard sums entirely. Pin that
        # contract — see the adversarial review on PR #498.
        from openjarvis.core.types import TOKEN_COUNTING_VERSION

        rec = received_records[0].data["record"]
        assert rec.token_counting_version == TOKEN_COUNTING_VERSION, (
            "InstrumentedEngine path must stamp the methodology version "
            "so the leaderboard's current-methodology filter accepts the "
            "record."
        )

    def test_agent_with_conversation(self, client_with_agent):
        resp = client_with_agent.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "Be helpful"},
                    {"role": "user", "content": "Hello"},
                ],
            },
        )
        assert resp.status_code == 200

    def test_streaming(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        # Parse SSE events
        lines = resp.text.strip().split("\n")
        data_lines = [ln for ln in lines if ln.startswith("data:")]
        assert len(data_lines) > 0
        # Last should be [DONE]
        assert data_lines[-1].strip() == "data: [DONE]"

    def test_streaming_content(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
            },
        )
        # Collect content tokens from stream
        content = ""
        for line in resp.text.strip().split("\n"):
            if line.startswith("data:") and "[DONE]" not in line:
                data = json.loads(line[5:].strip())
                choices = data.get("choices", [{}])
                delta_content = (
                    choices[0]
                    .get(
                        "delta",
                        {},
                    )
                    .get("content")
                )
                if delta_content:
                    content += delta_content
        assert content == "Hello world"

    def test_streaming_with_tools_emits_tool_calls_and_bypasses_agent(self):
        """Regression for the streaming analog of #414.

        When the client streams (`stream:true`) WITH explicit `tools`, the
        response must carry the model's real tool_calls (sourced from
        engine.stream_full) and a finish_reason of "tool_calls" — NOT route
        through the agent bridge, which ignores request_body.tools, runs the
        agent's own tool loop, and word-splits generic filler content,
        dropping the tool_calls the caller asked for.
        """
        from openjarvis.core.events import EventBus
        from openjarvis.engine._stubs import StreamChunk

        engine = _make_engine()

        async def mock_stream_full(
            messages,
            *,
            model,
            temperature=0.7,
            max_tokens=1024,
            **kwargs,
        ):
            # Ollama-shape: a complete tool_call arrives in a single chunk
            # carrying finish_reason="tool_calls".
            yield StreamChunk(
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Paris"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

        engine.stream_full = mock_stream_full
        # bus present + agent registered == the exact live condition under
        # which the pre-fix code routed to the (broken) agent stream bridge.
        agent = _make_agent(content="GENERIC AGENT FILLER")
        app = create_app(engine, "test-model", agent=agent, bus=EventBus())
        client = TestClient(app)

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "user", "content": "Weather in Paris? Use get_weather."}
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "parameters": {
                                "type": "object",
                                "properties": {"city": {"type": "string"}},
                                "required": ["city"],
                            },
                        },
                    }
                ],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")

        tool_call_names: list[str] = []
        finish_reasons: list[str] = []
        collected_content = ""
        for line in resp.text.strip().split("\n"):
            if not line.startswith("data:") or "[DONE]" in line:
                continue
            data = json.loads(line[5:].strip())
            choice = data.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            for tc in delta.get("tool_calls") or []:
                tool_call_names.append(tc["function"]["name"])
            if delta.get("content"):
                collected_content += delta["content"]
            if choice.get("finish_reason"):
                finish_reasons.append(choice["finish_reason"])

        # The real tool_call must be streamed through to the client.
        assert "get_weather" in tool_call_names
        # finish_reason must signal tool_calls, not a plain stop.
        assert "tool_calls" in finish_reasons
        # The agent's filler must NOT have been streamed...
        assert "GENERIC AGENT FILLER" not in collected_content
        # ...and the agent must not have been invoked at all.
        assert not agent.run.called

    def test_finish_reason_default(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "Hello"}],
            },
        )
        data = resp.json()
        assert data["choices"][0]["finish_reason"] == "stop"


# ---------------------------------------------------------------------------
# Identity system-prompt injection (#540)
# ---------------------------------------------------------------------------


def _make_capturing_engine(captured: list):
    """Like ``_make_engine`` but records the messages each path receives.

    ``engine.generate`` is a MagicMock so ``call_args`` works on the
    direct/non-stream path. ``engine.stream`` / ``engine.stream_full`` are
    plain async-generator FUNCTIONS, so they capture their ``messages``
    argument into the shared *captured* list from inside the generator body
    (``call_args`` does not apply to plain functions).
    """
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.health.return_value = True
    engine.list_models.return_value = ["test-model"]
    engine.generate.return_value = {
        "content": "ok",
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
        "model": "test-model",
        "finish_reason": "stop",
    }

    async def mock_stream(messages, *, model, temperature=0.7, max_tokens=1024, **kw):
        captured.append(messages)
        for token in ["Hello", " ", "world"]:
            yield token

    async def mock_stream_full(
        messages, *, model, temperature=0.7, max_tokens=1024, **kw
    ):
        from openjarvis.engine._stubs import StreamChunk

        captured.append(messages)
        yield StreamChunk(content="ok", finish_reason="stop")

    engine.stream = mock_stream
    engine.stream_full = mock_stream_full
    return engine


class TestIdentityPromptInjection:
    """Regression for #540.

    The desktop UI posts only user/assistant turns to the
    OpenAI-compatible ``/v1/chat/completions`` endpoint, so the engine never
    saw OpenJarvis's identity system prompt and the model answered from its
    training identity ("I'm Claude", "I am Qwen", ...). The engine-direct
    server handlers must now inject ``agent.default_system_prompt`` whenever
    the client omits a system message — and must NOT inject a second one when
    the client already supplies their own.
    """

    def test_stream_injects_identity_when_absent(self):
        captured: list = []
        engine = _make_capturing_engine(captured)
        client = TestClient(create_app(engine, "test-model"))

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "who are you?"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        # Drain the stream so the generator body runs and records messages.
        _ = resp.text
        assert captured, "engine.stream was never called"
        msgs = captured[-1]
        assert msgs[0].role.value == "system"
        assert "OpenJarvis" in msgs[0].content

    def test_stream_no_double_injection_when_client_supplies_system(self):
        captured: list = []
        engine = _make_capturing_engine(captured)
        client = TestClient(create_app(engine, "test-model"))

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "Be terse."},
                    {"role": "user", "content": "who are you?"},
                ],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        _ = resp.text
        msgs = captured[-1]
        system_msgs = [m for m in msgs if m.role.value == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "Be terse."

    def test_direct_injects_identity_when_absent(self):
        captured: list = []
        engine = _make_capturing_engine(captured)
        # No agent -> non-stream request goes through _handle_direct.
        client = TestClient(create_app(engine, "test-model"))

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "who are you?"}],
            },
        )
        assert resp.status_code == 200
        assert engine.generate.called
        msgs = engine.generate.call_args.args[0]
        assert msgs[0].role.value == "system"
        assert "OpenJarvis" in msgs[0].content

    def test_direct_no_double_injection_when_client_supplies_system(self):
        captured: list = []
        engine = _make_capturing_engine(captured)
        client = TestClient(create_app(engine, "test-model"))

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "Be terse."},
                    {"role": "user", "content": "who are you?"},
                ],
            },
        )
        assert resp.status_code == 200
        msgs = engine.generate.call_args.args[0]
        system_msgs = [m for m in msgs if m.role.value == "system"]
        assert len(system_msgs) == 1
        assert system_msgs[0].content == "Be terse."

    def test_stream_tools_injects_identity_when_absent(self):
        captured: list = []
        engine = _make_capturing_engine(captured)
        client = TestClient(create_app(engine, "test-model"))

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "who are you?"}],
                "tools": [{"type": "function", "function": {"name": "calc"}}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        _ = resp.text
        assert captured, "engine.stream_full was never called"
        msgs = captured[-1]
        assert msgs[0].role.value == "system"
        assert "OpenJarvis" in msgs[0].content


# ---------------------------------------------------------------------------
# Models endpoint tests
# ---------------------------------------------------------------------------


class TestModelsEndpoint:
    def test_list_models(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 1
        assert data["data"][0]["id"] == "test-model"

    def test_model_object_format(self, client):
        resp = client.get("/v1/models")
        data = resp.json()
        model = data["data"][0]
        assert model["object"] == "model"
        assert "owned_by" in model

    def test_multiple_models(self):
        engine = _make_engine(models=["model-a", "model-b", "model-c"])
        app = create_app(engine, "model-a")
        client = TestClient(app)
        resp = client.get("/v1/models")
        data = resp.json()
        assert len(data["data"]) == 3


# ---------------------------------------------------------------------------
# Health endpoint tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    def test_healthy(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_unhealthy(self):
        engine = _make_engine()
        engine.health.return_value = False
        app = create_app(engine, "test-model")
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# App creation tests
# ---------------------------------------------------------------------------


class TestCreateApp:
    def test_app_state(self):
        engine = _make_engine()
        app = create_app(engine, "test-model")
        assert app.state.engine is engine
        assert app.state.model == "test-model"

    def test_app_with_agent(self):
        engine = _make_engine()
        agent = _make_agent()
        app = create_app(engine, "test-model", agent=agent)
        assert app.state.agent is agent

    def test_app_without_agent(self):
        engine = _make_engine()
        app = create_app(engine, "test-model")
        assert app.state.agent is None


# ---------------------------------------------------------------------------
# Trace recording — regression coverage for the empty-traces.db bug
# (TraceCollector was never wired into the server chat endpoints).
# ---------------------------------------------------------------------------


class TestTraceRecording:
    def test_agent_completion_creates_trace(self):
        """A non-streaming agent completion records exactly one trace.

        The collector is the single writer: it saves directly and also
        publishes TRACE_COMPLETE, but the store is NOT subscribed to the bus
        (see server/app.py), so the trace is persisted exactly once. If the
        store were re-subscribed, the collector's second save would raise
        IntegrityError on the trace_id primary key and the request would 500 —
        so asserting 200 + count == 1 guards that double-save regression.
        """
        from openjarvis.core.events import EventBus

        engine = _make_engine()
        agent = _make_agent(content="traced reply")
        app = create_app(
            engine,
            "test-model",
            agent=agent,
            bus=EventBus(record_history=False),
        )
        store = app.state.trace_store
        assert store is not None, "traces enabled by default → store should exist"
        assert store.count() == 0

        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "What is 2+2?"}],
            },
        )
        assert resp.status_code == 200
        assert resp.json()["choices"][0]["message"]["content"] == "traced reply"

        assert store.count() == 1  # not 2 — double-save must be idempotent
        trace = store.list_traces(limit=1)[0]
        assert trace.query == "What is 2+2?"
        assert trace.result == "traced reply"

    def test_streaming_completion_creates_trace(self):
        """A streamed completion (no agent) records the assembled response."""
        engine = _make_engine()
        app = create_app(engine, "test-model")
        store = app.state.trace_store
        assert store is not None
        assert store.count() == 0

        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "test-model",
                "messages": [{"role": "user", "content": "stream please"}],
                "stream": True,
            },
        )
        assert resp.status_code == 200
        # Drain the SSE body so the streaming generator runs to completion.
        assert "data:" in resp.text

        assert store.count() == 1
        trace = store.list_traces(limit=1)[0]
        assert trace.query == "stream please"
        # _make_engine streams "Hello", " ", "world".
        assert trace.result == "Hello world"
