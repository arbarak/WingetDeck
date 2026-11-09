"""Talking to the Windows console itself."""

from __future__ import annotations

import ctypes
from collections.abc import Callable

CTRL_C = 0
CTRL_BREAK = 1
CTRL_CLOSE = 2
CTRL_LOGOFF = 5
CTRL_SHUTDOWN = 6
_CLOSING = {CTRL_BREAK, CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN}

_keep_alive = []  # Windows holds the only other reference to the callback


def make_ctrl_handler(on_close: Callable[[], None]) -> Callable[[int], bool]:
    def handler(event: int) -> bool:
        if event not in _CLOSING:
            return False  # Ctrl+C reaches the app as a key press
        try:
            on_close()
        except Exception:  # noqa: BLE001 - Windows is ending the process, there is nobody to tell
            pass
        return True

    return handler


def install_close_handler(on_close: Callable[[], None]) -> None:
    """Closing the console ends this process with no warning to the event loop. This is the only
    chance to thaw a frozen winget."""
    prototype = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)
    callback = prototype(make_ctrl_handler(on_close))
    _keep_alive.append(callback)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(callback, True)
