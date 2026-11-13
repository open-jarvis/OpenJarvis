"""Local OCR for the ``/read`` command.

Extracts text from the screen (or an image) with Tesseract — fast, offline,
and independent of a vision model. Both ``pytesseract`` (the Python binding)
and the Tesseract binary itself are optional: missing pieces raise a helpful
error that the chat command renders for the user.
"""

from __future__ import annotations

import io


def image_text(png_bytes: bytes) -> str:
    """Extract text from a PNG image using Tesseract OCR."""
    try:
        import pytesseract
    except ImportError as exc:
        raise RuntimeError(
            "OCR requires pytesseract — install with: "
            "pip install pytesseract (and the Tesseract binary, e.g. "
            "winget install UB-Mannheim.TesseractOCR)"
        ) from exc
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "OCR requires Pillow — install with: pip install pillow"
        ) from exc

    try:
        image = Image.open(io.BytesIO(png_bytes))
        text = pytesseract.image_to_string(image)
    except Exception as exc:  # noqa: BLE001 — engine/binary misconfigured
        raise RuntimeError(
            "OCR failed — check that Tesseract is installed and on PATH: "
            f"{exc}"
        ) from exc
    return text.strip()


def screen_text() -> str:
    """Capture the screen and return its text via Tesseract OCR."""
    from openjarvis.tools.screen import capture_screen_b64

    import base64

    png_bytes = base64.b64decode(capture_screen_b64())
    return image_text(png_bytes)


__all__ = ["image_text", "screen_text"]
