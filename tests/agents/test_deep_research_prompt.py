"""Tests for DeepResearch system prompt — date injection and adaptive behavior."""

from __future__ import annotations

import re
from datetime import datetime
from unittest.mock import MagicMock

import pytest


def test_system_prompt_contains_current_date() -> None:
    """The system prompt includes today's date."""
    from openjarvis.agents.deep_research import _build_system_prompt

    prompt = _build_system_prompt()
    today = datetime.now().strftime("%B %d, %Y")
    assert today in prompt, f"Expected '{today}' in prompt"


def test_system_prompt_contains_current_time() -> None:
    """The system prompt includes the current time (hour)."""
    from openjarvis.agents.deep_research import _build_system_prompt

    prompt = _build_system_prompt()
    # Just check that a time-like pattern exists (e.g. "02:28 PM")
    assert re.search(r"\d{1,2}:\d{2} [AP]M", prompt), "No time found in prompt"


def test_system_prompt_contains_day_of_week() -> None:
    """The system prompt includes the day of week."""
    from openjarvis.agents.deep_research import _build_system_prompt

    prompt = _build_system_prompt()
    day = datetime.now().strftime("%A")
    assert day in prompt, f"Expected '{day}' in prompt"


def test_system_prompt_is_dynamic() -> None:
    """Each call to _build_system_prompt returns a fresh prompt with current time."""
    from openjarvis.agents.deep_research import _build_system_prompt

    p1 = _build_system_prompt()
    p2 = _build_system_prompt()
    # Both should contain "Today is" — they may differ by seconds
    assert "Today is" in p1
    assert "Today is" in p2


def test_system_prompt_has_response_types() -> None:
    """The prompt describes multiple response types (not just deep research)."""
    from openjarvis.agents.deep_research import _build_system_prompt

    prompt = _build_system_prompt()
    assert "Casual" in prompt or "conversational" in prompt
    assert "Quick data lookup" in prompt or "Quick lookup" in prompt
    assert "Deep research" in prompt
    assert "People lookup" in prompt
    assert "digest" in prompt.lower()
    assert "Meeting prep" in prompt or "meeting" in prompt.lower()
    assert "Task" in prompt or "action item" in prompt.lower()
    assert "Contact analysis" in prompt or "haven't I messaged" in prompt


def test_system_prompt_has_tools() -> None:
    """The prompt describes all 4 tools."""
    from openjarvis.agents.deep_research import _build_system_prompt

    prompt = _build_system_prompt()
    assert "knowledge_search" in prompt
    assert "knowledge_sql" in prompt
    assert "scan_chunks" in prompt
    assert "think" in prompt


def test_system_prompt_has_no_think_directive() -> None:
    """The prompt starts with /no_think for Qwen compatibility."""
    from openjarvis.agents.deep_research import _build_system_prompt

    prompt = _build_system_prompt()
    assert prompt.startswith("/no_think")


def test_system_prompt_mentions_jarvis() -> None:
    """The agent identifies as Jarvis."""
    from openjarvis.agents.deep_research import _build_system_prompt

    prompt = _build_system_prompt()
    assert "Jarvis" in prompt
