"""The user's time zone reaches system prompts."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from openjarvis.core.config import SystemPromptConfig
from openjarvis.prompt.builder import SystemPromptBuilder
from openjarvis.prompt.time_context import (
    current_time_section,
    reset_request_timezone,
    set_request_timezone,
    valid_timezone,
)

NOW = datetime(2026, 11, 6, 8, 54, tzinfo=timezone.utc)


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
    assert "Unless the user asks otherwise" in section
    assert "Preserve date-only values and all-day event dates" in section


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


@pytest.mark.parametrize("enabled", [True, False])
def test_time_settings_loaded_from_config(tmp_path, enabled):
    from openjarvis.core.config import load_config

    path = tmp_path / "config.toml"
    path.write_text(
        '[system_prompt]\ntimezone = "America/New_York"\n'
        f"include_current_time = {str(enabled).lower()}\n"
    )
    config = load_config(path)
    builder = SystemPromptBuilder("Jarvis", system_prompt_config=config.system_prompt)
    if enabled:
        assert "America/New_York" in builder.current_time_section()
    else:
        assert builder.build() == "Jarvis"


def test_background_runs_use_config_without_a_request() -> None:
    token = set_request_timezone("Africa/Cairo")
    reset_request_timezone(token)
    assert "Europe/Berlin" in current_time_section("Europe/Berlin", now=NOW)


@pytest.mark.parametrize(
    ("zone", "now", "offset", "local"),
    [
        (
            "America/New_York",
            datetime(2026, 7, 6, 8, 54, tzinfo=timezone.utc),
            "UTC-04:00",
            "2026-07-06 04:54",
        ),
        ("Asia/Kolkata", NOW, "UTC+05:30", "2026-11-06 14:24"),
        ("America/St_Johns", NOW, "UTC-03:30", "2026-11-06 05:24"),
    ],
)
def test_dst_and_fractional_offsets(zone, now, offset, local):
    section = current_time_section(zone, now=now)
    assert offset in section
    assert local in section
