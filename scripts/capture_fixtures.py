"""Save real winget output as test samples.

Read-only commands, plus one `winget download` in a pseudo console so the progress
bar is recorded with its raw escape codes. The downloaded installer is never run.

Usage: python scripts/capture_fixtures.py [package-id-to-download]
"""

import getpass
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from winpty import PtyProcess

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
WINGET = shutil.which("winget")
READ_ONLY = {
    "en_upgrade_include_unknown.txt": ["upgrade", "--include-unknown", "--disable-interactivity"],
    "en_upgrade.txt": ["upgrade", "--disable-interactivity"],
    "en_source_list.txt": ["source", "list", "--disable-interactivity"],
    "en_pin_list.txt": ["pin", "list", "--disable-interactivity"],
    "en_list_git.txt": ["list", "--id", "Git.Git", "--disable-interactivity"],
    "en_version.txt": ["--version"],
    "en_upgrade_help.txt": ["upgrade", "--help"],
    "en_show_git.txt": ["show", "--id", "Git.Git", "-e", "-s", "winget", "--disable-interactivity"],
}


def scrub(text: str) -> str:
    return text.replace(getpass.getuser(), "<user>")


def capture_read_only() -> None:
    for name, args in READ_ONLY.items():
        done = subprocess.run([WINGET, *args], capture_output=True, timeout=180)
        text = done.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
        (OUT / name).write_text(scrub(text), encoding="utf-8", newline="\n")
        print(name, len(text), "chars, exit", hex(done.returncode & 0xFFFFFFFF))


def capture_download(package: str) -> None:
    target = Path(tempfile.mkdtemp(prefix="wingetdeck-capture-"))
    args = ["download", "--id", package, "-e", "-s", "winget", "-d", str(target), "--disable-interactivity"]
    proc = PtyProcess.spawn([WINGET, *args], dimensions=(30, 200))
    chunks: list[str] = []

    def reader() -> None:
        while True:
            try:
                chunks.append(proc.read(4096))
            except Exception:
                return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout=300)
    name = "pty_download.txt"
    (OUT / name).write_text(scrub("".join(chunks)), encoding="utf-8", newline="")
    print(name, sum(map(len, chunks)), "chars, exit", proc.exitstatus)
    shutil.rmtree(target, ignore_errors=True)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    capture_read_only()
    capture_download(sys.argv[1] if len(sys.argv) > 1 else "wkhtmltopdf.wkhtmltox")
