"""Run the app in a real Windows pseudo-console, resize it, and check it survives.

The unit tests use Textual's headless driver. This uses the real one, with no window on the desktop.

    python scripts/pty_check.py [--exe path\\to\\WingetDeck.exe]
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from pathlib import Path

from winpty import PtyProcess

SIZES = [(160, 50), (120, 30), (80, 24), (60, 20), (50, 16), (40, 10), (120, 40)]
TITLE = re.compile(r"\x1b\]0;([^\x07\x1b]*)")
QUIT_WAIT_SECONDS = 15


class Reader(threading.Thread):
    def __init__(self, process: PtyProcess) -> None:
        super().__init__(daemon=True)
        self.process = process
        self.seen = ""

    def run(self) -> None:
        while True:
            try:
                chunk = self.process.read(65536)
            except EOFError:
                return
            self.seen += chunk  # after the read, or clearing `seen` during it would be undone

    def wait_for(self, text: str, seconds: float = 20.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if text in self.seen:
                return True
            time.sleep(0.1)
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    command = [args.exe, "--demo"] if args.exe else [sys.executable, "-m", "wingetdeck", "--demo"]
    process = PtyProcess.spawn(command, dimensions=(40, 120), cwd=str(root))
    reader = Reader(process)
    reader.start()
    failures: list[str] = []

    def check(name: str, ok: bool) -> None:
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
        if not ok:
            failures.append(name)

    check("splash appears", reader.wait_for("WingetDeck"))
    check("window title is set", bool(TITLE.search(reader.seen)))
    check("Start button appears", reader.wait_for("Start"))
    for columns, rows in SIZES:
        reader.seen = ""
        process.setwinsize(rows, columns)
        time.sleep(1.0)
        check(f"alive after resize to {columns}x{rows}", process.isalive())
        if (columns, rows) == (40, 10):
            check("too-small message at 40x10", reader.wait_for("Window too", 5))
        elif (columns, rows) == (120, 40):
            check("draws again at 120x40", reader.wait_for("Start", 5))
    process.write("\r")  # the Start button
    check("package table opens", reader.wait_for("Upgrade", 15))
    process.setwinsize(24, 80)
    time.sleep(1.0)
    check("alive after resize on the table", process.isalive())
    process.write("\x11")  # Ctrl+Q
    deadline = time.monotonic() + QUIT_WAIT_SECONDS
    while process.isalive() and time.monotonic() < deadline:
        time.sleep(0.2)
    check("quits cleanly", not process.isalive())
    if process.isalive():
        process.terminate(force=True)
    else:
        check("exit code 0", process.exitstatus == 0)
    print("FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
