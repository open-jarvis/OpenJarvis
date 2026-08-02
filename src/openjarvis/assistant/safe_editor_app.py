"""Small owned Win32 text editor used by the desktop assistant tool.

The process accepts only a filename below the pre-validated assistant
workspace.  It refuses overwrites and exits when its owning tool process dies.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import re
from ctypes import wintypes
from pathlib import Path

TITLE = "OpenJarvis Safe Text Editor"
EDIT_ID = 1001
SAVE_ID = 1002
STATUS_ID = 1003
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}\.(?:txt|md)$")

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
user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _loword(value: int) -> int:
    return value & 0xFFFF


def _root() -> Path:
    raw = os.environ.get("OPENJARVIS_ASSISTANT_WORKSPACE", "")
    if not raw:
        raise RuntimeError("assistant workspace is unavailable")
    root = Path(raw).resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError("assistant workspace is invalid")
    return root


def _output_path(filename: str) -> Path:
    if not _NAME.fullmatch(filename) or Path(filename).name != filename:
        raise ValueError("output filename is not allowed")
    return _root() / filename


def _control_text(handle: int) -> str:
    length = int(user32.SendMessageW(handle, 0x000E, 0, 0))
    buffer = ctypes.create_unicode_buffer(length + 1)
    pointer = ctypes.cast(buffer, ctypes.c_void_p).value or 0
    user32.SendMessageW(handle, 0x000D, len(buffer), pointer)
    return buffer.value


def _parent_alive(parent_pid: int) -> bool:
    handle = kernel32.OpenProcess(0x1000, False, parent_pid)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


def run(filename: str, parent_pid: int) -> int:
    destination = _output_path(filename)
    if destination.exists():
        raise FileExistsError("refusing to overwrite an existing assistant file")

    wndproc_type = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class WndClassW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", wndproc_type),
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
        if message == 0x0111 and _loword(wparam) == SAVE_ID:
            edit = user32.GetDlgItem(hwnd, EDIT_ID)
            status = user32.GetDlgItem(hwnd, STATUS_ID)
            try:
                descriptor = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                with os.fdopen(
                    descriptor, "w", encoding="utf-8", newline="\n"
                ) as stream:
                    stream.write(_control_text(edit))
                user32.SetWindowTextW(status, "Saved")
            except FileExistsError:
                user32.SetWindowTextW(status, "Refused: file exists")
            except OSError:
                user32.SetWindowTextW(status, "Save failed")
            return 0
        if message == 0x0113 and not _parent_alive(parent_pid):
            user32.DestroyWindow(hwnd)
            return 0
        if message == 0x0010:
            user32.DestroyWindow(hwnd)
            return 0
        if message == 0x0002:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    callback = wndproc_type(window_proc)
    window_class = WndClassW()
    window_class.lpfnWndProc = callback
    window_class.hInstance = kernel32.GetModuleHandleW(None)
    window_class.lpszClassName = f"OpenJarvisSafeEditor{os.getpid()}"
    window_class.hCursor = user32.LoadCursorW(None, 32512)
    if not user32.RegisterClassW(ctypes.byref(window_class)):
        raise ctypes.WinError()

    window = user32.CreateWindowExW(
        0,
        window_class.lpszClassName,
        TITLE,
        0x00CF0000,
        120,
        120,
        720,
        480,
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
        0x503110C4,
        20,
        20,
        660,
        330,
        window,
        EDIT_ID,
        window_class.hInstance,
        None,
    )
    user32.CreateWindowExW(
        0,
        "BUTTON",
        "Save test file",
        0x50010000,
        20,
        370,
        160,
        32,
        window,
        SAVE_ID,
        window_class.hInstance,
        None,
    )
    user32.CreateWindowExW(
        0,
        "STATIC",
        f"Ready: {filename}",
        0x50000000,
        200,
        375,
        470,
        28,
        window,
        STATUS_ID,
        window_class.hInstance,
        None,
    )
    user32.SetTimer(window, 1, 1000, None)
    user32.ShowWindow(window, 5)
    user32.UpdateWindow(window)

    message = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(message))
        user32.DispatchMessageW(ctypes.byref(message))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("filename")
    parser.add_argument("parent_pid", type=int)
    args = parser.parse_args()
    return run(args.filename, args.parent_pid)


if __name__ == "__main__":
    raise SystemExit(main())
