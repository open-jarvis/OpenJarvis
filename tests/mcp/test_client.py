"""Tests for the MCP client."""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import CancelledError, ThreadPoolExecutor
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from openjarvis.mcp.client import MCPClient
from openjarvis.mcp.protocol import MCPError, MCPResponse
from openjarvis.mcp.server import MCPServer
from openjarvis.mcp.transport import InProcessTransport, MCPTransport
from openjarvis.tools._stubs import ToolSpec
from openjarvis.tools.calculator import CalculatorTool
from openjarvis.tools.think import ThinkTool


@pytest.fixture
def client():
    """MCP client connected via in-process transport."""
    server = MCPServer([CalculatorTool(), ThinkTool()])
    transport = InProcessTransport(server)
    return MCPClient(transport)


class TestMCPClient:
    def test_initialize_handshake(self, client):
        result = client.initialize()
        assert "protocolVersion" in result
        assert "serverInfo" in result
        assert result["serverInfo"]["name"] == "openjarvis"
        assert client._initialized is True

    def test_initialize_sets_capabilities(self, client):
        client.initialize()
        assert "tools" in client._capabilities

    def test_list_tools(self, client):
        tools = client.list_tools()
        assert len(tools) == 2
        assert all(isinstance(t, ToolSpec) for t in tools)
        names = {t.name for t in tools}
        assert "calculator" in names
        assert "think" in names

    def test_list_tools_have_descriptions(self, client):
        tools = client.list_tools()
        for t in tools:
            assert t.description  # non-empty

    def test_list_tools_have_parameters(self, client):
        tools = client.list_tools()
        for t in tools:
            assert "properties" in t.parameters

    def test_call_tool_calculator(self, client):
        result = client.call_tool("calculator", {"expression": "10 + 5"})
        assert result["isError"] is False
        assert "15" in result["content"][0]["text"]

    def test_call_tool_think(self, client):
        result = client.call_tool("think", {"thought": "Reasoning step."})
        assert result["isError"] is False
        assert "Reasoning step." in result["content"][0]["text"]

    def test_call_tool_error(self, client):
        # Rust calculator (meval) returns inf for 1/0 rather than an error
        result = client.call_tool("calculator", {"expression": "1/0"})
        assert result["isError"] is False
        assert "inf" in result["content"][0]["text"]

    def test_call_unknown_tool_raises(self, client):
        with pytest.raises(MCPError) as exc_info:
            client.call_tool("nonexistent", {})
        assert "Unknown tool" in str(exc_info.value)

    def test_client_server_roundtrip(self, client):
        """Full lifecycle: initialize -> list -> call -> close."""
        info = client.initialize()
        assert "serverInfo" in info

        tools = client.list_tools()
        assert len(tools) >= 1

        result = client.call_tool("calculator", {"expression": "7 * 8"})
        assert "56" in result["content"][0]["text"]

        client.close()

    def test_close(self, client):
        client.close()
        # Close should not raise even if called multiple times
        client.close()

    def test_incremental_ids(self, client):
        """Each request should get a unique ID."""
        id1 = client._next_id()
        id2 = client._next_id()
        assert id2 > id1

    def test_call_tool_with_no_arguments(self, client):
        """Calling a tool with no arguments passes empty dict."""
        result = client.call_tool("think")
        # Think tool echoes empty thought
        assert result["isError"] is False

    def test_shared_client_serializes_transport_round_trips(self):
        """Concurrent agents cannot consume one another's MCP responses."""

        class _ConcurrencyProbeTransport:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def send(self, request):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                time.sleep(0.01)
                with self.lock:
                    self.active -= 1
                return MCPResponse(result={"tools": []}, id=request.id)

            def send_notification(self, request):
                return None

            def close(self):
                return None

        transport = _ConcurrencyProbeTransport()
        shared_client = MCPClient(transport)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: shared_client.list_tools(), range(24)))

        assert transport.max_active == 1

    def test_close_interrupts_blocked_request_and_rejects_queued_request(self):
        """Shutdown reaches the transport without waiting on an in-flight call."""

        class _BlockingTransport:
            def __init__(self):
                self.send_started = threading.Event()
                self.send_released = threading.Event()
                self.close_called = threading.Event()
                self.send_count = 0

            def send(self, request):
                self.send_count += 1
                self.send_started.set()
                self.send_released.wait()
                raise RuntimeError("transport closed")

            def send_notification(self, request):
                return None

            def close(self):
                self.close_called.set()
                self.send_released.set()

        transport = _BlockingTransport()
        shared_client = MCPClient(transport)

        with ThreadPoolExecutor(max_workers=3) as pool:
            blocked_request = pool.submit(shared_client.list_tools)
            assert transport.send_started.wait(timeout=1)

            queued_request = pool.submit(shared_client.list_tools)
            close_call = pool.submit(shared_client.close)

            try:
                close_reached_transport = transport.close_called.wait(timeout=1)
            finally:
                # Keep the test failure-safe against a regression that makes
                # close wait behind the blocked request.
                transport.send_released.set()

            close_call.result(timeout=1)
            assert close_reached_transport
            with pytest.raises(RuntimeError, match="transport closed"):
                blocked_request.result(timeout=1)
            with pytest.raises(RuntimeError, match="MCP client is closed"):
                queued_request.result(timeout=1)

        assert transport.send_count == 1

    def test_close_retries_transport_cleanup_after_failure(self):
        """A failed close keeps requests blocked but permits cleanup retry."""

        transport = MagicMock()
        transport.close.side_effect = [RuntimeError("terminate timed out"), None]
        client = MCPClient(transport)

        with pytest.raises(RuntimeError, match="terminate timed out"):
            client.close()
        with pytest.raises(RuntimeError, match="MCP client is closed"):
            client.list_tools()

        client.close()
        client.close()

        assert transport.close.call_count == 2

    def test_in_process_transport_is_not_routed_through_the_sdk(self, client):
        assert client._external is False


class _FakeRuntime:
    """Stand-in for the official-SDK runtime owned by external transports."""

    instances: list[_FakeRuntime] = []

    def __init__(self, transport):
        self.transport = transport
        self.closes = 0
        self.cancels = 0
        self.calls: list[tuple[str, dict]] = []
        _FakeRuntime.instances.append(self)

    def cancel_active_call(self):
        self.cancels += 1

    def initialize(self):
        return {
            "protocolVersion": "2025-06-18",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "playwright-mcp", "version": "0.0.79"},
        }

    def list_tools(self):
        return [
            {
                "name": "browser_snapshot",
                "description": "Capture the accessibility tree",
                "inputSchema": {"type": "object", "properties": {}},
                "annotations": {"readOnlyHint": True},
            }
        ]

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments or {}))
        return {"content": [{"type": "text", "text": "button: Save"}], "isError": False}

    def close(self):
        self.closes += 1


class TestMCPClientExternalTransport:
    """External transports must reach the SDK runtime through the same facade."""

    @pytest.fixture
    def external_client(self, monkeypatch):
        from openjarvis.mcp.transport import StdioTransport

        _FakeRuntime.instances.clear()
        monkeypatch.setattr("openjarvis.mcp.runtime.MCPRuntime", _FakeRuntime)
        transport = StdioTransport(["npx", "-y", "@playwright/mcp@0.0.79"])
        return MCPClient(transport, server_name="playwright")

    def test_external_transport_is_detected(self, external_client):
        assert external_client._external is True

    def test_initialize_uses_the_sdk_runtime(self, external_client):
        result = external_client.initialize()
        assert result["serverInfo"]["name"] == "playwright-mcp"
        assert external_client._initialized is True
        assert external_client._capabilities == {"tools": {}}

    def test_list_tools_keeps_toolspec_mapping(self, external_client):
        specs = external_client.list_tools()
        assert [spec.name for spec in specs] == ["browser_snapshot"]
        assert specs[0].timeout_seconds == 600.0
        assert specs[0].metadata["mcp"] == {
            "server": "playwright",
            "annotations": {"readOnlyHint": True},
        }

    def test_call_tool_returns_the_standard_result(self, external_client):
        result = external_client.call_tool("browser_click", {"ref": "e17"})
        assert result["isError"] is False
        assert result["content"][0]["text"] == "button: Save"
        assert _FakeRuntime.instances[-1].calls == [("browser_click", {"ref": "e17"})]

    def test_one_runtime_is_shared_across_calls(self, external_client):
        external_client.initialize()
        external_client.list_tools()
        external_client.call_tool("browser_snapshot")
        assert len(_FakeRuntime.instances) == 1

    def test_call_tool_registers_cancellation_for_the_active_call_only(
        self, external_client, monkeypatch
    ):
        registered: list[object] = []
        unregistered: list[object] = []

        def _register(callback):
            registered.append(callback)
            return lambda: unregistered.append(callback)

        monkeypatch.setattr(
            "openjarvis.agents._stubs.register_agent_worker_cancellation", _register
        )
        external_client.list_tools()
        assert registered == []

        external_client.call_tool("browser_click", {"ref": "e17"})
        runtime = _FakeRuntime.instances[-1]
        assert registered == [runtime.cancel_active_call]
        assert unregistered == registered  # released once the call returned

    def test_close_is_idempotent_and_closes_the_runtime(self, external_client):
        external_client.initialize()
        external_client.close()
        external_client.close()
        assert _FakeRuntime.instances[-1].closes == 1


class _CancellableSession:
    """Fake SDK session whose ``call_tool`` parks until the test releases it."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.call_started = threading.Event()
        self._release: asyncio.Event | None = None

    async def __aenter__(self):
        self._release = asyncio.Event()
        self.entered.set()
        return self

    async def __aexit__(self, *exc):
        return False

    async def initialize(self):
        return SimpleNamespace(model_dump=lambda **_: {"capabilities": {}})

    async def list_tools(self, cursor=None):
        return SimpleNamespace(tools=[], nextCursor=None)

    async def call_tool(self, name, arguments, read_timeout_seconds=None):
        self.call_started.set()
        assert self._release is not None
        await self._release.wait()
        return SimpleNamespace(model_dump=lambda **_: {"isError": False})


class _SDKTransportDouble(MCPTransport):
    """External transport: implements ``sdk_client``, never ``send``."""

    def sdk_client(self):
        @asynccontextmanager
        async def _streams():
            yield (None, None)

        return _streams()


def test_external_call_tool_is_cancelled_only_by_its_own_lease(monkeypatch):
    """Barge-in on one agent must not drop another agent's in-flight tool call.

    This is the seam Task 4's scoped cancellation was built for and had no
    caller until external servers moved onto the SDK session: ``call_tool``
    registers ``cancel_active_call`` with the *calling* worker lease, and the
    runtime files the in-flight future under that lease's scope.
    """
    from openjarvis.agents._stubs import _RUN_WORKER_LEASE, AgentWorkerLease
    from openjarvis.mcp.runtime import MCPRuntime

    session = _CancellableSession()

    class _RuntimeWithFakeSession(MCPRuntime):
        def __init__(self, transport):
            super().__init__(transport, session_factory=lambda *a, **k: session)

    monkeypatch.setattr("openjarvis.mcp.runtime.MCPRuntime", _RuntimeWithFakeSession)

    caller_lease = AgentWorkerLease()
    other_lease = AgentWorkerLease()
    client = MCPClient(_SDKTransportDouble(), server_name="playwright")
    assert client._external is True

    outcome: list[BaseException | dict] = []

    def _in_lease(lease, function):
        def _run():
            token = _RUN_WORKER_LEASE.set(lease)
            try:
                function()
            finally:
                _RUN_WORKER_LEASE.reset(token)

        return _run

    def _call():
        try:
            outcome.append(client.call_tool("browser_click", {"ref": "e17"}))
        except BaseException as exc:  # noqa: BLE001 — recorded, then asserted
            outcome.append(exc)

    worker = threading.Thread(target=_in_lease(caller_lease, _call), daemon=True)
    worker.start()
    try:
        assert session.call_started.wait(timeout=5)

        # Another agent's caller walks away. Its lease holds no callback for
        # this call, and resolving the scope from its context finds no future.
        other = threading.Thread(
            target=_in_lease(other_lease, other_lease._signal_cancelled), daemon=True
        )
        other.start()
        other.join(timeout=5)
        assert not worker.join(timeout=0.2) and worker.is_alive()
        assert outcome == []

        # The owning caller barges in — this call, and only now, is dropped.
        barge = threading.Thread(
            target=_in_lease(caller_lease, caller_lease._signal_cancelled), daemon=True
        )
        barge.start()
        barge.join(timeout=5)
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert isinstance(outcome[0], (asyncio.CancelledError, CancelledError))
    finally:
        client.close()
