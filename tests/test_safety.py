import subprocess
from types import SimpleNamespace

import pytest

from wingetdeck.core.safety import (
    SnapshotFailed,
    create_restore_point,
    restart_as_admin,
    rollback_target,
    take_snapshot,
)
from wingetdeck.core.store import HistoryEntry
from wingetdeck.winget.fake import FakeBackend


def entry(from_version="1.0"):
    return HistoryEntry("2026-11-09T10:00:00", "A", "A", from_version, "2.0", "done", "0x00000000", "")


async def test_snapshot_writes_a_dated_file(tmp_data):
    first = await take_snapshot(FakeBackend([]), tmp_data)
    second = await take_snapshot(FakeBackend([]), tmp_data)
    assert first.parent == tmp_data.snapshots and first.name.startswith("winget_export_") and first.exists()
    assert first != second and first.exists(), "earlier snapshots stay"


async def test_snapshot_that_writes_nothing_counts_as_failed(tmp_data):
    class Silent(FakeBackend):
        async def export_snapshot(self, path):
            pass

    with pytest.raises(SnapshotFailed):
        await take_snapshot(Silent([]), tmp_data)


async def test_snapshot_error_counts_as_failed(tmp_data):
    class Broken(FakeBackend):
        async def export_snapshot(self, path):
            raise OSError("disk full")

    with pytest.raises(SnapshotFailed, match="disk full"):
        await take_snapshot(Broken([]), tmp_data)


def test_rollback_target_when_version_exists():
    assert rollback_target(entry(), ["2.0", "1.0", "0.9"]) == "1.0"


def test_rollback_none_when_version_gone():
    assert rollback_target(entry(), ["2.0", "1.5"]) is None


def test_rollback_none_when_earlier_version_unknown():
    assert rollback_target(entry("Unknown"), ["Unknown", "2.0"]) is None


def test_restore_point_refused_without_admin():
    calls = []
    result = create_restore_point("WingetDeck", run=lambda *a, **k: calls.append(a), is_admin=lambda: False)
    assert not result.ok and "administrator" in result.message.lower() and calls == []


def test_restore_point_success():
    seen = []

    def run(args, **kw):
        seen.append(args)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    assert create_restore_point("Before WingetDeck run", run=run, is_admin=lambda: True).ok
    assert seen[0][0].lower().startswith("powershell") and "Checkpoint-Computer" in " ".join(seen[0])


def test_restore_point_description_cannot_inject_commands():
    seen = []

    def run(args, **kw):
        seen.append(args)
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    create_restore_point("x'; Remove-Item C:\\ -Recurse; '", run=run, is_admin=lambda: True)
    command = seen[0][-1]
    assert ";" not in command and command.count("'") == 4, "the text cannot leave its quotes"


def test_restore_point_failure_gives_the_reason():
    run = lambda *a, **k: SimpleNamespace(returncode=1, stdout=b"", stderr=b"System Restore is off")
    result = create_restore_point("x", run=run, is_admin=lambda: True)
    assert not result.ok and "System Restore is off" in result.message


def test_restore_point_timeout_is_a_failure_not_a_crash():
    def run(*a, **k):
        raise subprocess.TimeoutExpired("powershell", 1)

    assert not create_restore_point("x", run=run, is_admin=lambda: True).ok


def test_restart_as_admin_uses_runas():
    calls = []

    def shell_execute(*args):
        calls.append(args)
        return 42

    assert restart_as_admin(shell_execute, executable="C:\\a b\\app.exe", arguments=["--debug", "x y"])
    assert calls[0][1] == "runas" and calls[0][2] == "C:\\a b\\app.exe" and '"x y"' in calls[0][3]


def test_restart_as_admin_declined_at_the_prompt_returns_false():
    assert not restart_as_admin(lambda *a: 5, executable="a.exe", arguments=[])
