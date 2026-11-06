"""The user's time zone reaches system prompts."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from openjarvis.core.config import SystemPromptConfig
from openjarvis.prompt import time_context
from openjarvis.prompt.builder import SystemPromptBuilder
from openjarvis.prompt.time_context import (
    current_time_section,
    reset_request_timezone,
    set_request_timezone,
    valid_timezone,
)

NOW = datetime(2026, 11, 6, 8, 54, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_remembered_zone(monkeypatch):
    monkeypatch.setattr(time_context, "_last_client_timezone", None)


@pytest.fixture
def request_tz():
    tokens = []

    def _set(name):
        tokens.append(set_request_timezone(name))

    yield _set
    for token in reversed(tokens):
        reset_request_timezone(token)


def test_request_zone_converts_utc_to_local(request_tz) -> None:
    request_tz("Africa/Cairo")
    section = current_time_section(now=NOW)
    assert "Africa/Cairo (UTC+02:00)" in section
    assert "2026-11-06 10:54" in section
    assert "do not label them UTC" in section


def test_request_zone_beats_config(request_tz) -> None:
    request_tz("Asia/Tokyo")
    assert "Asia/Tokyo (UTC+09:00)" in current_time_section("Africa/Cairo", now=NOW)


def test_config_zone_used_without_request_zone() -> None:
    section = current_time_section("America/New_York", now=NOW)
    assert "America/New_York (UTC-05:00)" in section
    assert "2026-11-06 03:54" in section


def test_unknown_zones_are_ignored(request_tz) -> None:
    assert valid_timezone("Not/AZone") is None
    assert valid_timezone("../../etc/passwd") is None
    request_tz("Not/AZone")
    assert "Europe/Berlin" in current_time_section("Europe/Berlin", now=NOW)


def test_builder_appends_time_after_cached_prefix(tmp_path, request_tz) -> None:
    request_tz("Africa/Cairo")
    builder = SystemPromptBuilder(
        "You are Jarvis.", system_prompt_config=SystemPromptConfig()
    )
    prompt = builder.build()
    assert prompt.startswith("You are Jarvis.\n\n## Current Time")
    assert "Africa/Cairo" in prompt
    names = [s.name for s in builder.sections()]
    assert names[-1] == "current_time"


def test_builder_can_turn_time_off() -> None:
    cfg = SystemPromptConfig(include_current_time=False)
    builder = SystemPromptBuilder("You are Jarvis.", system_prompt_config=cfg)
    assert builder.build() == "You are Jarvis."
    assert builder.current_time_section() == ""


def test_background_runs_use_the_last_zone_the_ui_sent() -> None:
    token = set_request_timezone("Africa/Cairo")
    reset_request_timezone(token)
    # No request now (a queued or scheduled agent run): Cairo is remembered.
    assert "Africa/Cairo" in current_time_section("Europe/Berlin", now=NOW)
