"""Where the app keeps its data. Portable first, then the user's profile."""

from __future__ import annotations

import itertools
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PORTABLE_FOLDER = "WingetDeck-data"
PROFILE_FOLDER = "WingetDeck"

_counter = itertools.count()


def stamp() -> str:
    """A sortable, file-safe time stamp that never repeats within a process."""
    now = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{now}_{next(_counter):04d}"


def _is_writable(folder: Path) -> bool:
    # os.access is unreliable on Windows, so really try it.
    try:
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=folder):
            pass
    except OSError:
        return False
    return True


@dataclass(frozen=True)
class DataDir:
    root: Path
    portable: bool

    def _sub(self, name: str) -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def logs(self) -> Path:
        return self._sub("logs")

    @property
    def state(self) -> Path:
        return self._sub("state")

    @property
    def snapshots(self) -> Path:
        return self._sub("snapshots")


def resolve_data_dir(exe_dir: Path, local_appdata: Path) -> DataDir:
    portable_root = exe_dir / PORTABLE_FOLDER
    if _is_writable(exe_dir) and _is_writable(portable_root):
        return DataDir(portable_root, portable=True)
    return DataDir(local_appdata / PROFILE_FOLDER, portable=False)


def app_data_dir() -> DataDir:
    """The data folder for this run: beside the exe, or beside the project when run from source."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parents[2]
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return resolve_data_dir(exe_dir, local)
