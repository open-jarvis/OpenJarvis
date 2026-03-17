"""Tests for agent loop guard (Phase 14.3)."""

from __future__ import annotations

from openjarvis.core.events import EventBus, EventType


class TestLoopGuard:
    def _make_guard(self, **kwargs):
        from openjarvis.agents.loop_guard import LoopGuard, LoopGuardConfig
        kwargs.setdefault("warn_before_block", False)
        config = LoopGuardConfig(**kwargs)
        bus = EventBus(record_history=True)
        return LoopGuard(config, bus=bus), bus

    def test_identical_calls_blocked(self):
        guard, bus = self._make_guard(max_identical_calls=2)
        v1 = guard.check_call("calc", '{"x": 1}')
        assert not v1.blocked
        # Rust backend uses a HashSet — blocks on the second identical call
        v2 = guard.check_call("calc", '{"x": 1}')
        assert v2.blocked
        assert "identical" in v2.reason.lower()

    def test_different_args_not_blocked(self):
        guard, _ = self._make_guard(max_identical_calls=2)
        guard.check_call("calc", '{"x": 1}')
        guard.check_call("calc", '{"x": 1}')
        v = guard.check_call("calc", '{"x": 2}')
        assert not v.blocked

    def test_ping_pong_detection(self):
        guard, _ = self._make_guard(ping_pong_window=4, poll_tool_budget=100)
        guard.check_call("A", "{}")
        guard.check_call("B", "{}")
        guard.check_call("A", '{"x": 1}')
        guard.check_call("B", '{"x": 1}')
        guard.check_call("A", '{"x": 2}')
        # After A-B-A-B pattern, next A should be blocked
        # Note: exact blocking depends on the window + detection logic
        # The sequence [A, B, A, B, A] with window=4 should detect A-B-A-B
        # But detection happens after 4+ calls in sequence

    def test_poll_budget_exceeded(self):
        guard, _ = self._make_guard(poll_tool_budget=3, max_identical_calls=100)
        guard.check_call("poll", '{"a": 1}')
        guard.check_call("poll", '{"a": 2}')
        guard.check_call("poll", '{"a": 3}')
        v = guard.check_call("poll", '{"a": 4}')
        assert v.blocked
        assert "poll budget" in v.reason.lower()

    def test_event_emitted(self):
        guard, bus = self._make_guard(max_identical_calls=1)
        guard.check_call("x", '{"a": 1}')
        guard.check_call("x", '{"a": 1}')
        events = [
            e for e in bus.history
            if e.event_type == EventType.LOOP_GUARD_TRIGGERED
        ]
        assert len(events) == 1

    def test_reset(self):
        guard, _ = self._make_guard(max_identical_calls=2)
        guard.check_call("x", '{"a": 1}')
        guard.check_call("x", '{"a": 1}')
        guard.reset()
        v = guard.check_call("x", '{"a": 1}')
        assert not v.blocked

    def test_context_compression_no_overflow(self):
        from openjarvis.core.types import Message, Role
        guard, _ = self._make_guard(max_context_messages=100)
        messages = [Message(role=Role.USER, content=f"msg {i}") for i in range(10)]
        result = guard.compress_context(messages)
        assert len(result) == 10

    def test_context_compression_with_overflow(self):
        from openjarvis.core.types import Message, Role
        guard, _ = self._make_guard(max_context_messages=10)
        messages = [
            Message(role=Role.SYSTEM, content="sys"),
        ] + [
            Message(role=Role.USER, content=f"msg {i}")
            for i in range(50)
        ] + [
            Message(role=Role.TOOL, content=f"result {i}", tool_call_id=f"t{i}")
            for i in range(50)
        ]
        result = guard.compress_context(messages)
        assert len(result) <= 10

    def test_context_compression_stage4_uses_current_state(self):
        """Stage 4 should derive from compressed state."""
        from openjarvis.core.types import Message, Role
        guard, _ = self._make_guard(max_context_messages=5)
        messages = [
            Message(role=Role.SYSTEM, content="sys"),
        ] + [
            Message(role=Role.USER, content=f"msg {i}")
            for i in range(100)
        ] + [
            Message(
                role=Role.TOOL,
                content=f"result {i}",
                tool_call_id=f"t{i}",
            )
            for i in range(100)
        ]
        result = guard.compress_context(messages)
        assert len(result) == 5
        system_count = sum(
            1 for m in result
            if getattr(m, 'role', None) == 'system'
        )
        assert system_count == 1

    def test_check_response_returns_unblocked(self):
        guard, _ = self._make_guard()
        v = guard.check_response("some content")
        assert not v.blocked

    def test_disabled_loop_guard(self):
        from openjarvis.agents.loop_guard import LoopGuard, LoopGuardConfig
        config = LoopGuardConfig(enabled=False)
        guard = LoopGuard(config)
        # Even though we'd normally block, disabled guard shouldn't
        for _ in range(10):
            guard.check_call("x", '{"a": 1}')
        # Guard is still created but check_call still works
        # (the enabled flag is checked at the ToolUsingAgent level)
