"""Synthetic native Win32 controls used only by Phase-5 desktop tests."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

TITLE = "OpenJarvis Phase 5 Synthetic Desktop"
EDIT_ID = 1001
BUTTON_ID = 1002
STATUS_ID = 1003

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
user32.LoadCursorW.restype = wintypes.HANDLE
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    ctypes.c_void_p,
]
user32.GetDlgItem.restype = wintypes.HWND
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]


def loword(value: int) -> int:
    return value & 0xFFFF


WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t,
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WndClassW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


def window_proc(hwnd, message, wparam, lparam):
    if message == 0x0111 and loword(wparam) == BUTTON_ID:
        status = user32.GetDlgItem(hwnd, STATUS_ID)
        user32.SetWindowTextW(status, "Verified: clicked")
        return 0
    if message == 0x0010:
        user32.DestroyWindow(hwnd)
        return 0
    if message == 0x0002:
        user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, message, wparam, lparam)


callback = WNDPROC(window_proc)
window_class = WndClassW()
window_class.lpfnWndProc = callback
window_class.hInstance = kernel32.GetModuleHandleW(None)
window_class.lpszClassName = "OpenJarvisPhase5Synthetic"
window_class.hCursor = user32.LoadCursorW(None, 32512)
if not user32.RegisterClassW(ctypes.byref(window_class)):
    raise ctypes.WinError()

window = user32.CreateWindowExW(
    0,
    window_class.lpszClassName,
    TITLE,
    0x00CF0000,
    100,
    100,
    520,
    240,
    None,
    None,
    window_class.hInstance,
    None,
)
if not window:
    raise ctypes.WinError()
user32.CreateWindowExW(
    0,
    "EDIT",
    "",
    0x50010080,
    20,
    30,
    300,
    28,
    window,
    EDIT_ID,
    window_class.hInstance,
    None,
)
user32.CreateWindowExW(
    0,
    "BUTTON",
    "Apply fake text",
    0x50010000,
    340,
    30,
    140,
    28,
    window,
    BUTTON_ID,
    window_class.hInstance,
    None,
)
user32.CreateWindowExW(
    0,
    "STATIC",
    "Ready",
    0x50000000,
    20,
    90,
    460,
    28,
    window,
    STATUS_ID,
    window_class.hInstance,
    None,
)
user32.ShowWindow(window, 5)
user32.UpdateWindow(window)

message = wintypes.MSG()
while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
    user32.TranslateMessage(ctypes.byref(message))
    user32.DispatchMessageW(ctypes.byref(message))
