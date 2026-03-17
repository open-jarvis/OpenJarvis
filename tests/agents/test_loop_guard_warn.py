from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.agents.loop_guard import LoopGuard, LoopGuardConfig, LoopVerdict


def test_warn_before_block_first_cycle_warns():
    config = LoopGuardConfig(
        enabled=True, max_identical_calls=2, warn_before_block=True,
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
        enabled=True, max_identical_calls=2, warn_before_block=True,
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
        enabled=True, max_identical_calls=2, warn_before_block=False,
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
