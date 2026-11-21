"""Tests for deterministic quick commands (no LLM)."""

from __future__ import annotations

import time

from openjarvis.speech.quick_commands import handle_quick_command


def _fixed_time():
    return time.struct_time((2026, 11, 14, 9, 5, 0, 5, 318, 0))


def test_time_commands_answer_in_french() -> None:
    reply = handle_quick_command("quelle heure est-il", now_fn=_fixed_time)
    assert reply is not None
    assert "Il est 09h05" in reply
    assert "samedi 14 novembre 2026" in reply


def test_open_app_command_launches_known_app() -> None:
    captured = {}

    def fake_launch(app_name, executable):
        captured["app"] = app_name
        captured["exe"] = executable
        return f"J'ouvre {app_name}."

    reply = handle_quick_command(
        "ouvre le bloc-notes", launch_fn=fake_launch, now_fn=_fixed_time
    )
    assert reply == "J'ouvre bloc-notes."
    assert captured == {"app": "bloc-notes", "exe": "notepad.exe"}


def test_lance_command_launches_calculator() -> None:
    captured = []

    def fake_launch(app_name, executable):
        captured.append((app_name, executable))
        return "ok"

    handle_quick_command(
        "lance la calculatrice", launch_fn=fake_launch, now_fn=_fixed_time
    )
    assert captured == [("calculatrice", "calc.exe")]


def test_lock_command_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.speech.quick_commands._lock_pc",
        lambda: "Écran verrouillé.",
    )
    assert handle_quick_command("verrouille le PC") == "Écran verrouillé."


def test_volume_commands_match(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        "openjarvis.speech.quick_commands._set_volume",
        lambda level: calls.append(level) or "Volume ajusté.",
    )
    assert handle_quick_command("monte le volume") == "Volume ajusté."
    assert handle_quick_command("baisse le volume") == "Volume ajusté."
    assert handle_quick_command("coupe le son") == "Volume ajusté."
    assert calls == ["up", "down", "mute"]


def test_unknown_commands_return_none() -> None:
    assert handle_quick_command("raconte-moi une histoire") is None
    assert handle_quick_command("bonjour jarvis") is None
    assert handle_quick_command("") is None


def test_time_in_city_uses_world_time(monkeypatch) -> None:
    monkeypatch.setattr(
        "openjarvis.tools.net.city_time",
        lambda city: f"À {city}, il est 17h05.",
    )
    reply = handle_quick_command("quelle heure est-il à Tokyo")
    assert reply == "À Tokyo, il est 17h05."


def test_time_without_city_stays_local() -> None:
    reply = handle_quick_command("quelle heure est-il", now_fn=_fixed_time)
    assert reply is not None
    assert "samedi 14 novembre 2026" in reply


def test_open_command_rejects_arbitrary_apps() -> None:
    # "ouvre" with an app outside the known list must NOT launch anything.
    assert handle_quick_command("ouvre le gestionnaire de tâches") is None

def test_city_time_with_trailing_punctuation() -> None:
    """Typed questions end with '?'; the city still has to be recognised."""
    reply = handle_quick_command(
        "quelle heure est-il à Tokyo ?", now_fn=_fixed_time
    )
    assert reply is not None
    assert "Tokyo" in reply


def test_city_time_without_accent_or_space_before_mark() -> None:
    assert "Tokyo" in (handle_quick_command("quelle heure à tokyo?") or "")


def test_plain_time_question_still_local() -> None:
    reply = handle_quick_command("quelle heure est-il ?", now_fn=_fixed_time)
    assert reply == "Il est 09h05 — samedi 14 novembre 2026."


def test_news_command_returns_live_headlines(monkeypatch) -> None:
    import openjarvis.tools.net as net

    monkeypatch.setattr(
        net, "headlines_for", lambda category="", limit=8: ["Titre A", "Titre B"]
    )
    reply = handle_quick_command("quelles sont les dernières nouvelles ?")
    assert reply is not None
    assert "Titre A" in reply and "Titre B" in reply


def test_news_command_falls_through_when_feeds_fail(monkeypatch) -> None:
    import openjarvis.tools.net as net

    def boom(*args, **kwargs):
        raise OSError("offline")

    monkeypatch.setattr(net, "headlines_for", boom)
    assert handle_quick_command("les dernières nouvelles") is None


def test_country_name_resolves_to_capital(monkeypatch) -> None:
    # No network: city_time is patched to echo its argument.
    import openjarvis.tools.net as net

    monkeypatch.setattr(net, "city_time", lambda city: f"heure de {city}")
    assert "Berlin" in (handle_quick_command("quelle heure est-il en Allemagne ?") or "")
    assert "Tokyo" in (handle_quick_command("quelle heure est-il au Japon ?") or "")
    assert "New York" in (
        handle_quick_command("quelle heure est-il aux États-Unis ?") or ""
    )
