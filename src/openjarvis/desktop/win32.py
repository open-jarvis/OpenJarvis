"""Minimal semantic Win32 control backend and window-only screenshot capture."""

from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes

from openjarvis.desktop.models import (
    DesktopElement,
    DesktopRect,
    DesktopWindow,
    DisplayContext,
)


def _configure_win32() -> tuple[object, object]:
    """Declare pointer-sized Win32 signatures before crossing the ctypes boundary."""

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetFocus.argtypes = [wintypes.HWND]
    user32.SetFocus.restype = wintypes.HWND
    user32.AttachThreadInput.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.BOOL,
    ]
    user32.AttachThreadInput.restype = wintypes.BOOL
    user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = ctypes.c_ssize_t
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL
    gdi32.BitBlt.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    return user32, gdi32


class WindowsDesktopError(RuntimeError):
    pass


def _require_windows() -> None:
    if os.name != "nt":
        raise WindowsDesktopError(
            "Win32 desktop automation is available only on Windows"
        )


def _text(hwnd: int) -> str:
    user32, _ = _configure_win32()
    # GetWindowTextW deliberately cannot read child-control text owned by
    # another process. Standard WM_GETTEXT messages are marshalled by Windows.
    length = int(user32.SendMessageW(hwnd, 0x000E, 0, 0))
    buffer = ctypes.create_unicode_buffer(length + 1)
    pointer = ctypes.cast(buffer, ctypes.c_void_p).value or 0
    user32.SendMessageW(hwnd, 0x000D, len(buffer), pointer)
    return buffer.value


def _rect(hwnd: int) -> DesktopRect:
    value = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(value)):
        raise WindowsDesktopError("GetWindowRect failed")
    return DesktopRect(value.left, value.top, value.right, value.bottom)


def _pid(hwnd: int) -> int:
    value = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
    return int(value.value)


class Win32SemanticBackend:
    """Use native window/control semantics; no blind coordinates by default."""

    def find_window(self, process_id: int, expected_title: str) -> DesktopWindow:
        _require_windows()
        matches: list[int] = []
        owned_titles: list[str] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def callback(hwnd, _lparam):
            if ctypes.windll.user32.IsWindowVisible(hwnd) and _pid(hwnd) == process_id:
                title = _text(hwnd)
                owned_titles.append(title)
                if title == expected_title:
                    matches.append(int(hwnd))
            return True

        callback_ref = callback_type(callback)
        ctypes.windll.user32.EnumWindows(callback_ref, 0)
        if len(matches) != 1:
            raise WindowsDesktopError(
                "expected exactly one owned window, "
                f"found {len(matches)}; owned visible titles={owned_titles!r}"
            )
        hwnd = matches[0]
        dpi = int(getattr(ctypes.windll.user32, "GetDpiForWindow", lambda _h: 96)(hwnd))
        return DesktopWindow(hwnd, _pid(hwnd), _text(hwnd), _rect(hwnd), dpi or 96)

    @staticmethod
    def is_owned_process(process_id: int, root_process_id: int) -> bool:
        return process_id == root_process_id

    def elements(self, window: DesktopWindow) -> tuple[DesktopElement, ...]:
        self._assert_owned(window.handle, window.process_id)
        children: list[DesktopElement] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def callback(hwnd, _lparam):
            class_name = ctypes.create_unicode_buffer(256)
            ctypes.windll.user32.GetClassNameW(hwnd, class_name, len(class_name))
            children.append(
                DesktopElement(
                    handle=int(hwnd),
                    process_id=window.process_id,
                    role=class_name.value.casefold(),
                    name=_text(hwnd),
                    automation_id=int(ctypes.windll.user32.GetDlgCtrlID(hwnd)),
                    bounds=_rect(hwnd),
                )
            )
            return True

        callback_ref = callback_type(callback)
        ctypes.windll.user32.EnumChildWindows(window.handle, callback_ref, 0)
        return tuple(children)

    def find_element(
        self,
        window: DesktopWindow,
        *,
        automation_id: int,
        role: str | None = None,
    ) -> DesktopElement:
        matches = [
            element
            for element in self.elements(window)
            if element.automation_id == automation_id
            and (role is None or element.role == role.casefold())
        ]
        if len(matches) != 1:
            raise WindowsDesktopError(
                "expected one semantic element "
                f"id={automation_id}, found {len(matches)}"
            )
        return matches[0]

    def set_text(
        self, window: DesktopWindow, element: DesktopElement, value: str
    ) -> str:
        self._assert_element(window, element)
        if element.role != "edit":
            raise WindowsDesktopError("semantic text input requires an EDIT control")
        text_value = ctypes.c_wchar_p(value)
        text_pointer = ctypes.cast(text_value, ctypes.c_void_p).value or 0
        if not ctypes.windll.user32.SendMessageW(
            element.handle, 0x000C, 0, text_pointer
        ):
            # WM_SETTEXT returns zero for some controls even when successful;
            # the observed text below is the authority.
            pass
        observed = _text(element.handle)
        if observed != value:
            raise WindowsDesktopError("text input verification failed")
        return observed

    def click(self, window: DesktopWindow, element: DesktopElement) -> None:
        self._assert_element(window, element)
        if element.role != "button":
            raise WindowsDesktopError("semantic click requires a BUTTON control")
        ctypes.windll.user32.SendMessageW(element.handle, 0x00F5, 0, 0)

    def focus(self, window: DesktopWindow) -> bool:
        self._assert_owned(window.handle, window.process_id)
        user32, _ = _configure_win32()
        if int(user32.GetForegroundWindow()) == window.handle:
            return True
        current_thread = int(ctypes.windll.kernel32.GetCurrentThreadId())
        target_thread = int(user32.GetWindowThreadProcessId(window.handle, None))
        foreground = int(user32.GetForegroundWindow())
        foreground_thread = (
            int(user32.GetWindowThreadProcessId(foreground, None))
            if foreground
            else 0
        )
        attached: list[int] = []
        try:
            for thread_id in {target_thread, foreground_thread} - {0, current_thread}:
                if user32.AttachThreadInput(current_thread, thread_id, True):
                    attached.append(thread_id)
            user32.BringWindowToTop(window.handle)
            user32.SetForegroundWindow(window.handle)
            user32.SetFocus(window.handle)
            return int(user32.GetForegroundWindow()) == window.handle
        finally:
            for thread_id in reversed(attached):
                user32.AttachThreadInput(current_thread, thread_id, False)

    def is_focused(self, window: DesktopWindow) -> bool:
        return int(ctypes.windll.user32.GetForegroundWindow()) == window.handle

    def close(self, window: DesktopWindow) -> None:
        self._assert_owned(window.handle, window.process_id)
        ctypes.windll.user32.PostMessageW(window.handle, 0x0010, 0, 0)

    def display_context(self, window: DesktopWindow) -> DisplayContext:
        user32 = ctypes.windll.user32
        return DisplayContext(
            monitor_count=int(user32.GetSystemMetrics(80)),
            virtual_left=int(user32.GetSystemMetrics(76)),
            virtual_top=int(user32.GetSystemMetrics(77)),
            virtual_width=int(user32.GetSystemMetrics(78)),
            virtual_height=int(user32.GetSystemMetrics(79)),
            dpi=window.dpi,
            scale=window.dpi / 96.0,
        )

    def coordinate_click(self, window: DesktopWindow, x: int, y: int) -> None:
        self._assert_owned(window.handle, window.process_id)
        if not window.bounds.left <= x < window.bounds.right:
            raise WindowsDesktopError("x coordinate escaped the owned window")
        if not window.bounds.top <= y < window.bounds.bottom:
            raise WindowsDesktopError("y coordinate escaped the owned window")
        ctypes.windll.user32.SetCursorPos(x, y)
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)

    def screenshot_window(self, window: DesktopWindow) -> bytes:
        """Capture exactly one owned window as BMP bytes using GDI."""

        self._assert_owned(window.handle, window.process_id)
        width, height = window.bounds.width, window.bounds.height
        user32, gdi32 = _configure_win32()
        window_dc = user32.GetWindowDC(window.handle)
        memory_dc = gdi32.CreateCompatibleDC(window_dc)
        bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
        old = gdi32.SelectObject(memory_dc, bitmap)
        try:
            if not user32.PrintWindow(window.handle, memory_dc, 2):
                gdi32.BitBlt(
                    memory_dc, 0, 0, width, height, window_dc, 0, 0, 0x00CC0020
                )
            header = _BitmapInfoHeader()
            header.biSize = ctypes.sizeof(_BitmapInfoHeader)
            header.biWidth = width
            header.biHeight = -height
            header.biPlanes = 1
            header.biBitCount = 32
            header.biCompression = 0
            pixel_size = width * height * 4
            pixels = ctypes.create_string_buffer(pixel_size)
            info = _BitmapInfo()
            info.bmiHeader = header
            if not gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                height,
                pixels,
                ctypes.byref(info),
                0,
            ):
                raise WindowsDesktopError("GetDIBits failed")
            file_header = struct.pack(
                "<2sIHHI",
                b"BM",
                14 + 40 + pixel_size,
                0,
                0,
                14 + 40,
            )
            dib_header = struct.pack(
                "<IiiHHIIiiII",
                40,
                width,
                -height,
                1,
                32,
                0,
                pixel_size,
                0,
                0,
                0,
                0,
            )
            return file_header + dib_header + pixels.raw
        finally:
            gdi32.SelectObject(memory_dc, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(window.handle, window_dc)

    @staticmethod
    def _assert_owned(hwnd: int, process_id: int) -> None:
        if _pid(hwnd) != process_id:
            raise WindowsDesktopError("window ownership changed")

    def _assert_element(self, window: DesktopWindow, element: DesktopElement) -> None:
        self._assert_owned(window.handle, window.process_id)
        if (
            element.process_id != window.process_id
            or _pid(element.handle) != window.process_id
        ):
            raise WindowsDesktopError("element escaped the owned process")


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]


__all__ = ["Win32SemanticBackend", "WindowsDesktopError"]
