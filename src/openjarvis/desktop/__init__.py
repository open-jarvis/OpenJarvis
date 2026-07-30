"""Safe Windows desktop automation abstraction."""

from openjarvis.desktop.models import (
    CoordinateActionContext,
    DesktopArtifact,
    DesktopElement,
    DesktopRect,
    DesktopWindow,
    DisplayContext,
)
from openjarvis.desktop.session import WindowsDesktopSession
from openjarvis.desktop.win32 import Win32SemanticBackend, WindowsDesktopError

__all__ = [
    "CoordinateActionContext",
    "DesktopArtifact",
    "DesktopElement",
    "DesktopRect",
    "DesktopWindow",
    "DisplayContext",
    "Win32SemanticBackend",
    "WindowsDesktopError",
    "WindowsDesktopSession",
]
