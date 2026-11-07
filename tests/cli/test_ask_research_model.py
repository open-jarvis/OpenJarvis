"""Tests for the ``friday ask --research`` planner-model resolution."""

from __future__ import annotations

from friday_ai.agents.research_loop import DEFAULT_PLANNER_MODEL
from friday_ai.cli.ask import _resolve_research_model
from friday_ai.core.config import FridayConfig


def test_explicit_model_flag_wins() -> None:
    config = FridayConfig()
    config.deep_research.model = "dr-model"
    config.intelligence.default_model = "cfg-model"
    assert _resolve_research_model("cli-model", config) == "cli-model"


def test_deep_research_section_beats_default_model() -> None:
    config = FridayConfig()
    config.deep_research.model = "dr-model"
    config.intelligence.default_model = "cfg-model"
    assert _resolve_research_model(None, config) == "dr-model"


def test_config_default_model_used_when_no_override() -> None:
    """The bug: a configured default model must not be ignored for gemma4."""
    config = FridayConfig()
    config.intelligence.default_model = "qwen3.5:2b"
    assert _resolve_research_model(None, config) == "qwen3.5:2b"


def test_legacy_fallback_when_nothing_configured() -> None:
    config = FridayConfig()
    config.intelligence.default_model = ""
    assert _resolve_research_model(None, config) == DEFAULT_PLANNER_MODEL
    assert _resolve_research_model(None, None) == DEFAULT_PLANNER_MODEL
