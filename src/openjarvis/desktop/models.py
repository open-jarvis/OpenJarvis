"""Windows desktop automation records."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DesktopRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass(frozen=True, slots=True)
class DesktopWindow:
    handle: int
    process_id: int
    title: str
    bounds: DesktopRect
    dpi: int


@dataclass(frozen=True, slots=True)
class DesktopElement:
    handle: int
    process_id: int
    role: str
    name: str
    automation_id: int
    bounds: DesktopRect


@dataclass(frozen=True, slots=True)
class DesktopArtifact:
    artifact_id: str
    path: str
    sha256: str
    size_bytes: int
    window_handle: int


@dataclass(frozen=True, slots=True)
class DisplayContext:
    monitor_count: int
    virtual_left: int
    virtual_top: int
    virtual_width: int
    virtual_height: int
    dpi: int
    scale: float


@dataclass(frozen=True, slots=True)
class CoordinateActionContext:
    display: DisplayContext
    window: DesktopWindow
    target: DesktopRect
    focused: bool
    before_artifact: DesktopArtifact
    interrupt_enabled: bool


__all__ = [
    "CoordinateActionContext",
    "DesktopArtifact",
    "DesktopElement",
    "DesktopRect",
    "DesktopWindow",
    "DisplayContext",
]
