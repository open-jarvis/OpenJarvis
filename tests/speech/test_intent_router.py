"""Tests for the voice-command intent router."""

from __future__ import annotations

import pytest

from openjarvis.speech.intent_router import (
    ACTION_ANALYZE_MATERIAL,
    ACTION_CHAT_FALLBACK,
    ACTION_COMPARE_MATERIALS,
    ACTION_OPEN_SCIENCE_LAB,
    ACTION_SAVE_PROJECT,
    ACTION_SIMULATE_MIXTURE,
    IntentRouter,
)


@pytest.mark.parametrize(
    "phrase,expected_action",
    [
        ("JARVIS, abra o laboratório científico", ACTION_OPEN_SCIENCE_LAB),
        ("abra o laboratório científico", ACTION_OPEN_SCIENCE_LAB),
        ("JARVIS, analise este material", ACTION_ANALYZE_MATERIAL),
        ("analisar o material", ACTION_ANALYZE_MATERIAL),
        ("JARVIS, compare esses dois materiais", ACTION_COMPARE_MATERIALS),
        ("comparar materiais", ACTION_COMPARE_MATERIALS),
        ("JARVIS, simule essa mistura", ACTION_SIMULATE_MIXTURE),
        ("simular a mistura", ACTION_SIMULATE_MIXTURE),
        ("JARVIS, salve esse projeto", ACTION_SAVE_PROJECT),
        ("salvar o projeto", ACTION_SAVE_PROJECT),
    ],
)
def test_route_fixed_phrases(phrase, expected_action):
    router = IntentRouter()
    intent = router.route(phrase)
    assert intent.action == expected_action


def test_unmatched_text_falls_through_to_chat():
    router = IntentRouter()
    intent = router.route("qual é a previsão do tempo hoje?")
    assert intent.action == ACTION_CHAT_FALLBACK
    assert intent.args["text"] == "qual é a previsão do tempo hoje?"


def test_empty_text_falls_through_to_chat():
    router = IntentRouter()
    intent = router.route("")
    assert intent.action == ACTION_CHAT_FALLBACK
