"""Render Blueprint stays aligned with settings the server consumes."""

from pathlib import Path

RENDER_BLUEPRINT = Path(__file__).resolve().parents[2] / "render.yaml"


def test_render_selects_cloud_engine_through_the_serve_cli() -> None:
    text = RENDER_BLUEPRINT.read_text(encoding="utf-8")

    assert "dockerCommand: serve --host 0.0.0.0 --port $PORT --engine cloud" in text
    assert "key: OPENJARVIS_ENGINE" not in text


def test_render_does_not_advertise_an_unconsumed_cors_variable() -> None:
    text = RENDER_BLUEPRINT.read_text(encoding="utf-8")

    assert "OPENJARVIS_CORS_ORIGINS" not in text


def test_render_public_bind_generates_an_api_key() -> None:
    text = RENDER_BLUEPRINT.read_text(encoding="utf-8")

    assert "key: OPENJARVIS_API_KEY" in text
    assert "generateValue: true" in text
