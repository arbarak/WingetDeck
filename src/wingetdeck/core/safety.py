"""Ways back: a list of what was installed, an earlier version, a restore point."""

from __future__ import annotations

import ctypes
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..i18n import t
from ..paths import DataDir, is_elevated, stamp
from ..winget.backend import WingetBackend
from .store import HistoryEntry

_RESTORE_POINT_TIMEOUT = 300
_SHELL_EXECUTE_OK = 32
_NO_WINDOW = 0x08000000
_UNSAFE_DESCRIPTION = re.compile(r"[^\w .-]")


class SnapshotFailed(Exception):
    pass


async def take_snapshot(backend: WingetBackend, data_dir: DataDir) -> Path:
    """A dated list of installed versions, so there is a record of how things were."""
    path = data_dir.snapshots / f"winget_export_{stamp()}.json"
    try:
        await backend.export_snapshot(path)
    except Exception as e:
        raise SnapshotFailed(str(e)) from e
    if not path.exists() or path.stat().st_size == 0:
        raise SnapshotFailed("winget did not write the list of installed apps")
    return path


def rollback_target(entry: HistoryEntry, available_versions: list[str]) -> str | None:
    """The version to go back to, if the source still has it."""
    if entry.from_version in ("", "Unknown") or entry.from_version not in available_versions:
        return None
    return entry.from_version


@dataclass(frozen=True)
class RestoreResult:
    ok: bool
    message: str = ""


def create_restore_point(
    description: str,
    run: Callable = subprocess.run,
    is_admin: Callable[[], bool] = is_elevated,
) -> RestoreResult:
    if not is_admin():
        return RestoreResult(False, t("A restore point needs administrator rights."))
    safe = _UNSAFE_DESCRIPTION.sub("", description)[:60] or "WingetDeck"
    command = f"Checkpoint-Computer -Description '{safe}' -RestorePointType 'MODIFY_SETTINGS' -ErrorAction Stop"
    try:
        done = run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            timeout=_RESTORE_POINT_TIMEOUT,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return RestoreResult(False, t("Could not create a restore point: {reason}", reason=e))
    if done.returncode != 0:
        reason = done.stderr.decode("utf-8", errors="replace").strip()
        return RestoreResult(False, t("Could not create a restore point: {reason}", reason=reason))
    return RestoreResult(True)


def _shell_execute(*args) -> int:
    return ctypes.windll.shell32.ShellExecuteW(*args)


def restart_as_admin(
    shell_execute: Callable = _shell_execute,
    executable: str | None = None,
    arguments: list[str] | None = None,
) -> bool:
    """Starts a new elevated copy. False means it did not start, such as No at the Windows prompt."""
    if executable is None:
        executable = sys.executable
        arguments = sys.argv[1:] if getattr(sys, "frozen", False) else ["-m", "wingetdeck.cli", *sys.argv[1:]]
    command_line = subprocess.list2cmdline(arguments or [])
    return shell_execute(None, "runas", executable, command_line, None, 1) > _SHELL_EXECUTE_OK
