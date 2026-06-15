"""CLI-level regression tests for ``jarvis ask`` vision input.

The unit tests in ``tests/test_vision.py`` cover the ``Message.images`` ->
``messages_to_dicts`` serialization contract in isolation. These tests lock
the *end-to-end CLI wiring*: that ``--image`` reads a file, base64-encodes it,
attaches it to the final user ``Message``, and that the bytes actually reach
``engine.generate()`` -- and that the local-first privacy guard fires only for
non-local engines.
"""

from __future__ import annotations

import base64
import importlib
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from openjarvis.cli import cli
from openjarvis.core.config import JarvisConfig
from openjarvis.core.types import Role

# Import the module (not the Click command attribute) so we can monkeypatch
# the names it looks up at call time.
_ask_mod = importlib.import_module("openjarvis.cli.ask")

# A minimal but valid 1x1 PNG so ``click.Path(exists=True)`` is satisfied and
# the bytes are deterministic.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


class _RecordingEngine:
    """A fake engine that records the messages handed to ``generate()``."""

    def __init__(self) -> None:
        self.engine_id = "mock"
        self.received: list[Any] = []

    def health(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["test-model"]

    def generate(self, messages, *, model=None, **kwargs):
        # Capture the exact Message objects the CLI built so the test can
        # assert the image bytes reached the engine boundary.
        self.received = list(messages)
        return {
            "content": "a 1x1 pixel",
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "model": "test-model",
            "finish_reason": "stop",
        }


def _patch_ask(monkeypatch, tmp_path: Path, *, engine_name: str) -> _RecordingEngine:
    """Wire ``jarvis ask`` to a recording engine reported under ``engine_name``."""
    cfg = JarvisConfig()
    cfg.telemetry.db_path = str(tmp_path / "telemetry.db")
    # Keep memory context out of the picture so the user message we inspect is
    # the one the CLI built directly from the query + image.
    cfg.agent.context_from_memory = False
    monkeypatch.setattr(_ask_mod, "load_config", lambda: cfg)

    engine = _RecordingEngine()
    monkeypatch.setattr(_ask_mod, "get_engine", lambda *a, **kw: (engine_name, engine))
    monkeypatch.setattr(_ask_mod, "discover_engines", lambda c: [(engine_name, engine)])
    monkeypatch.setattr(
        _ask_mod, "discover_models", lambda e: {engine_name: ["test-model"]}
    )
    return engine


def _write_png(tmp_path: Path) -> tuple[Path, str]:
    img = tmp_path / "pixel.png"
    img.write_bytes(_PNG_BYTES)
    return img, base64.b64encode(_PNG_BYTES).decode("ascii")


def test_image_reaches_engine_payload(monkeypatch, tmp_path: Path) -> None:
    engine = _patch_ask(monkeypatch, tmp_path, engine_name="ollama")
    img, expected_b64 = _write_png(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["ask", "-i", str(img), "--no-context", "--agent", "", "describe this"],
    )

    assert result.exit_code == 0, result.output
    # The CLI must have routed to direct mode and called the engine.
    assert engine.received, "engine.generate() was never called"
    user_msgs = [m for m in engine.received if m.role == Role.USER]
    assert user_msgs, "no USER message reached the engine"
    assert user_msgs[-1].images == [expected_b64]


def test_privacy_warning_for_non_local_engine(monkeypatch, tmp_path: Path) -> None:
    engine = _patch_ask(monkeypatch, tmp_path, engine_name="openai")
    img, expected_b64 = _write_png(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["ask", "-i", str(img), "--no-context", "--agent", "", "describe this"],
    )

    assert result.exit_code == 0, result.output
    assert "Privacy warning" in result.output
    # The warning is informational; the image must still be delivered.
    user_msgs = [m for m in engine.received if m.role == Role.USER]
    assert user_msgs and user_msgs[-1].images == [expected_b64]


def test_no_privacy_warning_for_local_engine(monkeypatch, tmp_path: Path) -> None:
    _patch_ask(monkeypatch, tmp_path, engine_name="ollama")
    img, _ = _write_png(tmp_path)

    result = CliRunner().invoke(
        cli,
        ["ask", "-i", str(img), "--no-context", "--agent", "", "describe this"],
    )

    assert result.exit_code == 0, result.output
    assert "Privacy warning" not in result.output
