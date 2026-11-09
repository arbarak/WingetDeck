"""Diagnostic logs: dated files that are never overwritten and never deleted automatically."""

from __future__ import annotations

import json
import re
import traceback
import zipfile
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from ..paths import DataDir, stamp

_KEEP_IN_MEMORY = 2000
_CRASH_EVENTS = 200
_WINGET_LOGS_IN_REPORT = 5
_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")


@dataclass(frozen=True)
class LogEvent:
    time: str
    level: str
    message: str
    package: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)

    def text(self) -> str:
        pkg = f" [{self.package}]" if self.package else ""
        extra = "".join(f" {k}={v}" for k, v in self.fields.items())
        return f"{self.time} {self.level:<5}{pkg} {self.message}{extra}"


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "package"


class SessionLog:
    def __init__(self, data_dir: DataDir, debug: bool, header: dict[str, str]) -> None:
        self.data_dir = data_dir
        self.debug_enabled = debug
        self.session = stamp()
        self.text_path = data_dir.logs / f"session_{self.session}.log"
        self.json_path = data_dir.logs / f"session_{self.session}.jsonl"
        self._recent: deque[LogEvent] = deque(maxlen=_KEEP_IN_MEMORY)
        self.paths: list[Path] = [self.text_path, self.json_path]
        self._text = self.text_path.open("x", encoding="utf-8", buffering=1)
        self._json = self.json_path.open("x", encoding="utf-8", buffering=1)
        self._text.write("WingetDeck session " + self.session + "\n")
        for key, value in header.items():
            self._text.write(f"{key}={value}\n")
        self._text.write("-" * 60 + "\n")
        self._json.write(json.dumps({"session": self.session, "header": header}) + "\n")

    def _write(self, level: str, msg: str, package: str | None, fields: dict[str, Any]) -> None:
        event = LogEvent(datetime.now().strftime("%H:%M:%S.%f")[:-3], level, msg, package, fields)
        self._recent.append(event)
        self._text.write(event.text() + "\n")
        row = {"time": event.time, "level": level, "message": msg, "package": package, **fields}
        self._json.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")

    def debug(self, msg: str, package: str | None = None, **fields: Any) -> None:
        if self.debug_enabled:
            self._write("DEBUG", msg, package, fields)

    def info(self, msg: str, package: str | None = None, **fields: Any) -> None:
        self._write("INFO", msg, package, fields)

    def warn(self, msg: str, package: str | None = None, **fields: Any) -> None:
        self._write("WARN", msg, package, fields)

    def error(self, msg: str, package: str | None = None, **fields: Any) -> None:
        self._write("ERROR", msg, package, fields)

    def events(self, level: str | None = None, package: str | None = None) -> list[LogEvent]:
        return [
            e
            for e in self._recent
            if (level is None or e.level == level) and (package is None or e.package == package)
        ]

    def package_transcript(self, package_id: str) -> TextIO:
        path = self.data_dir.logs / f"winget_{stamp()}_{_safe_name(package_id)}.log"
        self.paths.append(path)
        self.info("Transcript started", package=package_id, file=path.name)
        return path.open("x", encoding="utf-8", buffering=1, errors="replace", newline="")

    def transcript_for(self, package_id: str) -> Path | None:
        """The newest transcript for a package in this session."""
        wanted = f"_{_safe_name(package_id)}.log"
        for path in reversed(self.paths):
            if path.name.startswith("winget_") and path.name.endswith(wanted):
                return path
        return None

    def write_crash(self, exc: BaseException) -> Path:
        path = self.data_dir.logs / f"crash_{stamp()}.log"
        self.paths.append(path)
        lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        recent = list(self._recent)[-_CRASH_EVENTS:]
        with path.open("x", encoding="utf-8") as f:
            f.write("".join(lines))
            f.write("\nLast events:\n")
            f.writelines(e.text() + "\n" for e in recent)
        self.error("Crash", file=path.name, error=repr(exc))
        return path

    def total_size_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.data_dir.logs.rglob("*") if p.is_file())


_SECRETS = [
    (re.compile(r"(--header\s+)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1<removed>"),
    (re.compile(r"(--(?:custom|override)\s+)(\"[^\"]*\"|'[^']*'|\S+)"), r"\1<removed>"),
    (re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@"), r"\1<removed>@"),
]


def redact(text: str, username: str) -> str:
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    if username:
        text = re.sub(re.escape(username), "<user>", text, flags=re.IGNORECASE)
    return text


def report_contents(log: SessionLog, winget_log_dir: Path | None) -> list[str]:
    """What a diagnostic report will include, in words, to show before saving."""
    items = ["winget_info.txt: winget version and folders"]
    items += [f"{p.name}: this session" for p in log.paths if p.exists()]
    newest = _newest_winget_logs(winget_log_dir)
    if newest:
        items.append(f"{len(newest)} newest winget logs")
    return items


def _newest_winget_logs(folder: Path | None) -> list[Path]:
    if folder is None or not folder.is_dir():
        return []
    logs = [p for p in folder.iterdir() if p.is_file()]
    logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return logs[:_WINGET_LOGS_IN_REPORT]


def save_diagnostic_report(
    log: SessionLog, winget_info: str, winget_log_dir: Path | None, username: str
) -> Path:
    path = log.data_dir.logs / f"diagnostic_{stamp()}.zip"

    def add(zf: zipfile.ZipFile, name: str, source: Path) -> None:
        try:
            text = source.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            text = f"could not read: {e}"
        zf.writestr(name, redact(text, username))

    with zipfile.ZipFile(path, "x", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("winget_info.txt", redact(winget_info, username))
        for source in log.paths:
            if source.exists():
                add(zf, source.name, source)
        for source in _newest_winget_logs(winget_log_dir):
            add(zf, f"winget_logs/{source.name}", source)
    log.info("Diagnostic report saved", file=path.name)
    return path
