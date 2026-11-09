"""Where the app keeps its data. Portable first, then the user's profile."""

from __future__ import annotations

import itertools
import ctypes
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PORTABLE_FOLDER = "WingetDeck-data"
PROFILE_FOLDER = "WingetDeck"

_SUBFOLDERS = ("logs", "state", "snapshots")

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


def _is_redirected(path: Path) -> bool:
    """True for a junction or symbolic link, which could point the app's files somewhere else."""
    try:
        attributes = os.lstat(path).st_file_attributes
    except OSError:
        return False
    return bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def resolve_data_dir(exe_dir: Path, local_appdata: Path, elevated: bool = False) -> DataDir:
    """Use the folder beside the exe, unless that is unsafe or impossible.

    An elevated run never trusts it: another user could have written settings or a queue there
    that would then drive installers as administrator. Links are refused for the same reason.
    """
    portable_root = exe_dir / PORTABLE_FOLDER
    if (
        not elevated
        and not any(_is_redirected(p) for p in (exe_dir, portable_root))
        and not any(_is_redirected(portable_root / n) for n in _SUBFOLDERS)
        and _is_writable(exe_dir)
        and _is_writable(portable_root)
    ):
        return DataDir(portable_root, portable=True)
    return DataDir(local_appdata / PROFILE_FOLDER, portable=False)


def app_data_dir() -> DataDir:
    """The data folder for this run: beside the exe, or beside the project when run from source."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
    else:
        exe_dir = Path(__file__).resolve().parents[2]
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return resolve_data_dir(exe_dir, local, elevated=is_elevated())


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False
