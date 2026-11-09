"""Helpers shared by the Sandbox experiments."""

import ctypes
import json
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import psutil
from winpty import PtyProcess

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
SIZES = re.compile(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB)\s*/\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB)")
ntdll = ctypes.WinDLL("ntdll")
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.OpenProcess.restype = ctypes.c_void_p
ntdll.NtSuspendProcess.argtypes = [ctypes.c_void_p]
ntdll.NtResumeProcess.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
WINGET = shutil.which("winget")


def rx_mb() -> float:
    return psutil.net_io_counters().bytes_recv / 1e6


def rates(seconds: int) -> list[float]:
    values = []
    for _ in range(seconds):
        start = rx_mb()
        time.sleep(1)
        values.append(round(rx_mb() - start, 2))
    return values


def suspend(pid: int, resume: bool = False) -> int:
    handle = kernel32.OpenProcess(0x0800, False, pid)
    status = (ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess)(handle)
    kernel32.CloseHandle(handle)
    return status


def set_downloader(value: str | None) -> None:
    path = Path.home() / "AppData/Local/Packages/Microsoft.DesktopAppInstaller_8wekyb3d8bbwe/LocalState/settings.json"
    if value is None:
        path.unlink(missing_ok=True)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"network": {"downloader": value}}), encoding="utf-8")


class Run:
    """A winget command in a pseudo console, keeping everything it prints."""

    def __init__(self, *args: str, raw_path: Path | None = None) -> None:
        self.proc = PtyProcess.spawn([WINGET, *args], dimensions=(30, 200))
        self.pid = self.proc.pid
        self.raw: list[str] = []
        self.sizes: list[str] = []
        self.raw_path = raw_path
        self.children: set[str] = set()
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._watch, daemon=True).start()

    def _read(self) -> None:
        while True:
            try:
                chunk = self.proc.read(4096)
            except Exception:
                return
            self.raw.append(chunk)
            for match in SIZES.finditer(ANSI.sub("", "".join(self.raw[-200:]))):
                if not self.sizes or self.sizes[-1] != match.group(0):
                    self.sizes.append(match.group(0))

    def _watch(self) -> None:
        while self.proc.isalive():
            try:
                for child in psutil.Process(self.pid).children(recursive=True):
                    self.children.add(child.name())
            except psutil.Error:
                pass
            time.sleep(0.2)

    def wait_for_progress(self, timeout: float = 120) -> bool:
        start = time.time()
        while not self.sizes and self.proc.isalive() and time.time() - start < timeout:
            time.sleep(0.02)
        return bool(self.sizes)

    def wait(self, timeout: float = 300) -> int | None:
        start = time.time()
        while self.proc.isalive() and time.time() - start < timeout:
            time.sleep(0.2)
        time.sleep(0.3)
        if self.raw_path:
            self.raw_path.write_text("".join(self.raw), encoding="utf-8", newline="")
        return self.proc.exitstatus if not self.proc.isalive() else None

    def kill(self) -> str:
        done = subprocess.run(["taskkill", "/PID", str(self.pid), "/T", "/F"], capture_output=True, text=True)
        return (done.stdout + done.stderr).strip()[:160]

    def clean(self) -> str:
        return ANSI.sub("", "".join(self.raw))


def temp_files() -> dict[str, int]:
    root = Path.home() / "AppData/Local/Temp/WinGet"
    if not root.exists():
        return {}
    return {f.name: f.stat().st_size for f in root.rglob("*") if f.is_file() and "cache" not in f.parts}


def save(out: str, name: str, data: object) -> None:
    Path(out, name).write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
