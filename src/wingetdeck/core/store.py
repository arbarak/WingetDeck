"""Everything saved between runs. A damaged file never stops the app: it is kept under a dated
name, reported, and replaced by defaults. Package ids read back are validated before use."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from ..paths import DataDir, stamp
from ..winget.backend import UpgradeOptions
from .logs import SessionLog

_ERROR_ALREADY_EXISTS = 183


@dataclass
class Settings:
    defaults: UpgradeOptions = field(default_factory=UpgradeOptions)
    theme: str = "wingetdeck-green"
    consented_agreements: bool = False
    asked_agreements: bool = False
    offered_direct_downloader: bool = False
    ignored: set[str] = field(default_factory=set)
    per_package: dict[str, UpgradeOptions] = field(default_factory=dict)
    auto_check_minutes: int | None = None
    stall_minutes: int = 10
    moved_downloader: dict | None = None
    create_restore_point: bool = False
    language: str = ""  # empty follows Windows


@dataclass(frozen=True)
class QueueItem:
    name: str
    id: str
    installed: str
    available: str
    source: str | None
    state: str


@dataclass(frozen=True)
class QueueSnapshot:
    items: list[QueueItem]
    direct_downloader: bool


@dataclass(frozen=True)
class HistoryEntry:
    when: str
    id: str
    name: str
    from_version: str
    to_version: str
    outcome: str
    code: str
    log_path: str


def is_safe_package_id(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not value.startswith("-")


def _options_from(data: dict) -> UpgradeOptions:
    known = {f.name for f in fields(UpgradeOptions)}
    if not isinstance(data, dict):
        raise TypeError("options must be an object")
    return UpgradeOptions(**{k: v for k, v in data.items() if k in known})


def _settings_to_json(s: Settings) -> dict:
    data = asdict(s)
    data["ignored"] = sorted(s.ignored)
    return data


def _settings_from_json(data: dict) -> Settings:
    if not isinstance(data, dict):
        raise TypeError("settings must be an object")
    s = Settings()
    if "defaults" in data:
        s.defaults = _options_from(data["defaults"])
    if "per_package" in data:
        if not isinstance(data["per_package"], dict):
            raise TypeError("per_package must be an object")
        s.per_package = {k: _options_from(v) for k, v in data["per_package"].items()}
    if "ignored" in data:
        if not isinstance(data["ignored"], list):
            raise TypeError("ignored must be a list")
        s.ignored = set(data["ignored"])
    expected = {
        "theme": str,
        "consented_agreements": bool,
        "asked_agreements": bool,
        "offered_direct_downloader": bool,
        "stall_minutes": int,
        "create_restore_point": bool,
        "language": str,
    }
    for key, kind in expected.items():
        if key in data:
            if not isinstance(data[key], kind):
                raise TypeError(f"{key} has the wrong type")
            setattr(s, key, data[key])
    for key, kind in (("auto_check_minutes", int), ("moved_downloader", dict)):
        value = data.get(key)
        if value is not None and not isinstance(value, kind):
            raise TypeError(f"{key} has the wrong type")
        setattr(s, key, value)
    return s


class Store:
    def __init__(self, data_dir: DataDir, log: SessionLog) -> None:
        self.data_dir = data_dir
        self.log = log
        self.settings_path = data_dir.state / "settings.json"
        self.queue_path = data_dir.state / "queue.json"
        self.history_path = data_dir.state / "history.jsonl"
        self.corruption_notes: list[str] = []

    def _write_atomic(self, path: Path, text: str) -> None:
        temp = path.with_name(f"{path.name}.{stamp()}.tmp")
        temp.write_text(text, encoding="utf-8")
        try:
            os.replace(temp, path)
        except OSError:
            temp.unlink(missing_ok=True)
            raise

    def _quarantine(self, path: Path, kind: str, reason: object) -> None:
        keep = path.with_name(f"{kind}_corrupt_{stamp()}{path.suffix}")
        os.replace(path, keep)
        note = f"{path.name} could not be read and was kept as {keep.name}"
        self.corruption_notes.append(note)
        self.log.warn(note, reason=str(reason))

    def load_settings(self) -> Settings:
        if not self.settings_path.exists():
            return Settings()
        try:
            return _settings_from_json(json.loads(self.settings_path.read_text(encoding="utf-8")))
        except (ValueError, TypeError, OSError) as e:
            self._quarantine(self.settings_path, "settings", e)
            return Settings()

    def save_settings(self, settings: Settings) -> None:
        self._write_atomic(self.settings_path, json.dumps(_settings_to_json(settings), indent=1))

    def save_queue(self, snapshot: QueueSnapshot) -> None:
        self._write_atomic(self.queue_path, json.dumps(asdict(snapshot), indent=1))

    def load_queue(self) -> QueueSnapshot | None:
        if not self.queue_path.exists():
            return None
        try:
            data = json.loads(self.queue_path.read_text(encoding="utf-8"))
            items = [QueueItem(**row) for row in data["items"]]
            if not all(is_safe_package_id(i.id) for i in items):
                raise ValueError("unsafe package id")
            return QueueSnapshot(items=items, direct_downloader=bool(data.get("direct_downloader")))
        except (ValueError, TypeError, KeyError, OSError) as e:
            self._quarantine(self.queue_path, "queue", e)
            return None

    def clear_queue(self, keep_copy: bool = False) -> None:
        if not self.queue_path.exists():
            return
        if keep_copy:
            os.replace(self.queue_path, self.queue_path.with_name(f"queue_declined_{stamp()}.json"))
        else:
            self.queue_path.unlink()

    def append_history(self, entry: HistoryEntry) -> None:
        with self.history_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

    def history(self) -> list[HistoryEntry]:
        if not self.history_path.exists():
            return []
        entries = []
        bad = 0
        for line in self.history_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                entries.append(HistoryEntry(**json.loads(line)))
            except (ValueError, TypeError):
                bad += 1
        if bad:
            note = f"{bad} damaged line(s) in {self.history_path.name} were skipped"
            self.corruption_notes.append(note)
            self.log.warn(note)
        return entries


class AlreadyRunning(Exception):
    pass


class SingleInstance:
    """Only one copy per data folder. Windows drops the lock itself if the app crashes."""

    def __init__(self, data_dir: DataDir) -> None:
        digest = hashlib.sha256(str(data_dir.root).lower().encode("utf-8")).hexdigest()[:24]
        self._name = f"Local\\WingetDeck_{digest}"
        self._handle = None
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateMutexW.restype = ctypes.c_void_p
        self._kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    def __enter__(self) -> SingleInstance:
        ctypes.set_last_error(0)
        handle = self._kernel32.CreateMutexW(None, 1, self._name)
        already = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
        if already:
            if handle:
                self._kernel32.CloseHandle(handle)
            raise AlreadyRunning(self._name)
        self._handle = handle
        return self

    def __exit__(self, *exc) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None
