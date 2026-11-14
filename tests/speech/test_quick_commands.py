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


def test_open_command_rejects_arbitrary_apps() -> None:
    # "ouvre" with an app outside the known list must NOT launch anything.
    assert handle_quick_command("ouvre le gestionnaire de tâches") is None
