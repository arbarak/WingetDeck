"""What this terminal and this Windows can do."""

from __future__ import annotations

import ctypes
import locale
import os
import platform
import re
import struct
import sys
from collections.abc import Mapping
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


def detect_terminal(env: Mapping[str, str] | None = None, font: str | None = None) -> TerminalInfo:
    if env is None:
        env, font = os.environ, console_font()
    if env.get("WT_SESSION"):
        return TerminalInfo("Windows Terminal", False)
    if env.get("TERM_PROGRAM"):
        return TerminalInfo(env["TERM_PROGRAM"], False)
    if env.get("ConEmuPID"):
        return TerminalInfo("ConEmu", False)
    return TerminalInfo("classic console", font == _RASTER_FONT)


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
        "size": f"{size[0]}x{size[1]}",
        "locale": locale_name,
        "elevated": elevated,
        "demo": demo,
    }
