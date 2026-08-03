"""Minimal semantic Win32 control backend and window-only screenshot capture."""

from __future__ import annotations

import ctypes
import hashlib
import os
import struct
from ctypes import wintypes

from openjarvis.desktop.models import (
    DesktopElement,
    DesktopMonitor,
    DesktopRect,
    DesktopWindow,
    DisplayContext,
)
from openjarvis.desktop.uia import UIAutomationError, WindowsUIAutomationBridge

_DPI_AWARENESS_CONFIGURED = False


def _configure_win32() -> tuple[object, object]:
    """Declare pointer-sized Win32 signatures before crossing the ctypes boundary."""

    global _DPI_AWARENESS_CONFIGURED

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumChildWindows.argtypes = [
        wintypes.HWND,
        ctypes.c_void_p,
        wintypes.LPARAM,
    ]
    user32.EnumChildWindows.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        ctypes.c_void_p,
        wintypes.LPARAM,
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
    user32.GetMonitorInfoW.restype = wintypes.BOOL
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
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.IsZoomed.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.MoveWindow.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.BOOL,
    ]
    user32.MoveWindow.restype = wintypes.BOOL
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.GetDpiForWindow.argtypes = [wintypes.HWND]
    user32.GetDpiForWindow.restype = wintypes.UINT
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    if hasattr(user32, "SetProcessDpiAwarenessContext"):
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if not _DPI_AWARENESS_CONFIGURED:
            # PER_MONITOR_AWARE_V2. Failure is benign when awareness was set
            # earlier by the desktop host; GetDpiForWindow remains authoritative.
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            _DPI_AWARENESS_CONFIGURED = True
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.GetUserObjectInformationW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetUserObjectInformationW.restype = wintypes.BOOL
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.restype = wintypes.BOOL
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
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL
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
    _configure_win32()
    value = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(value)):
        raise WindowsDesktopError("GetWindowRect failed")
    return DesktopRect(value.left, value.top, value.right, value.bottom)


def _pid(hwnd: int) -> int:
    _configure_win32()
    value = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
    return int(value.value)


class _MonitorInfoExW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class Win32SemanticBackend:
    """Use native window/control semantics; no blind coordinates by default."""

    def __init__(self) -> None:
        self._uia = WindowsUIAutomationBridge()
        self._uia_runtime_ids: dict[tuple[int, int], str] = {}
        self._uia_password_ids: set[tuple[int, int]] = set()
        self._semantic_backend = "not_checked"

    def semantic_status(self) -> str:
        return self._semantic_backend

    def find_window(self, process_id: int, expected_title: str) -> DesktopWindow:
        _require_windows()
        user32, _ = _configure_win32()
        matches: list[int] = []
        owned_titles: list[str] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and _pid(hwnd) == process_id:
                title = _text(hwnd)
                owned_titles.append(title)
                if title == expected_title:
                    matches.append(int(hwnd))
            return True

        callback_ref = callback_type(callback)
        user32.EnumWindows(callback_ref, 0)
        if len(matches) != 1:
            raise WindowsDesktopError(
                "expected exactly one owned window, "
                f"found {len(matches)}; owned visible titles={owned_titles!r}"
            )
        hwnd = matches[0]
        dpi = int(getattr(ctypes.windll.user32, "GetDpiForWindow", lambda _h: 96)(hwnd))
        return DesktopWindow(hwnd, _pid(hwnd), _text(hwnd), _rect(hwnd), dpi or 96)

    def visible_windows(self) -> tuple[DesktopWindow, ...]:
        """Enumerate visible top-level windows without attaching to any of them."""

        _require_windows()
        user32, _ = _configure_win32()
        handles: list[int] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )

        def callback(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and _text(hwnd).strip():
                handles.append(int(hwnd))
            return True

        callback_ref = callback_type(callback)
        user32.EnumWindows(callback_ref, 0)
        windows: list[DesktopWindow] = []
        for hwnd in handles:
            dpi = int(
                getattr(ctypes.windll.user32, "GetDpiForWindow", lambda _h: 96)(hwnd)
            )
            windows.append(
                DesktopWindow(hwnd, _pid(hwnd), _text(hwnd), _rect(hwnd), dpi or 96)
            )
        return tuple(windows)

    def monitors(self) -> tuple[DesktopMonitor, ...]:
        """Enumerate every monitor, including negative virtual coordinates."""

        _require_windows()
        user32, _ = _configure_win32()
        monitors: list[DesktopMonitor] = []
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )

        def callback(handle, _dc, _rect_value, _lparam):
            info = _MonitorInfoExW()
            info.cbSize = ctypes.sizeof(info)
            if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                monitors.append(
                    DesktopMonitor(
                        handle=int(handle),
                        device=info.szDevice,
                        bounds=DesktopRect(
                            info.rcMonitor.left,
                            info.rcMonitor.top,
                            info.rcMonitor.right,
                            info.rcMonitor.bottom,
                        ),
                        work_area=DesktopRect(
                            info.rcWork.left,
                            info.rcWork.top,
                            info.rcWork.right,
                            info.rcWork.bottom,
                        ),
                        primary=bool(info.dwFlags & 1),
                    )
                )
            return True

        callback_ref = callback_type(callback)
        if not user32.EnumDisplayMonitors(0, None, callback_ref, 0):
            raise WindowsDesktopError("monitor enumeration failed")
        return tuple(monitors)

    def active_window(self) -> DesktopWindow:
        _require_windows()
        user32, _ = _configure_win32()
        handle = int(user32.GetForegroundWindow())
        if not handle or not user32.IsWindow(handle):
            raise WindowsDesktopError("no active desktop window")
        dpi = int(
            getattr(ctypes.windll.user32, "GetDpiForWindow", lambda _h: 96)(handle)
        )
        return DesktopWindow(handle, _pid(handle), _text(handle), _rect(handle), dpi or 96)

    def refresh_window(self, window: DesktopWindow) -> DesktopWindow:
        self._assert_owned(window.handle, window.process_id)
        if not ctypes.windll.user32.IsWindow(window.handle):
            raise WindowsDesktopError("desktop window was closed")
        dpi = int(
            getattr(ctypes.windll.user32, "GetDpiForWindow", lambda _h: 96)(
                window.handle
            )
        )
        return DesktopWindow(
            window.handle,
            window.process_id,
            _text(window.handle),
            _rect(window.handle),
            dpi or 96,
        )

    @staticmethod
    def process_executable(process_id: int) -> str:
        _require_windows()
        _configure_win32()
        process = ctypes.windll.kernel32.OpenProcess(0x1000, False, process_id)
        if not process:
            raise WindowsDesktopError("unable to inspect desktop process")
        try:
            capacity = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(capacity.value)
            if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
                process, 0, buffer, ctypes.byref(capacity)
            ):
                raise WindowsDesktopError("unable to resolve desktop executable")
            return buffer.value
        finally:
            ctypes.windll.kernel32.CloseHandle(process)

    @staticmethod
    def input_desktop_name() -> str:
        """Return the interactive desktop name; UAC/Winlogon desktops are rejected."""

        _require_windows()
        user32, _gdi32 = _configure_win32()
        desktop = user32.OpenInputDesktop(0, False, 0x0100)
        if not desktop:
            return "secure-or-unavailable"
        try:
            needed = wintypes.DWORD()
            user32.GetUserObjectInformationW(desktop, 2, None, 0, ctypes.byref(needed))
            if needed.value <= 2 or needed.value > 1024:
                return "secure-or-unavailable"
            buffer = ctypes.create_unicode_buffer(needed.value // 2)
            if not user32.GetUserObjectInformationW(
                desktop, 2, buffer, needed, ctypes.byref(needed)
            ):
                return "secure-or-unavailable"
            return buffer.value
        finally:
            user32.CloseDesktop(desktop)

    @staticmethod
    def is_owned_process(process_id: int, root_process_id: int) -> bool:
        return process_id == root_process_id

    def elements(self, window: DesktopWindow) -> tuple[DesktopElement, ...]:
        self._assert_owned(window.handle, window.process_id)
        try:
            uia_elements = self._uia.inspect(window.handle)
        except UIAutomationError:
            self._semantic_backend = "win32_fallback"
        else:
            converted: list[DesktopElement] = []
            window_keys = {
                key for key in self._uia_runtime_ids if key[0] == window.handle
            }
            for key in window_keys:
                self._uia_runtime_ids.pop(key, None)
                self._uia_password_ids.discard(key)
            for raw in uia_elements:
                runtime_id = raw.get("runtime_id")
                bounds = raw.get("bounds")
                if not isinstance(runtime_id, str) or not isinstance(bounds, dict):
                    continue
                try:
                    rect = DesktopRect(
                        int(bounds["left"]),
                        int(bounds["top"]),
                        int(bounds["right"]),
                        int(bounds["bottom"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                digest = int.from_bytes(
                    hashlib.sha256(runtime_id.encode("utf-8")).digest()[:4],
                    "big",
                ) & 0x7FFFFFFF
                semantic_id = -(digest or 1)
                while (
                    (window.handle, semantic_id) in self._uia_runtime_ids
                    and self._uia_runtime_ids[(window.handle, semantic_id)]
                    != runtime_id
                ):
                    semantic_id -= 1
                key = (window.handle, semantic_id)
                self._uia_runtime_ids[key] = runtime_id
                protected = bool(raw.get("is_password"))
                if protected:
                    self._uia_password_ids.add(key)
                converted.append(
                    DesktopElement(
                        handle=int(raw.get("native_handle") or 0),
                        process_id=window.process_id,
                        role=str(raw.get("role") or "custom").casefold()[:80],
                        name=str(raw.get("name") or "")[:512],
                        automation_id=semantic_id,
                        bounds=rect,
                        value=("" if protected else str(raw.get("value") or "")[:4096]),
                        protected=protected,
                    )
                )
            if converted:
                self._semantic_backend = "windows_uia"
                return tuple(converted)
            self._semantic_backend = "win32_fallback"
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
            if element.role != "document":
                raise WindowsDesktopError(
                    "semantic text input requires an editable control"
                )
        runtime_id = self._uia_runtime_ids.get(
            (window.handle, element.automation_id)
        )
        if runtime_id is not None:
            try:
                return self._uia.set_value(window.handle, runtime_id, value)
            except UIAutomationError as exc:
                raise WindowsDesktopError(
                    "Windows UI Automation text action failed"
                ) from exc
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
        allowed_roles = {
            "button",
            "checkbox",
            "hyperlink",
            "listitem",
            "menuitem",
            "radioButton".casefold(),
            "tabitem",
            "treeitem",
        }
        if element.role not in allowed_roles:
            raise WindowsDesktopError("semantic click requires an actionable control")
        runtime_id = self._uia_runtime_ids.get(
            (window.handle, element.automation_id)
        )
        if runtime_id is not None:
            try:
                self._uia.invoke(window.handle, runtime_id)
                return
            except UIAutomationError as exc:
                raise WindowsDesktopError(
                    "Windows UI Automation click action failed"
                ) from exc
        ctypes.windll.user32.SendMessageW(element.handle, 0x00F5, 0, 0)

    def is_password_element(
        self, window: DesktopWindow, element: DesktopElement
    ) -> bool:
        self._assert_element(window, element)
        if (window.handle, element.automation_id) in self._uia_password_ids:
            return True
        return element.role == "edit" and bool(
            ctypes.windll.user32.GetWindowLongW(element.handle, -16) & 0x0020
        )

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

    def window_state(self, window: DesktopWindow) -> str:
        self._assert_owned(window.handle, window.process_id)
        if ctypes.windll.user32.IsIconic(window.handle):
            return "minimized"
        if ctypes.windll.user32.IsZoomed(window.handle):
            return "maximized"
        return "restored"

    def set_window_state(self, window: DesktopWindow, state: str) -> str:
        self._assert_owned(window.handle, window.process_id)
        commands = {"minimized": 6, "maximized": 3, "restored": 9}
        if state not in commands:
            raise WindowsDesktopError("unsupported window state")
        ctypes.windll.user32.ShowWindow(window.handle, commands[state])
        observed = self.window_state(window)
        if observed != state:
            raise WindowsDesktopError("window state verification failed")
        return observed

    def move_window(self, window: DesktopWindow, bounds: DesktopRect) -> DesktopWindow:
        self._assert_owned(window.handle, window.process_id)
        if bounds.width < 160 or bounds.height < 100:
            raise WindowsDesktopError("window bounds are too small")
        if not ctypes.windll.user32.MoveWindow(
            window.handle,
            bounds.left,
            bounds.top,
            bounds.width,
            bounds.height,
            True,
        ):
            raise WindowsDesktopError("window move failed")
        observed = self.refresh_window(window)
        if observed.bounds != bounds:
            raise WindowsDesktopError("window bounds verification failed")
        return observed

    def clipboard_read(self) -> str:
        _require_windows()
        user32, _ = _configure_win32()
        if not user32.OpenClipboard(0):
            raise WindowsDesktopError("clipboard is busy")
        try:
            handle = user32.GetClipboardData(13)
            if not handle:
                return ""
            pointer = ctypes.windll.kernel32.GlobalLock(handle)
            if not pointer:
                raise WindowsDesktopError("clipboard text is unavailable")
            try:
                return ctypes.wstring_at(pointer)
            finally:
                ctypes.windll.kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def clipboard_write(self, value: str) -> str:
        _require_windows()
        user32, _ = _configure_win32()
        encoded = (value + "\0").encode("utf-16-le")
        handle = ctypes.windll.kernel32.GlobalAlloc(0x0042, len(encoded))
        if not handle:
            raise WindowsDesktopError("clipboard allocation failed")
        pointer = ctypes.windll.kernel32.GlobalLock(handle)
        if not pointer:
            ctypes.windll.kernel32.GlobalFree(handle)
            raise WindowsDesktopError("clipboard allocation could not be locked")
        ctypes.memmove(pointer, encoded, len(encoded))
        ctypes.windll.kernel32.GlobalUnlock(handle)
        ownership_transferred = False
        if not user32.OpenClipboard(0):
            ctypes.windll.kernel32.GlobalFree(handle)
            raise WindowsDesktopError("clipboard is busy")
        try:
            user32.EmptyClipboard()
            if not user32.SetClipboardData(13, handle):
                raise WindowsDesktopError("clipboard write failed")
            ownership_transferred = True
        finally:
            user32.CloseClipboard()
            if not ownership_transferred:
                ctypes.windll.kernel32.GlobalFree(handle)
        observed = self.clipboard_read()
        if observed != value:
            raise WindowsDesktopError("clipboard verification failed")
        return observed

    def send_hotkey(self, window: DesktopWindow, chord: str) -> None:
        self._assert_owned(window.handle, window.process_id)
        if not self.is_focused(window):
            raise WindowsDesktopError("hotkey target lost focus")
        keys = {
            "ctrl": 0x11,
            "shift": 0x10,
            "alt": 0x12,
            "a": 0x41,
            "c": 0x43,
            "f": 0x46,
            "v": 0x56,
            "x": 0x58,
            "y": 0x59,
            "z": 0x5A,
            "tab": 0x09,
        }
        parts = chord.casefold().split("+")
        try:
            virtual_keys = [keys[part] for part in parts]
        except KeyError as exc:
            raise WindowsDesktopError("hotkey is not allowlisted") from exc
        for key in virtual_keys:
            ctypes.windll.user32.keybd_event(key, 0, 0, 0)
        for key in reversed(virtual_keys):
            ctypes.windll.user32.keybd_event(key, 0, 0x0002, 0)

    def scroll(self, window: DesktopWindow, delta: int) -> None:
        self._assert_owned(window.handle, window.process_id)
        if not self.is_focused(window):
            raise WindowsDesktopError("scroll target lost focus")
        current = self.refresh_window(window)
        x = current.bounds.left + current.bounds.width // 2
        y = current.bounds.top + current.bounds.height // 2
        ctypes.windll.user32.SetCursorPos(x, y)
        ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(delta), 0)

    def close(self, window: DesktopWindow) -> None:
        self._assert_owned(window.handle, window.process_id)
        ctypes.windll.user32.PostMessageW(window.handle, 0x0010, 0, 0)

    def interrupt_semantic(self) -> None:
        self._uia.interrupt()

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

    def screenshot_region(self, bounds: DesktopRect) -> bytes:
        """Capture one validated virtual-screen region as BMP bytes."""

        _require_windows()
        if bounds.width <= 0 or bounds.height <= 0:
            raise WindowsDesktopError("invalid screenshot region")
        user32, gdi32 = _configure_win32()
        screen_dc = user32.GetDC(0)
        memory_dc = gdi32.CreateCompatibleDC(screen_dc)
        bitmap = gdi32.CreateCompatibleBitmap(
            screen_dc, bounds.width, bounds.height
        )
        old = gdi32.SelectObject(memory_dc, bitmap)
        try:
            if not gdi32.BitBlt(
                memory_dc,
                0,
                0,
                bounds.width,
                bounds.height,
                screen_dc,
                bounds.left,
                bounds.top,
                0x00CC0020,
            ):
                raise WindowsDesktopError("screen capture failed")
            header = _BitmapInfoHeader()
            header.biSize = ctypes.sizeof(_BitmapInfoHeader)
            header.biWidth = bounds.width
            header.biHeight = -bounds.height
            header.biPlanes = 1
            header.biBitCount = 32
            pixel_size = bounds.width * bounds.height * 4
            pixels = ctypes.create_string_buffer(pixel_size)
            info = _BitmapInfo()
            info.bmiHeader = header
            if not gdi32.GetDIBits(
                memory_dc,
                bitmap,
                0,
                bounds.height,
                pixels,
                ctypes.byref(info),
                0,
            ):
                raise WindowsDesktopError("screen capture encoding failed")
            return struct.pack(
                "<2sIHHI", b"BM", 54 + pixel_size, 0, 0, 54
            ) + struct.pack(
                "<IiiHHIIiiII",
                40,
                bounds.width,
                -bounds.height,
                1,
                32,
                0,
                pixel_size,
                0,
                0,
                0,
                0,
            ) + pixels.raw
        finally:
            gdi32.SelectObject(memory_dc, old)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(memory_dc)
            user32.ReleaseDC(0, screen_dc)

    @staticmethod
    def _assert_owned(hwnd: int, process_id: int) -> None:
        if _pid(hwnd) != process_id:
            raise WindowsDesktopError("window ownership changed")

    def _assert_element(self, window: DesktopWindow, element: DesktopElement) -> None:
        self._assert_owned(window.handle, window.process_id)
        if (window.handle, element.automation_id) in self._uia_runtime_ids:
            if element.process_id != window.process_id:
                raise WindowsDesktopError("element escaped the owned process")
            return
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
