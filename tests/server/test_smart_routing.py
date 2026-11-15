"""Tests for model routing with ``model="auto"``."""

from __future__ import annotations

import pytest

from openjarvis.server.smart_routing import (
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_OPENAI_MODEL,
    choose_model,
)

LOCAL = "qwen3.5:4b"


class FakeEngine:
    def __init__(self, models):
        self._models = list(models)

    def list_models(self):
        return self._models


@pytest.fixture
def keys(monkeypatch):
    """Set which cloud keys exist; returns an engine advertising those models."""

    def _set(*, claude: bool = False, openai: bool = False) -> FakeEngine:
        for var, on in (("ANTHROPIC_API_KEY", claude), ("OPENAI_API_KEY", openai)):
            if on:
                monkeypatch.setenv(var, "test-key")
            else:
                monkeypatch.delenv(var, raising=False)
        monkeypatch.delenv("OPENJARVIS_CLAUDE_MODEL", raising=False)
        monkeypatch.delenv("OPENJARVIS_OPENAI_MODEL", raising=False)
        models = [LOCAL]
        if claude:
            models.append(DEFAULT_CLAUDE_MODEL)
        if openai:
            models.append(DEFAULT_OPENAI_MODEL)
        return FakeEngine(models)

    return _set


def route(text, engine, tier=None):
    return choose_model(text, tier, local_model=LOCAL, engine=engine)


def test_everyday_chat_stays_local(keys):
    assert route("what is the capital of japan", keys(claude=True)).model == LOCAL


def test_automation_goes_to_claude(keys):
    d = route("remind me every morning at 8 to drink water", keys(claude=True))
    assert d.model == DEFAULT_CLAUDE_MODEL
    assert d.used_claude


def test_asking_for_chatgpt_uses_it(keys):
    d = route("ask chatgpt what a black hole is", keys(claude=True, openai=True))
    assert d.model == DEFAULT_OPENAI_MODEL


def test_hard_work_falls_back_to_chatgpt_without_claude(keys):
    assert route("write a script to rename files", keys(openai=True)).model == (
        DEFAULT_OPENAI_MODEL
    )


def test_without_keys_everything_stays_local(keys):
    engine = keys()
    assert route("ask chatgpt anything", engine).model == LOCAL
    assert route("schedule a daily backup", engine).model == LOCAL


def test_malayalam_goes_to_a_cloud_model_when_available(keys):
    """The small local model writes poor Malayalam; prefer Claude, then ChatGPT."""
    question = "ഇന്ന് കാലാവസ്ഥ എങ്ങനെയുണ്ട്?"
    assert route(question, keys(claude=True)).model == DEFAULT_CLAUDE_MODEL
    assert route(question, keys(openai=True)).model == DEFAULT_OPENAI_MODEL
    assert "Malayalam" in route(question, keys(openai=True)).reason


def test_malayalam_stays_local_without_keys(keys):
    assert route("സമയം എത്രയായി?", keys()).model == LOCAL


def test_an_english_question_with_one_malayalam_word_is_not_malayalam(keys):
    assert route("what does നന്ദി mean in english", keys(claude=True)).model == LOCAL


def test_malayalam_voice_command_with_the_hud_instruction_still_counts(keys):
    """The HUD appends an English reply instruction to spoken turns."""
    spoken = (
        "സമയം എത്രയായി?\n\n(Spoken request: reply in at most two short spoken "
        "sentences, plain words, no lists or markdown. Reply in Malayalam, "
        "written in Malayalam script.)"
    )
    assert route(spoken, keys(openai=True)).model == DEFAULT_OPENAI_MODEL
