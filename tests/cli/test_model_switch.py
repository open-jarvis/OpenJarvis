"""Tests for CLI model preset / smart resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

from openjarvis.cli._model_switch import (
    resolve_chat_cli_model,
    tty_wants_model_picker,
    variant_preset_model,
)
from openjarvis.core.config import JarvisConfig


def test_variant_preset_long() -> None:
    cfg = JarvisConfig()
    cfg.intelligence.model_long = "devstral:q4"
    assert variant_preset_model(cfg, "long") == "devstral:q4"
    assert variant_preset_model(cfg, "chat") == ""


def test_resolve_explicit_model() -> None:
    cfg = JarvisConfig()
    cfg.intelligence.default_model = "fallback"
    cfg.intelligence.model_long = "preset-long"
    eng = MagicMock()
    eng.list_models.return_value = ["a"]
    m = resolve_chat_cli_model(
        console=MagicMock(),
        config=cfg,
        engine=eng,
        engine_name="ollama",
        cli_model="explicit-only",
        chat_variant="long",
    )
    assert m == "explicit-only"


def test_resolve_smart_uses_preset() -> None:
    cfg = JarvisConfig()
    cfg.intelligence.default_model = "fallback"
    cfg.intelligence.model_code = "coder-model"
    eng = MagicMock()
    eng.list_models.return_value = ["a"]
    m = resolve_chat_cli_model(
        console=MagicMock(),
        config=cfg,
        engine=eng,
        engine_name="ollama",
        cli_model="smart",
        chat_variant="code",
    )
    assert m == "coder-model"


def test_tty_wants_model_picker_flag() -> None:
    assert tty_wants_model_picker(True) is True


def test_resolve_omitted_uses_default() -> None:
    cfg = JarvisConfig()
    cfg.intelligence.default_model = "defm"
    eng = MagicMock()
    eng.list_models.return_value = ["x"]
    m = resolve_chat_cli_model(
        console=MagicMock(),
        config=cfg,
        engine=eng,
        engine_name="ollama",
        cli_model=None,
        chat_variant="short",
    )
    assert m == "defm"
