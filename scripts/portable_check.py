"""Prove a built exe is portable, on this PC, with no window on the desktop.

    python scripts/portable_check.py path\\to\\WingetDeck-x64.exe WORK_FOLDER

Copies the exe to a path with spaces and non-English letters, runs it there with Python hidden from it,
and checks where its data goes, including when the exe's folder cannot be written to. WORK_FOLDER is
left in place so the results can be read.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from winpty import PtyProcess

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {name}{'  ' + detail if detail else ''}")
    if not ok:
        failures.append(name)


def clean_env(local_app_data: Path) -> dict[str, str]:
    """No Python on the path and no Python settings: what a PC without Python looks like to the exe."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("PYTHON", "VIRTUAL_ENV", "UV_"))}
    system = os.environ["SystemRoot"]
    env["PATH"] = f"{system}\\System32;{system}"
    env["LOCALAPPDATA"] = str(local_app_data)
    return env


def run_demo(exe: Path, env: dict[str, str]) -> bool:
    """Start the demo in a pseudo console, go to the table, quit. True if all of that worked."""
    env_block = {k: v for k, v in env.items()}
    process = PtyProcess.spawn([str(exe), "--demo"], dimensions=(36, 120), cwd=str(exe.parent), env=env_block)
    seen: list[str] = []

    def read() -> None:
        while True:
            try:
                seen.append(process.read(65536))
            except EOFError:
                return

    threading.Thread(target=read, daemon=True).start()

    def wait_for(text: str, seconds: float = 40.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if text in "".join(seen):
                return True
            time.sleep(0.1)
        return False

    ok = wait_for("Select a source")
    process.write("\r")
    ok = wait_for("UPGRADE", 15) and ok
    process.write("\x11")
    deadline = time.monotonic() + 15
    while process.isalive() and time.monotonic() < deadline:
        time.sleep(0.2)
    alive = process.isalive()
    if alive:
        process.terminate(force=True)
    return ok and not alive and process.exitstatus == 0


def main() -> int:
    source, work = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
    work.mkdir(parents=True, exist_ok=True)
    profile = work / "profile"
    env = clean_env(profile)

    folder = work / "Program Tést — été"
    folder.mkdir(exist_ok=True)
    exe = folder / source.name
    shutil.copy2(source, exe)
    shown = subprocess.run([str(exe), "--version"], env=env, capture_output=True, text=True, timeout=120)
    check("--version exits 0 from an odd path with no Python", shown.returncode == 0, shown.stdout.strip())
    check("demo runs through to the table", run_demo(exe, env))
    check("WingetDeck-data appears beside the exe", (folder / "WingetDeck-data" / "demo" / "logs").is_dir())
    check("the profile folder is left alone", not (profile / "WingetDeck").exists())

    locked = work / "locked"
    locked.mkdir(exist_ok=True)
    exe2 = locked / source.name
    shutil.copy2(source, exe2)
    user = os.environ["USERNAME"]
    subprocess.run(["icacls", str(locked), "/deny", f"{user}:(OI)(CI)(WD,AD)"], check=True, capture_output=True)
    try:
        check("demo runs from a folder it cannot write to", run_demo(exe2, env))
        check("data falls back to the profile folder", (profile / "WingetDeck" / "demo" / "logs").is_dir())
        check("nothing was written beside that exe", not (locked / "WingetDeck-data").exists())
    finally:
        subprocess.run(["icacls", str(locked), "/remove:d", user], check=True, capture_output=True)
    print("FAILED" if failures else "PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
