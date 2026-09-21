"""Tests for GuardrailsEngine."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields
from typing import Any, Sequence
from unittest.mock import MagicMock

import pytest

from openjarvis.core.events import EventBus, EventType
from openjarvis.core.types import Message, Role, ToolCall
from openjarvis.engine._stubs import StreamChunk
from openjarvis.security.guardrails import GuardrailsEngine, SecurityBlockError
from openjarvis.security.scanner import SecretScanner
from openjarvis.security.types import RedactionMode


def _make_mock_engine(response_content: str = "Hello!") -> MagicMock:
    """Create a mock InferenceEngine."""
    engine = MagicMock()
    engine.engine_id = "mock"
    engine.generate.return_value = {
        "content": response_content,
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        "model": "test-model",
        "finish_reason": "stop",
    }
    engine.list_models.return_value = ["model-a", "model-b"]
    engine.health.return_value = True
    return engine


class TestGuardrailsEngineWarnMode:
    def test_warn_mode_passes_through(self) -> None:
        """WARN mode passes through content but publishes event."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine("The key is sk-abc123def456ghi789jkl012")
        ge = GuardrailsEngine(mock, mode=RedactionMode.WARN, bus=bus)

        messages = [Message(role=Role.USER, content="tell me something")]
        result = ge.generate(messages, model="test")

        # Content should pass through unchanged
        assert result["content"] == "The key is sk-abc123def456ghi789jkl012"
        # Event should be published
        alerts = [e for e in bus.history if e.event_type == EventType.SECURITY_ALERT]
        assert len(alerts) >= 1

    def test_warn_mode_no_findings(self) -> None:
        """WARN mode with clean content — no events."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine("Just a normal response")
        ge = GuardrailsEngine(mock, mode=RedactionMode.WARN, bus=bus)

        messages = [Message(role=Role.USER, content="hello")]
        result = ge.generate(messages, model="test")

        assert result["content"] == "Just a normal response"
        alerts = [e for e in bus.history if e.event_type == EventType.SECURITY_ALERT]
        assert len(alerts) == 0


class TestGuardrailsEngineRedactMode:
    def test_redact_mode_redacts_output(self) -> None:
        """REDACT mode replaces sensitive content in output."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine("The key is sk-abc123def456ghi789jkl012")
        ge = GuardrailsEngine(mock, mode=RedactionMode.REDACT, bus=bus)

        messages = [Message(role=Role.USER, content="tell me")]
        result = ge.generate(messages, model="test")

        assert "sk-abc123" not in result["content"]
        assert "[REDACTED:" in result["content"]

    def test_redact_mode_clean_passthrough(self) -> None:
        """REDACT mode with clean content — no changes."""
        mock = _make_mock_engine("Hello there!")
        ge = GuardrailsEngine(mock, mode=RedactionMode.REDACT)

        messages = [Message(role=Role.USER, content="hi")]
        result = ge.generate(messages, model="test")

        assert result["content"] == "Hello there!"


class TestGuardrailsEngineBlockMode:
    def test_block_mode_raises(self) -> None:
        """BLOCK mode raises SecurityBlockError when findings in output."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine("The key is sk-abc123def456ghi789jkl012")
        ge = GuardrailsEngine(mock, mode=RedactionMode.BLOCK, bus=bus)

        messages = [Message(role=Role.USER, content="tell me")]
        with pytest.raises(SecurityBlockError):
            ge.generate(messages, model="test")

        blocks = [e for e in bus.history if e.event_type == EventType.SECURITY_BLOCK]
        assert len(blocks) >= 1

    def test_block_mode_clean_passthrough(self) -> None:
        """BLOCK mode with clean content — no exception."""
        mock = _make_mock_engine("All good!")
        ge = GuardrailsEngine(mock, mode=RedactionMode.BLOCK)

        messages = [Message(role=Role.USER, content="hi")]
        result = ge.generate(messages, model="test")
        assert result["content"] == "All good!"


class TestGuardrailsEngineInputScanning:
    def test_scan_input(self) -> None:
        """Input messages are scanned when scan_input=True."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine("OK")
        ge = GuardrailsEngine(
            mock,
            mode=RedactionMode.WARN,
            scan_input=True,
            bus=bus,
        )

        secret = "my key sk-abc123def456ghi789jkl012"
        messages = [Message(role=Role.USER, content=secret)]
        ge.generate(messages, model="test")

        alerts = [e for e in bus.history if e.event_type == EventType.SECURITY_ALERT]
        # Should detect the secret in input
        assert len(alerts) >= 1
        assert any(a.data.get("direction") == "input" for a in alerts)

    def test_redact_input_modifies_messages_sent_to_engine(
        self,
    ) -> None:
        """REDACT mode on input must send redacted messages."""
        mock = _make_mock_engine("OK")
        ge = GuardrailsEngine(
            mock,
            mode=RedactionMode.REDACT,
            scan_input=True,
        )

        secret = "my key sk-abc123def456ghi789jkl012"
        messages = [Message(role=Role.USER, content=secret)]
        ge.generate(messages, model="test")

        # Engine should receive redacted content
        call_args = mock.generate.call_args
        sent_messages = call_args[0][0]
        assert "sk-abc123" not in sent_messages[0].content
        assert "[REDACTED:" in sent_messages[0].content

    def test_scan_input_disabled(self) -> None:
        """Input messages are not scanned when scan_input=False."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine("OK")
        ge = GuardrailsEngine(
            mock,
            mode=RedactionMode.WARN,
            scan_input=False,
            bus=bus,
        )

        secret = "my key sk-abc123def456ghi789jkl012"
        messages = [Message(role=Role.USER, content=secret)]
        ge.generate(messages, model="test")

        alerts = [e for e in bus.history if e.event_type == EventType.SECURITY_ALERT]
        # No input scanning, so no alerts about input
        input_alerts = [a for a in alerts if a.data.get("direction") == "input"]
        assert len(input_alerts) == 0


class TestGuardrailsEngineDelegation:
    def test_delegates_close(self) -> None:
        mock = _make_mock_engine()
        ge = GuardrailsEngine(mock)

        ge.close()

        mock.close.assert_called_once()

    def test_delegates_list_models(self) -> None:
        """list_models() delegates to wrapped engine."""
        mock = _make_mock_engine()
        ge = GuardrailsEngine(mock)

        models = ge.list_models()
        assert models == ["model-a", "model-b"]
        mock.list_models.assert_called_once()

    def test_delegates_health(self) -> None:
        """health() delegates to wrapped engine."""
        mock = _make_mock_engine()
        ge = GuardrailsEngine(mock)

        assert ge.health() is True
        mock.health.assert_called_once()

    def test_engine_id_delegates(self) -> None:
        """engine_id property delegates to wrapped engine."""
        mock = _make_mock_engine()
        ge = GuardrailsEngine(mock)

        assert ge.engine_id == "mock"


class TestGuardrailsEngineCleanPassthrough:
    def test_clean_passthrough(self) -> None:
        """No findings → content passes through unchanged in all modes."""
        for mode in RedactionMode:
            mock = _make_mock_engine("Nothing special here")
            ge = GuardrailsEngine(mock, mode=mode)

            messages = [Message(role=Role.USER, content="hello")]
            result = ge.generate(messages, model="test")
            expected = "Nothing special here"
            assert result["content"] == expected, f"mode={mode}"


# ---------------------------------------------------------------------------
# stream() tests
# ---------------------------------------------------------------------------


async def _async_token_iter(tokens):
    for t in tokens:
        yield t


_SECRET = "my key sk-abc123def456ghi789jkl012"
_METHODS = ["generate", "stream", "stream_full"]


async def _invoke(
    guarded: GuardrailsEngine,
    method: str,
    messages: Sequence[Message],
    **kwargs: Any,
) -> Any:
    if method == "generate":
        return guarded.generate(messages, **kwargs)
    return [item async for item in getattr(guarded, method)(messages, **kwargs)]


def _recording_engine() -> MagicMock:
    engine = _make_mock_engine("OK")
    engine.stream.side_effect = lambda *a, **kw: _async_token_iter(["OK"])
    engine.stream_full.side_effect = lambda *a, **kw: _async_token_iter(
        [StreamChunk(content="OK"), StreamChunk(finish_reason="stop")]
    )
    return engine


@pytest.mark.asyncio
@pytest.mark.parametrize("method", _METHODS)
class TestGuardrailsInputPolicy:
    async def test_block_before_backend(self, method: str) -> None:
        bus = EventBus(record_history=True)
        backend = _recording_engine()
        guarded = GuardrailsEngine(
            backend, mode=RedactionMode.BLOCK, scan_output=False, bus=bus
        )
        messages = [Message(Role.USER, "hello"), Message(Role.TOOL, _SECRET)]
        if method == "generate":
            with pytest.raises(SecurityBlockError, match="blocked input"):
                guarded.generate(messages, model="test")
        else:
            iterator = getattr(guarded, method)(messages, model="test")
            assert not bus.history
            getattr(backend, method).assert_not_called()
            with pytest.raises(SecurityBlockError, match="blocked input"):
                await iterator.__anext__()
        getattr(backend, method).assert_not_called()
        assert len(bus.history) == 1
        event = bus.history[0]
        assert event.event_type == EventType.SECURITY_BLOCK
        assert event.data["direction"] == "input"
        assert event.data["mode"] == "block"
        assert event.data["findings"][0]["pattern"] == "openai_key"

    @pytest.mark.parametrize("mode", [RedactionMode.WARN, RedactionMode.REDACT])
    async def test_findings_preserve_messages_and_arguments(
        self, method: str, mode: RedactionMode
    ) -> None:
        bus = EventBus(record_history=True)
        backend = _recording_engine()
        guarded = GuardrailsEngine(backend, mode=mode, scan_output=False, bus=bus)
        messages = tuple(
            Message(
                role=role,
                content=_SECRET,
                name="speaker",
                tool_calls=[ToolCall("call-1", "lookup", "{}")],
                tool_call_id="call-1",
                metadata={"nested": ["value"]},
                images=["aGVsbG8="],
            )
            for role in Role
        )
        original = deepcopy(messages)
        call = getattr(backend, method)
        original_effect = call.side_effect

        def receive(*args: Any, **kwargs: Any) -> Any:
            # All input events must already exist when the backend is called.
            assert len(bus.history) == len(messages)
            if original_effect:
                return original_effect(*args, **kwargs)
            return call.return_value

        call.side_effect = receive
        kwargs = dict(model="test", temperature=0.2, max_tokens=17, stop=["END"])
        await _invoke(guarded, method, messages, **kwargs)
        assert call.call_count == 1
        assert call.call_args.kwargs == kwargs
        sent = call.call_args.args[0]
        assert len(sent) == len(messages)
        assert messages == original
        for before, after in zip(messages, sent):
            assert after is not before
            assert after.content == (
                _SECRET
                if mode == RedactionMode.WARN
                else "my key [REDACTED:openai_key]"
            )
            for field in fields(Message):
                if field.name != "content":
                    assert getattr(after, field.name) is getattr(before, field.name)
        for event in bus.history:
            assert event.event_type == EventType.SECURITY_ALERT
            assert event.data["direction"] == "input"
            assert event.data["mode"] == mode.value
            assert event.data["findings"] == [
                {
                    "pattern": "openai_key",
                    "threat": "critical",
                    "description": "OpenAI API key",
                }
            ]

    @pytest.mark.parametrize("mode", list(RedactionMode))
    async def test_disabled_input_scan(self, method: str, mode: RedactionMode) -> None:
        backend = _recording_engine()
        scanner = MagicMock()
        bus = EventBus(record_history=True)
        guarded = GuardrailsEngine(
            backend,
            scanners=[scanner],
            mode=mode,
            scan_input=False,
            scan_output=False,
            bus=bus,
        )
        messages = (Message(Role.USER, _SECRET),)
        await _invoke(guarded, method, messages, model="test")
        assert getattr(backend, method).call_args.args[0] is messages
        scanner.scan.assert_not_called()
        scanner.redact.assert_not_called()
        assert not bus.history

    @pytest.mark.parametrize("mode", list(RedactionMode))
    @pytest.mark.parametrize("case", ["empty", "clean", "no_scanners"])
    async def test_no_findings(
        self, method: str, mode: RedactionMode, case: str
    ) -> None:
        backend = _recording_engine()
        bus = EventBus(record_history=True)
        scanner = MagicMock(wraps=SecretScanner())
        messages = (
            ()
            if case == "empty"
            else (
                Message(Role.USER, _SECRET if case == "no_scanners" else "hello"),
                Message(Role.ASSISTANT, None),
                Message(Role.TOOL, ""),
            )
        )
        guarded = GuardrailsEngine(
            backend,
            scanners=[] if case == "no_scanners" else [scanner],
            mode=mode,
            scan_output=False,
            bus=bus,
        )
        await _invoke(guarded, method, messages, model="test")
        sent = getattr(backend, method).call_args.args[0]
        assert list(sent) == list(messages)
        assert all(a is b for a, b in zip(sent, messages))
        if case == "clean":
            scanner.scan.assert_called_once_with("hello")
        else:
            scanner.scan.assert_not_called()
        assert not bus.history


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["stream", "stream_full"])
@pytest.mark.parametrize("mode", list(RedactionMode))
async def test_stream_output_remains_post_hoc(method: str, mode: RedactionMode) -> None:
    bus = EventBus(record_history=True)
    backend = _recording_engine()
    expected = ["my key ", "sk-abc123def456ghi789jkl012"]
    if method == "stream_full":
        expected = [
            StreamChunk(content=expected[0]),
            StreamChunk(content=expected[1], tool_calls=[{"index": 0}]),
            StreamChunk(
                finish_reason="stop",
                usage={"total_tokens": 3},
                content_blocks=[{"type": "text", "text": "done"}],
                tool_results=[{"id": "call-1"}],
            ),
        ]
    getattr(backend, method).side_effect = lambda *a, **kw: _async_token_iter(expected)
    guarded = GuardrailsEngine(backend, mode=mode, bus=bus)
    iterator = getattr(guarded, method)([Message(Role.USER, "hello")], model="test")
    for item in expected:
        assert await iterator.__anext__() is item
        assert not bus.history
    with pytest.raises(StopAsyncIteration):
        await iterator.__anext__()
    assert len(bus.history) == 1
    event = bus.history[0]
    assert event.event_type == EventType.SECURITY_ALERT
    assert event.data["direction"] == "output"
    assert event.data["mode"] == f"{method}_post_hoc"
    assert event.data["findings"][0]["pattern"] == "openai_key"


@pytest.mark.asyncio
class TestGuardrailsEngineStream:
    async def test_stream_yields_tokens(self) -> None:
        """stream() yields all tokens from the wrapped engine."""
        mock = _make_mock_engine()
        mock.stream = lambda messages, **kw: _async_token_iter(
            ["Hello", " ", "world"],
        )
        ge = GuardrailsEngine(mock)

        messages = [Message(role=Role.USER, content="hi")]
        tokens = [t async for t in ge.stream(messages, model="test")]
        assert tokens == ["Hello", " ", "world"]

    async def test_stream_scans_output_post_hoc(self) -> None:
        """stream() publishes SECURITY_ALERT after yielding sensitive tokens."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine()
        mock.stream = lambda messages, **kw: _async_token_iter(
            ["The key is ", "sk-abc123def456ghi789jkl012"],
        )
        ge = GuardrailsEngine(mock, bus=bus)

        messages = [Message(role=Role.USER, content="show key")]
        _ = [t async for t in ge.stream(messages, model="test")]

        alerts = [e for e in bus.history if e.event_type == EventType.SECURITY_ALERT]
        assert len(alerts) >= 1
        assert alerts[0].data["direction"] == "output"
        assert alerts[0].data["mode"] == "stream_post_hoc"

    async def test_stream_publishes_alert_with_findings(self) -> None:
        """Alert event contains a non-empty findings list with 'pattern' key."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine()
        mock.stream = lambda messages, **kw: _async_token_iter(
            ["The key is ", "sk-abc123def456ghi789jkl012"],
        )
        ge = GuardrailsEngine(mock, bus=bus)

        messages = [Message(role=Role.USER, content="show key")]
        _ = [t async for t in ge.stream(messages, model="test")]

        alerts = [e for e in bus.history if e.event_type == EventType.SECURITY_ALERT]
        assert len(alerts) >= 1
        findings = alerts[0].data["findings"]
        assert isinstance(findings, list) and len(findings) > 0
        assert "pattern" in findings[0]

    async def test_stream_skips_scan_when_disabled(self) -> None:
        """No alert events when scan_output=False, even with sensitive content."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine()
        mock.stream = lambda messages, **kw: _async_token_iter(
            ["The key is ", "sk-abc123def456ghi789jkl012"],
        )
        ge = GuardrailsEngine(mock, scan_output=False, bus=bus)

        messages = [Message(role=Role.USER, content="show key")]
        _ = [t async for t in ge.stream(messages, model="test")]

        alerts = [e for e in bus.history if e.event_type == EventType.SECURITY_ALERT]
        assert len(alerts) == 0

    async def test_stream_clean_content_no_events(self) -> None:
        """Clean tokens produce no SECURITY_ALERT events."""
        bus = EventBus(record_history=True)
        mock = _make_mock_engine()
        mock.stream = lambda messages, **kw: _async_token_iter(
            ["Just", " a", " normal", " response"],
        )
        ge = GuardrailsEngine(mock, bus=bus)

        messages = [Message(role=Role.USER, content="hello")]
        _ = [t async for t in ge.stream(messages, model="test")]

        alerts = [e for e in bus.history if e.event_type == EventType.SECURITY_ALERT]
        assert len(alerts) == 0
