"""What this terminal and this Windows can do."""

from __future__ import annotations

import ctypes
import locale
import os
import platform
import re
import struct
import sys
from collections.abc import Callable, Mapping
from ctypes import wintypes
from dataclasses import dataclass
from typing import Any, Protocol

from .. import __version__

ENABLE_QUICK_EDIT_MODE = 0x0040
ENABLE_EXTENDED_FLAGS = 0x0080
STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
MIN_BUILD = 17763  # Windows 10 1809, the oldest winget runs on
MIN_WINGET = (1, 4)  # the first with --include-unknown, which the table relies on
_DEVELOPMENT_BUILD = (0, 0)  # not a release, so its number says nothing about its age
_RASTER_FONT = "Terminal"
_DEFAULT_CHARSET = 1
_MARK_MISSING = 1  # GGI_MARK_NONEXISTING_GLYPHS
_NO_GLYPH = 0xFFFF
_READ_WRITE = 0xC0000000
_SHARE_READ_WRITE = 3
_OPEN_EXISTING = 3
_INVALID_HANDLE = 2**64 - 1 if struct.calcsize("P") == 8 else 2**32 - 1
_SB_BOTH = 3
_VERSION = re.compile(r"v?(\d+)\.(\d+)")


class Console(Protocol):
    def get_mode(self) -> int | None: ...

    def set_mode(self, mode: int) -> bool: ...


def _kernel32() -> Any:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel.GetStdHandle.restype = wintypes.HANDLE
    kernel.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetConsoleMode.restype = wintypes.BOOL
    kernel.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.SetConsoleMode.restype = wintypes.BOOL
    return kernel


class RealConsole:
    """The input side of this process's console. With no console, get_mode answers None."""

    def __init__(self) -> None:
        self._kernel = _kernel32()
        self._handle = self._kernel.GetStdHandle(STD_INPUT_HANDLE & 0xFFFFFFFF)

    def get_mode(self) -> int | None:
        mode = wintypes.DWORD()
        return mode.value if self._kernel.GetConsoleMode(self._handle, ctypes.byref(mode)) else None

    def set_mode(self, mode: int) -> bool:
        return bool(self._kernel.SetConsoleMode(self._handle, mode))


class QuickEditGuard:
    """QuickEdit makes the classic console treat a click as "select text", so buttons would not work."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console if console is not None else RealConsole()
        self._saved: int | None = None

    def __enter__(self) -> QuickEditGuard:
        self._saved = self._console.get_mode()
        if self._saved is not None:
            self._console.set_mode((self._saved & ~ENABLE_QUICK_EDIT_MODE) | ENABLE_EXTENDED_FLAGS)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._saved is not None:
            self._console.set_mode(self._saved)


@dataclass(frozen=True)
class TerminalInfo:
    name: str
    ascii_recommended: bool
    basic_symbols: bool = False
    font: str | None = None


class _CoordFont(ctypes.Structure):
    _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]


class _FontInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.ULONG),
        ("nFont", wintypes.DWORD),
        ("dwFontSize", _CoordFont),
        ("FontFamily", wintypes.UINT),
        ("FontWeight", wintypes.UINT),
        ("FaceName", wintypes.WCHAR * 32),
    ]


def console_font() -> str | None:
    """The classic console's font name, or None when it cannot be read."""
    try:
        kernel = _kernel32()
        info = _FontInfo(cbSize=ctypes.sizeof(_FontInfo))
        handle = kernel.GetStdHandle(STD_OUTPUT_HANDLE & 0xFFFFFFFF)
        ok = kernel.GetCurrentConsoleFontEx(wintypes.HANDLE(handle), False, ctypes.byref(info))
    except (OSError, AttributeError, ValueError):
        return None
    return info.FaceName if ok else None


def console_window_visible() -> bool:
    """A console hosted by another terminal has a hidden window, and that terminal does the drawing."""
    try:
        user = ctypes.WinDLL("user32")
        kernel = _kernel32()
        kernel.GetConsoleWindow.restype = wintypes.HWND
        user.IsWindowVisible.argtypes = [wintypes.HWND]
        window = kernel.GetConsoleWindow()
        return bool(window and user.IsWindowVisible(window))
    except (OSError, AttributeError, ValueError):
        return False


def font_has_glyph(face: str) -> Callable[[str], bool] | None:
    """Ask Windows whether a font can draw a character, or None when the font cannot be read."""
    try:
        gdi = ctypes.WinDLL("gdi32")
        gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
        gdi.CreateCompatibleDC.restype = wintypes.HDC
        gdi.CreateFontW.restype = wintypes.HANDLE
        gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
        gdi.SelectObject.restype = wintypes.HANDLE
        gdi.GetGlyphIndicesW.argtypes = [
            wintypes.HDC,
            wintypes.LPCWSTR,
            ctypes.c_int,
            ctypes.POINTER(wintypes.WORD),
            wintypes.DWORD,
        ]
        gdi.GetGlyphIndicesW.restype = wintypes.DWORD
        context = gdi.CreateCompatibleDC(None)
        font = gdi.CreateFontW(16, 0, 0, 0, 400, 0, 0, 0, _DEFAULT_CHARSET, 0, 0, 0, 0, face)
        if not context or not font or not gdi.SelectObject(context, font):
            return None
    except (OSError, AttributeError, ValueError):
        return None

    def has(char: str) -> bool:
        if ord(char) > 0xFFFF:  # the classic console draws one 16-bit character per cell
            return False
        glyph = wintypes.WORD()
        done = gdi.GetGlyphIndicesW(context, char, 1, ctypes.byref(glyph), _MARK_MISSING)
        return done == 1 and glyph.value != _NO_GLYPH

    return has


class _CursorInfo(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("bVisible", wintypes.BOOL)]


class _Coord(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _SmallRect(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short), ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]


class _BufferInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.ULONG),
        ("dwSize", _Coord),
        ("dwCursorPosition", _Coord),
        ("wAttributes", wintypes.WORD),
        ("srWindow", _SmallRect),
        ("dwMaximumWindowSize", _Coord),
        ("wPopupAttributes", wintypes.WORD),
        ("bFullscreenSupported", wintypes.BOOL),
        ("ColorTable", wintypes.DWORD * 16),
    ]


class _FontInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.ULONG),
        ("nFont", wintypes.DWORD),
        ("dwFontSize", _Coord),
        ("FontFamily", wintypes.UINT),
        ("FontWeight", wintypes.UINT),
        ("FaceName", wintypes.WCHAR * 32),
    ]


def filled_size(client: tuple[int, int], font: tuple[int, int], buffer: tuple[int, int]) -> tuple[int, int] | None:
    """The text area, in characters, that fills a window of `client` pixels, or None to leave it as it is."""
    if min(font) <= 0:
        return None
    columns, rows = client[0] // font[0], client[1] // font[1]
    if columns < 1 or rows < 1 or (columns, rows) == tuple(buffer):
        return None
    return columns, rows


def _fill_window(kernel: Any, output: int, window: int) -> None:
    """The console leaves room for its scrollbar even once it is hidden, and never draws there. Widen the text area
    into that room. The console then reports the new size, and the app redraws to the edge."""
    user = ctypes.WinDLL("user32")
    rect = wintypes.RECT()
    if not user.GetClientRect(wintypes.HWND(window), ctypes.byref(rect)):
        return
    info, font = _BufferInfo(), _FontInfo()
    info.cbSize, font.cbSize = ctypes.sizeof(_BufferInfo), ctypes.sizeof(_FontInfo)
    handle = wintypes.HANDLE(output)
    if not kernel.GetConsoleScreenBufferInfoEx(handle, ctypes.byref(info)):
        return
    if not kernel.GetCurrentConsoleFontEx(handle, False, ctypes.byref(font)):
        return
    size = filled_size(
        (rect.right, rect.bottom), (font.dwFontSize.X, font.dwFontSize.Y), (info.dwSize.X, info.dwSize.Y)
    )
    if size is None:
        return
    info.dwSize = _Coord(*size)
    info.srWindow = _SmallRect(0, 0, *size)  # this call reads the right and bottom edges as one past the end
    kernel.SetConsoleScreenBufferInfoEx(handle, ctypes.byref(info))


def tidy_classic_console() -> None:
    """The classic console leaves its cursor blinking and keeps its scrollbars, though nothing can scroll.
    Once they are hidden, the text area is widened into the room they leave."""
    try:
        kernel = _kernel32()
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel.GetConsoleWindow.restype = wintypes.HWND
        user = ctypes.WinDLL("user32")
        user.ShowScrollBar.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.BOOL]
        window = kernel.GetConsoleWindow()
        if window:
            user.ShowScrollBar(window, _SB_BOTH, False)
        output = kernel.CreateFileW("CONOUT$", _READ_WRITE, _SHARE_READ_WRITE, None, _OPEN_EXISTING, 0, None)
        if output and output != _INVALID_HANDLE:
            try:
                if window:
                    _fill_window(kernel, output, window)
                cursor = _CursorInfo(25, False)  # after the resize, which can bring the cursor back
                kernel.SetConsoleCursorInfo(wintypes.HANDLE(output), ctypes.byref(cursor))
            finally:
                kernel.CloseHandle(wintypes.HANDLE(output))
    except (OSError, AttributeError, ValueError):
        pass  # only looks: the app works the same with them showing


def detect_terminal(
    env: Mapping[str, str] | None = None, font: str | None = None, window_visible: bool = True
) -> TerminalInfo:
    if env is None:
        env, font, window_visible = os.environ, console_font(), console_window_visible()
    if env.get("WT_SESSION"):
        return TerminalInfo("Windows Terminal", False)
    if env.get("TERM_PROGRAM"):
        return TerminalInfo(env["TERM_PROGRAM"], False)
    if env.get("ConEmuPID"):
        return TerminalInfo("ConEmu", False)
    if not window_visible:
        return TerminalInfo("terminal with its own window", False)
    if font == _RASTER_FONT:
        return TerminalInfo("classic console", True, False, font)
    return TerminalInfo("classic console", False, True, font)


def windows_build() -> int:
    return sys.getwindowsversion().build


def check_support(build: int) -> str | None:
    if build >= MIN_BUILD:
        return None
    return (
        f"WingetDeck needs Windows 10 version 1809 (build {MIN_BUILD}) or newer, "
        f"because winget cannot run on older Windows. This PC is on build {build}."
    )


def winget_too_old(version: str) -> bool:
    found = _VERSION.search(version)
    if not found:
        return False
    number = int(found[1]), int(found[2])
    return number != _DEVELOPMENT_BUILD and number < MIN_WINGET


def user_locale() -> str:
    buffer = ctypes.create_unicode_buffer(85)
    try:
        if ctypes.windll.kernel32.GetUserDefaultLocaleName(buffer, len(buffer)):
            return buffer.value
    except (OSError, AttributeError):
        pass
    return locale.getlocale()[0] or "unknown"


def session_header(
    demo: bool, terminal: TerminalInfo, size: tuple[int, int], locale_name: str, elevated: bool
) -> dict[str, Any]:
    """What a bug report needs. Winget's own details follow as the "winget found" event, once it has answered."""
    return {
        "app": __version__,
        "windows": platform.version(),
        "build": windows_build(),
        "machine": platform.machine(),
        "bits": struct.calcsize("P") * 8,
        "terminal": terminal.name,
        "font": terminal.font,
        "size": f"{size[0]}x{size[1]}",
        "locale": locale_name,
        "elevated": elevated,
        "demo": demo,
    }
