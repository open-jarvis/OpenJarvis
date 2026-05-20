"""Unit tests for the prompt middleware chain."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from openjarvis.agents.prompt_middleware import (
    DateTimeInjector,
    apply_chain,
    build_default_middleware,
)


def _fixed_clock(value: datetime):
    def _clock() -> datetime:
        return value
    return _clock


def test_datetime_injector_appends_note_to_existing_prompt() -> None:
    injector = DateTimeInjector(
        timezone="UTC",
        clock=_fixed_clock(datetime(2026, 5, 20, 9, 30)),
    )
    out = injector("你是 Jarvis。")
    assert out.startswith("你是 Jarvis。")
    assert "2026-05-20" in out
    assert "09:30" in out
    assert "星期三" in out


def test_datetime_injector_skips_when_prompt_is_none() -> None:
    """When upstream supplied a SYSTEM message we must not stack another one."""
    injector = DateTimeInjector(timezone="UTC")
    assert injector(None) is None


def test_datetime_injector_strips_leading_newlines_on_empty_prompt() -> None:
    injector = DateTimeInjector(
        timezone="UTC",
        clock=_fixed_clock(datetime(2026, 5, 20, 9, 30)),
    )
    out = injector("")
    assert out is not None
    assert not out.startswith("\n")


def test_build_default_middleware_respects_inject_datetime_flag() -> None:
    """When all injectors are disabled the chain is empty."""
    cfg = SimpleNamespace(
        agent=SimpleNamespace(
            inject_datetime=False,
            datetime_timezone="UTC",
            inject_profile=False,
            inject_tool_affinity=False,
        ),
    )
    assert build_default_middleware(cfg) == []


def test_build_default_middleware_includes_datetime_when_enabled() -> None:
    cfg = SimpleNamespace(
        agent=SimpleNamespace(
            inject_datetime=True,
            datetime_timezone="UTC",
            inject_profile=False,
            inject_tool_affinity=False,
        ),
    )
    chain = build_default_middleware(cfg)
    assert len(chain) == 1
    assert isinstance(chain[0], DateTimeInjector)
    assert chain[0].timezone == "UTC"


def test_apply_chain_runs_in_order() -> None:
    def upper(prompt):
        return None if prompt is None else prompt.upper()

    def exclaim(prompt):
        return None if prompt is None else f"{prompt}!"

    assert apply_chain("hi", [upper, exclaim]) == "HI!"
    assert apply_chain(None, [upper, exclaim]) is None
