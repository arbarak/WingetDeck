"""Run a built exe against this PC's real winget: scan only. It never presses Upgrade.

    python scripts/real_scan_check.py path\\to\\WingetDeck.exe

Opens the exe in a pseudo console with no window on the desktop, goes to the package table, waits for the
scan, resizes, quits, then prints what the session log recorded.
"""

from __future__ import annotations

import re
import sys
import threading
import time
from pathlib import Path

from winpty import PtyProcess

SCAN_SECONDS = 180
failures: list[str] = []


def check(name: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        failures.append(name)


def main() -> int:
    exe = Path(sys.argv[1]).resolve()
    data = exe.parent / "WingetDeck-data"
    before = set(data.glob("logs/session_*.log"))
    process = PtyProcess.spawn([str(exe)], dimensions=(36, 120), cwd=str(exe.parent))
    seen: list[str] = []

    def read() -> None:
        while True:
            try:
                chunk = process.read(65536)
            except EOFError:
                return
            seen.append(chunk)

    threading.Thread(target=read, daemon=True).start()

    def wait_for(pattern: str, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if re.search(pattern, "".join(seen)):
                return True
            time.sleep(0.2)
        return False

    check("splash shows the real winget version", wait_for(r"winget v\d+\.\d+", 60))
    process.write("\r")  # Start. Nothing in this script ever sends the Upgrade key or clicks it.
    check("the scan finishes", wait_for(r"upgrade\(s\) available|No upgrades|up to date", SCAN_SECONDS))
    for rows, columns in ((24, 80), (16, 50), (36, 120)):
        process.setwinsize(rows, columns)
        time.sleep(1.0)
        check(f"alive at {columns}x{rows}", process.isalive())
    process.write("\x11")
    deadline = time.monotonic() + 15
    while process.isalive() and time.monotonic() < deadline:
        time.sleep(0.2)
    alive = process.isalive()
    if alive:
        process.terminate(force=True)
    check("quits with exit code 0", not alive and process.exitstatus == 0)
    new = sorted(set(data.glob("logs/session_*.log")) - before)
    check("a session log was written", bool(new))
    if new:
        print("--- session log")
        for line in new[-1].read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
            print(line[:170])
    check("no crash log", not list(data.glob("logs/crash_*.log")))
    print("FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
