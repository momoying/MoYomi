"""Window sizing in logical pixels and uniform scaling of the existing UI."""

from __future__ import annotations

import math
import os


WINDOW_WIDTH, WINDOW_HEIGHT = 1350, 860
# Client area of the original Windows window, excluding its native frame.
CANVAS_WIDTH, CANVAS_HEIGHT = 1334, 821


def fit_window(work_area: tuple[float, float] | None) -> tuple[float, float]:
    scale = 1.0
    if work_area is not None:
        scale = min(1.0, work_area[0] * 0.9 / WINDOW_WIDTH, work_area[1] * 0.9 / WINDOW_HEIGHT)
    return WINDOW_WIDTH * scale, WINDOW_HEIGHT * scale


def fit_canvas(width: float, height: float) -> tuple[float, float, float] | None:
    if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
        return None
    scale = min(width / CANVAS_WIDTH, height / CANVAS_HEIGHT)
    return scale, (width - CANVAS_WIDTH * scale) / 2, (height - CANVAS_HEIGHT * scale) / 2


def windows_work_area(title: str) -> tuple[float, float] | None:
    """Read the current monitor's work area without changing process DPI awareness."""
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("size", wintypes.DWORD), ("monitor", wintypes.RECT),
            ("work", wintypes.RECT), ("flags", wintypes.DWORD),
        ]

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.SetThreadDpiAwarenessContext.argtypes = [wintypes.HANDLE]
        user32.SetThreadDpiAwarenessContext.restype = wintypes.HANDLE
        user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        user32.FindWindowW.restype = wintypes.HWND
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HANDLE
        user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
        user32.GetDpiForSystem.restype = wintypes.UINT
        previous = user32.SetThreadDpiAwarenessContext(wintypes.HANDLE(-4))
        if not previous:
            return None
        try:
            window = user32.FindWindowW(None, title) or user32.GetForegroundWindow()
            monitor = user32.MonitorFromWindow(window, 1)
            info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
            if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                return None
            dpi = user32.GetDpiForWindow(window) if window else user32.GetDpiForSystem()
            if not dpi:
                return None
            width, height = info.work.right - info.work.left, info.work.bottom - info.work.top
            return (width * 96 / dpi, height * 96 / dpi) if width > 0 and height > 0 else None
        finally:
            user32.SetThreadDpiAwarenessContext(previous)
    except (AttributeError, OSError):
        return None
