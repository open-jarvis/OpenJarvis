from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.agents.loop_guard import LoopGuard, LoopGuardConfig, LoopVerdict


def test_warn_before_block_first_cycle_warns():
    config = LoopGuardConfig(
        enabled=True,
        max_identical_calls=2,
        warn_before_block=True,
    )
    guard = LoopGuard(config)
    # Simulate the Rust backend blocking on the second identical call
    mock_rust = MagicMock()
    mock_rust.check.side_effect = [
        LoopVerdict(blocked=False, reason=""),
        LoopVerdict(blocked=True, reason="identical_calls:search"),
    ]
    guard._rust_impl = mock_rust
    guard.check_call("search", '{"q": "test"}')
    v2 = guard.check_call("search", '{"q": "test"}')
    assert not v2.blocked
    assert v2.warned


def test_warn_before_block_second_cycle_blocks():
    config = LoopGuardConfig(
        enabled=True,
        max_identical_calls=2,
        warn_before_block=True,
    )
    guard = LoopGuard(config)
    mock_rust = MagicMock()
    mock_rust.check.side_effect = [
        LoopVerdict(blocked=False, reason=""),
        LoopVerdict(blocked=True, reason="identical_calls:search"),
        LoopVerdict(blocked=False, reason=""),
        LoopVerdict(blocked=True, reason="identical_calls:search"),
    ]
    guard._rust_impl = mock_rust
    guard.check_call("search", '{"q": "test"}')
    v_warn = guard.check_call("search", '{"q": "test"}')
    assert v_warn.warned and not v_warn.blocked
    guard.check_call("search", '{"q": "test"}')
    v_block = guard.check_call("search", '{"q": "test"}')
    assert v_block.blocked
    assert not v_block.warned


def test_default_behavior_unchanged():
    config = LoopGuardConfig(
        enabled=True,
        max_identical_calls=2,
        warn_before_block=False,
    )
    guard = LoopGuard(config)
    mock_rust = MagicMock()
    mock_rust.check.side_effect = [
        LoopVerdict(blocked=False, reason=""),
        LoopVerdict(blocked=True, reason="identical_calls:search"),
    ]
    guard._rust_impl = mock_rust
    guard.check_call("search", '{"q": "test"}')
    v = guard.check_call("search", '{"q": "test"}')
    assert v.blocked
    assert not v.warned


def test_python_identical_calls_warn_once_then_block():
    """Regression: reasons embed a running counter, so keying the warning on
    the raw reason made every repeat look like a new cycle and the guard never
    blocked. One warning per loop, then block."""
    config = LoopGuardConfig(
        enabled=True,
        max_identical_calls=3,
        warn_before_block=True,
    )
    guard = LoopGuard(config)
    guard._rust_impl = None  # force the pure-Python path

    verdicts = [guard.check_call("search", '{"q": "same"}') for _ in range(8)]

    assert not any(v.blocked or v.warned for v in verdicts[:3])
    assert verdicts[3].warned and not verdicts[3].blocked
    assert all(v.blocked for v in verdicts[4:])


def test_python_poll_budget_warns_once_then_blocks():
    config = LoopGuardConfig(
        enabled=True,
        max_identical_calls=100,
        poll_tool_budget=2,
        warn_before_block=True,
    )
    guard = LoopGuard(config)
    guard._rust_impl = None

    verdicts = [guard.check_call("poll", f'{{"n": {i}}}') for i in range(6)]

    assert verdicts[2].warned and not verdicts[2].blocked
    assert all(v.blocked for v in verdicts[3:])


def test_warning_is_tracked_per_tool():
    config = LoopGuardConfig(
        enabled=True,
        max_identical_calls=1,
        warn_before_block=True,
    )
    guard = LoopGuard(config)
    guard._rust_impl = None

    guard.check_call("a", "{}")
    assert guard.check_call("a", "{}").warned
    guard.check_call("b", "{}")
    # tool "b" has its own first warning, it is not blocked by a's history
    assert guard.check_call("b", "{}").warned
