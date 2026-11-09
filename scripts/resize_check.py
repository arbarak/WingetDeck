"""Opens the exe's demo in a classic console, resizes the window like a user would, and measures whether the console's
text area covers the whole window. Demo mode only. Prints, for each size, the window's room in columns against the
console buffer's width, and saves a picture of the window.

    python scripts/resize_check.py <exe> <out folder>
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

exe, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
user, kernel, gdi = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("gdi32")

env = {k: v for k, v in os.environ.items() if k.upper() not in {"WT_SESSION", "WT_PROFILE_ID", "TERM_PROGRAM", "CONEMUPID"}}
proc = subprocess.Popen(["conhost.exe", str(exe), "--demo"], env=env)

EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find():
    found = []

    def each(h, _):
        cls, title = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(128)
        user.GetClassNameW(h, cls, 64)
        user.GetWindowTextW(h, title, 128)
        if cls.value == "ConsoleWindowClass" and user.IsWindowVisible(h) and title.value.startswith("WingetDeck"):
            found.append(h)
            return False
        return True

    user.EnumWindows(EnumProc(each), 0)
    return found[0] if found else None


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short), ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]


class CSBI(ctypes.Structure):
    _fields_ = [("dwSize", COORD), ("dwCursorPosition", COORD), ("wAttributes", wintypes.WORD),
                ("srWindow", SMALL_RECT), ("dwMaximumWindowSize", COORD)]


class FONT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.ULONG), ("nFont", wintypes.DWORD), ("dwFontSize", COORD),
                ("FontFamily", wintypes.UINT), ("FontWeight", wintypes.UINT), ("FaceName", wintypes.WCHAR * 32)]


def console_pid(window):
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(window, ctypes.byref(pid))
    return pid.value


def measure(window):
    """Attach to the app's console (this script has none of its own while measuring) and read its buffer."""
    kernel.FreeConsole()
    if not kernel.AttachConsole(target_pid):
        return None
    try:
        h = kernel.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
        info, font = CSBI(), FONT()
        font.cbSize = ctypes.sizeof(FONT)
        kernel.GetConsoleScreenBufferInfo(h, ctypes.byref(info))
        kernel.GetCurrentConsoleFontEx(h, False, ctypes.byref(font))
        kernel.CloseHandle(h)
    finally:
        kernel.FreeConsole()
    rect = wintypes.RECT()
    user.GetClientRect(window, ctypes.byref(rect))
    cw, ch = font.dwFontSize.X or 8, font.dwFontSize.Y or 16
    return {
        "client_cols": rect.right // cw, "client_rows": rect.bottom // ch,
        "buffer": (info.dwSize.X, info.dwSize.Y),
        "view": (info.srWindow.Right - info.srWindow.Left + 1, info.srWindow.Bottom - info.srWindow.Top + 1),
        "font": (cw, ch),
    }


def snap(window, name):
    rect = wintypes.RECT()
    user.GetWindowRect(window, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    screen = user.GetDC(None)
    dc = gdi.CreateCompatibleDC(screen)
    bmp = gdi.CreateCompatibleBitmap(screen, w, h)
    gdi.SelectObject(dc, bmp)
    user.PrintWindow(window, dc, 2)
    header = (ctypes.c_byte * 40)()
    ctypes.memmove(header, (ctypes.c_int32 * 3)(40, w, -h), 12)
    ctypes.memmove(ctypes.byref(header, 12), (ctypes.c_int16 * 2)(1, 32), 4)
    pixels = (ctypes.c_byte * (w * h * 4))()
    gdi.GetDIBits(dc, bmp, 0, h, pixels, header, 0)
    file_header = b"BM" + (54 + len(pixels)).to_bytes(4, "little") + b"\0\0\0\0" + (54).to_bytes(4, "little")
    (out / f"{name}.bmp").write_bytes(file_header + bytes(header) + bytes(pixels))
    gdi.DeleteObject(bmp)
    gdi.DeleteDC(dc)
    user.ReleaseDC(None, screen)


window = None
for _ in range(75):
    window = find()
    if window:
        break
    time.sleep(0.2)
if not window:
    proc.kill()
    raise SystemExit("no console window")
target_pid = console_pid(window)
time.sleep(4)
results = []
try:
    steps = [("start", None)]
    steps += [(f"drag{w}", (60, 60, w, 520)) for w in range(1000, 1301, 37)]  # dragging the edge wider in small steps
    steps += [("maximized", "max"), ("restored", "restore")]
    steps += [(f"shrink{w}", (60, 60, w, 600)) for w in range(1200, 799, -53)]
    for name, how in steps:
        if how == "max":
            user.ShowWindow(window, 3)
        elif how == "restore":
            user.ShowWindow(window, 9)
        elif how:
            user.MoveWindow(window, *how, True)
        time.sleep(0.15 if name.startswith(("drag", "shrink")) else 1.5)
        if name in ("start", "maximized", "restored") or name == steps[-1][0] or name == f"drag{range(1000, 1301, 37)[-1]}":
            time.sleep(1.5)
            m = measure(window)
            snap(window, name)
            results.append((name, m))
            print(name, m, flush=True)
finally:
    proc.kill()
    subprocess.run(["taskkill", "/f", "/im", exe.name], capture_output=True)

bad = [n for n, m in results if m and m["buffer"][0] < m["client_cols"]]
print("gap between the buffer and the window at:", bad or "none")
print("PASSED" if not bad else "FAILED")
raise SystemExit(1 if bad else 0)
