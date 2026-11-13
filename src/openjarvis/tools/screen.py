"""Local screen capture for the vision ``/see`` command.

Captures the primary screen as a base64 PNG so a vision-capable model can
describe what is displayed — the "describe my screen" pattern of local-first
assistants. Pillow is an optional dependency: without it a helpful error is
raised instead of failing at import time.
"""

from __future__ import annotations

import base64
import io


def capture_screen_b64() -> str:
    """Capture the primary screen and return it as a base64 PNG string.

    Raises RuntimeError with an install hint when Pillow is missing or the
    capture fails.
    """
    try:
        from PIL import ImageGrab
    except ImportError as exc:
        raise RuntimeError(
            "Screen capture requires Pillow — install with: pip install pillow"
        ) from exc

    try:
        image = ImageGrab.grab()
    except Exception as exc:  # noqa: BLE001 — platform grab failures
        raise RuntimeError(
            f"Screen capture failed on this platform: {exc}"
        ) from exc

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


__all__ = ["capture_screen_b64"]
