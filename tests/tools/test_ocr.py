"""Tests for the local Tesseract OCR helper."""

from __future__ import annotations

import io
import sys
from types import SimpleNamespace

import pytest

from openjarvis.tools.ocr import image_text


def _png_bytes() -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_text_without_pytesseract_raises(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    with pytest.raises(RuntimeError) as excinfo:
        image_text(_png_bytes())
    assert "pytesseract" in str(excinfo.value)


def test_image_text_extracts_text(monkeypatch) -> None:
    fake = SimpleNamespace(
        image_to_string=lambda image: "Bonjour le monde\n",
    )
    monkeypatch.setitem(sys.modules, "pytesseract", fake)

    assert image_text(_png_bytes()) == "Bonjour le monde"


def test_image_text_tesseract_binary_missing_raises(monkeypatch) -> None:
    class _BrokenTesseract:
        def image_to_string(self, image):
            raise RuntimeError("TesseractNotFoundError")

    monkeypatch.setitem(sys.modules, "pytesseract", _BrokenTesseract())
    with pytest.raises(RuntimeError) as excinfo:
        image_text(_png_bytes())
    assert "OCR failed" in str(excinfo.value)
