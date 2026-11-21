"""`jarvis ask` must answer clock/news questions without the LLM."""

from __future__ import annotations

from click.testing import CliRunner

from openjarvis.cli import cli


def test_ask_time_uses_local_clock() -> None:
    result = CliRunner().invoke(cli, ["ask", "quelle heure est-il ?"])
    assert result.exit_code == 0, result.output
    assert "Il est " in result.output
    assert "samedi" in result.output.lower() or "dimanche" in result.output.lower()


def test_ask_news_uses_rss_headlines(monkeypatch) -> None:
    import openjarvis.tools.net as net

    monkeypatch.setattr(
        net, "headlines_for", lambda category="", limit=8: ["Titre A", "Titre B"]
    )
    result = CliRunner().invoke(cli, ["ask", "les dernières nouvelles"])
    assert result.exit_code == 0, result.output
    assert "Titre A" in result.output and "Titre B" in result.output
