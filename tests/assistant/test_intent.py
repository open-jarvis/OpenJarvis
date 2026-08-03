from __future__ import annotations

import pytest

from openjarvis.assistant import AssistantIntentKind, classify_assistant_intent
from openjarvis.tasks.policy import RiskLevel


@pytest.mark.parametrize(
    "message",
    [
        "Explain simply how a browser works.",
        "How does a software build work?",
        "Can you explain why a desktop app needs a window?",
        "Was ist ein Texteditor?",
        "Write a short poem about a repository.",
        "Erkläre mir, warum langsames Radfahren schwieriger ist.",
    ],
)
def test_explanations_and_writing_remain_plain_chat(message: str) -> None:
    intent = classify_assistant_intent(message)
    assert intent.kind is AssistantIntentKind.CHAT
    assert intent.risk_level is RiskLevel.READ_ONLY


@pytest.mark.parametrize(
    "message",
    [
        "Open a text editor and save the test note.",
        "Bitte öffne einen Editor und tippe den Testtext ein.",
        "Kannst du die Desktop-App starten?",
    ],
)
def test_desktop_actions_are_interactive(message: str) -> None:
    intent = classify_assistant_intent(message)
    assert intent.kind is AssistantIntentKind.DESKTOP
    assert intent.risk_level is RiskLevel.EXTERNAL_PREPARATION


@pytest.mark.parametrize(
    "message",
    [
        "Kannst du mal den Dokumente-Ordner öffnen?",
        "Durchsuche meine Dokumente nach der Rechnung.",
        "Show the files in my downloads folder.",
    ],
)
def test_filesystem_desktop_actions_are_detected(message: str) -> None:
    intent = classify_assistant_intent(message)
    assert intent.kind is AssistantIntentKind.DESKTOP
    assert intent.risk_level is RiskLevel.EXTERNAL_PREPARATION


@pytest.mark.parametrize(
    "message",
    [
        "Research bicycle balance in the browser.",
        "Recherchiere online, wie Fahrräder balancieren.",
        "Geh auf TikTok und schreib Bashar hallo.",
    ],
)
def test_browser_preparation_is_detected_in_english_and_german(message: str) -> None:
    intent = classify_assistant_intent(message)
    assert intent.kind is AssistantIntentKind.BROWSER
    assert intent.risk_level is RiskLevel.EXTERNAL_PREPARATION


@pytest.mark.parametrize(
    "message",
    [
        "Open the browser and submit the form.",
        "Öffne die Webseite und sende die Nachricht.",
    ],
)
def test_external_effect_raises_browser_risk(message: str) -> None:
    intent = classify_assistant_intent(message)
    assert intent.kind is AssistantIntentKind.BROWSER
    assert intent.risk_level is RiskLevel.DESTRUCTIVE_OR_SENSITIVE


@pytest.mark.parametrize(
    "message",
    [
        "Fix the bug in this repository and run the tests.",
        "Bitte behebe den Fehler im Projekt.",
        "Implement the requested code change.",
    ],
)
def test_programming_actions_are_reversible_workspace_work(message: str) -> None:
    intent = classify_assistant_intent(message)
    assert intent.kind is AssistantIntentKind.PROGRAMMING
    assert intent.risk_level is RiskLevel.REVERSIBLE_WORKSPACE


def test_destructive_programming_request_raises_the_risk_floor() -> None:
    intent = classify_assistant_intent(
        "Change the code, delete the generated file, and run the tests."
    )

    assert intent.kind is AssistantIntentKind.PROGRAMMING
    assert intent.risk_level is RiskLevel.DESTRUCTIVE_OR_SENSITIVE
