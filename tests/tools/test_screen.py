"""Tests for the local screen/webcam/image capture helpers."""

from __future__ import annotations

import base64
import io

import pytest

from openjarvis.tools.screen import (
    _MAX_SIDE,
    capture_webcam_b64,
    image_file_b64,
    save_screen,
)


def _png_b64(size: tuple[int, int]) -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color="red").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_image_file_b64_roundtrip(tmp_path) -> None:
    from PIL import Image

    path = tmp_path / "photo.png"
    Image.new("RGB", (640, 480), color="blue").save(path, format="PNG")

    b64 = image_file_b64(str(path))

    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))
    assert decoded.size == (640, 480)


def test_image_file_b64_downscales_large_images(tmp_path) -> None:
    from PIL import Image

    path = tmp_path / "big.png"
    Image.new("RGB", (4000, 2000), color="green").save(path, format="PNG")

    b64 = image_file_b64(str(path))
    decoded = Image.open(io.BytesIO(base64.b64decode(b64)))

    assert max(decoded.size) == _MAX_SIDE


def test_image_file_b64_missing_file_raises(tmp_path) -> None:
    with pytest.raises(RuntimeError) as excinfo:
        image_file_b64(str(tmp_path / "missing.png"))
    assert "Could not read image" in str(excinfo.value)


def test_capture_webcam_b64_without_cv2_raises(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "cv2", None)
    with pytest.raises(RuntimeError) as excinfo:
        capture_webcam_b64()
    assert "opencv-python" in str(excinfo.value)


def test_save_screen_writes_png(tmp_path, monkeypatch) -> None:
    from PIL import Image, ImageGrab

    monkeypatch.setattr(
        ImageGrab,
        "grab",
        lambda: Image.new("RGB", (320, 240), color="white"),
    )
    target = tmp_path / "shot.png"

    saved = save_screen(str(target))

    assert saved == str(target)
    assert target.exists()
    assert Image.open(target).format == "PNG"


def test_save_screen_default_path(tmp_path, monkeypatch) -> None:
    from PIL import Image, ImageGrab

    monkeypatch.setattr(
        ImageGrab,
        "grab",
        lambda: Image.new("RGB", (320, 240), color="white"),
    )
    monkeypatch.setattr(
        "openjarvis.core.paths.get_config_dir",
        lambda: tmp_path,
    )

    saved = save_screen()

    assert saved.endswith(".png")
    assert (tmp_path / "screenshots").exists()
