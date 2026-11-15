"""Local screen capture and vision inputs (``/see``, ``/read``).

Captures the primary screen (or loads an image file / webcam frame) as a
base64 PNG so a vision-capable model can describe what is displayed — the
"describe my screen" pattern of local-first assistants. Pillow is required
for screen/file capture and OpenCV for the webcam; each helper raises a
helpful error instead of failing at import time when its dependency is
missing.
"""

from __future__ import annotations

import base64
import io
import time
from pathlib import Path
from typing import Optional

# Downscale large captures before sending them to the model: fewer tokens,
# faster inference, and plenty of detail left for screen description.
_MAX_SIDE = 1280


def _image_to_b64(image: object, *, format: str = "PNG") -> str:
    """Encode a Pillow image as base64, resized to fit ``_MAX_SIDE``."""
    image.thumbnail((_MAX_SIDE, _MAX_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _pillow() -> object:
    try:
        import PIL
    except ImportError as exc:
        raise RuntimeError(
            "Screen capture requires Pillow — install with: pip install pillow"
        ) from exc
    return PIL


def capture_screen_b64() -> str:
    """Capture the primary screen and return it as a base64 PNG string.

    Raises RuntimeError with an install hint when Pillow is missing or the
    capture fails.
    """
    pil = _pillow()
    try:
        from PIL import ImageGrab

        image = ImageGrab.grab()
    except Exception as exc:  # noqa: BLE001 — platform grab failures
        raise RuntimeError(
            f"Screen capture failed on this platform: {exc}"
        ) from exc
    return _image_to_b64(image)


def save_screen(path: Optional[str] = None) -> str:
    """Capture the screen and save it as a PNG file.

    Returns the saved path. Without *path*, writes a timestamped file into
    ``<config-dir>/screenshots/``.
    """
    pil = _pillow()
    from PIL import ImageGrab

    if path is None:
        from openjarvis.core.paths import get_config_dir

        directory = get_config_dir() / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        path = str(
            directory / f"screenshot_{time.strftime('%Y-%m-%d_%H%M%S')}.png"
        )
    image = ImageGrab.grab()
    image.thumbnail((_MAX_SIDE, _MAX_SIDE))
    image.save(path, format="PNG")
    return path


def image_file_b64(path: str) -> str:
    """Load an image file (PNG/JPEG/…) and return it as base64."""
    _pillow()
    from PIL import Image

    try:
        with Image.open(Path(path)) as image:
            image.load()
            return _image_to_b64(image)
    except Exception as exc:  # noqa: BLE001 — unreadable/corrupt files
        raise RuntimeError(f"Could not read image '{path}': {exc}") from exc


def capture_webcam_b64(camera_index: int = 0) -> str:
    """Capture one frame from the webcam and return it as base64.

    Requires OpenCV (``pip install opencv-python``).
    """
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError(
            "Webcam capture requires OpenCV — install with: "
            "pip install opencv-python"
        ) from exc

    capture = cv2.VideoCapture(camera_index)
    try:
        if not capture.isOpened():
            raise RuntimeError(
                f"Could not open webcam #{camera_index} on this machine."
            )
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError("Could not read a frame from the webcam.")
    finally:
        capture.release()

    _pillow()
    from PIL import Image

    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    return _image_to_b64(image, format="JPEG")


__all__ = [
    "capture_screen_b64",
    "capture_webcam_b64",
    "image_file_b64",
    "save_screen",
]
