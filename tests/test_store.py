import json
import os
import subprocess
import sys
import time

import pytest

from wingetdeck.core.logs import SessionLog
from wingetdeck.core.store import (
    AlreadyRunning,
    HistoryEntry,
    QueueItem,
    QueueSnapshot,
    Settings,
    SingleInstance,
    Store,
)
from wingetdeck.winget.backend import UpgradeOptions


@pytest.fixture
def store(tmp_data):
    return Store(tmp_data, SessionLog(tmp_data, False, {}))


def snap():
    return QueueSnapshot(
        items=[QueueItem("Git", "Git.Git", "1.0", "1.1", "winget", "waiting")], direct_downloader=False
    )


def test_settings_round_trip(store):
    s = Settings(theme="x", consented_agreements=True, ignored={"A.B"})
    s.defaults = UpgradeOptions(force=True)
    s.per_package["Git.Git"] = UpgradeOptions(silent=False, scope="user")
    store.save_settings(s)
    loaded = store.load_settings()
    assert loaded.theme == "x" and loaded.ignored == {"A.B"} and loaded.defaults.force
    assert loaded.per_package["Git.Git"].scope == "user" and loaded.stall_minutes == 10


def test_missing_settings_gives_defaults(store):
    assert store.load_settings() == Settings()


def test_writes_are_atomic(store, monkeypatch):
    store.save_settings(Settings(theme="good"))

    def boom(*a):
        raise OSError("power cut")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.save_settings(Settings(theme="bad"))
    monkeypatch.undo()
    assert store.load_settings().theme == "good"


def test_queue_round_trip(store):
    store.save_queue(snap())
    assert store.load_queue() == snap()
    store.clear_queue()
    assert store.load_queue() is None


def test_clear_queue_keeps_a_dated_copy(store):
    store.save_queue(snap())
    store.clear_queue(keep_copy=True)
    assert list(store.queue_path.parent.glob("queue_declined_*.json"))


def test_corrupt_queue_kept_and_reported(store):
    store.queue_path.write_text("{not json", encoding="utf-8")
    assert store.load_queue() is None
    assert list(store.queue_path.parent.glob("queue_corrupt_*.json")) and store.corruption_notes


def test_queue_with_wrong_shape_is_corrupt(store):
    store.queue_path.write_text('{"items": 3}', encoding="utf-8")
    assert store.load_queue() is None and store.corruption_notes


@pytest.mark.parametrize("bad", ["", "--override=x", "-s"])
def test_queue_with_unsafe_package_id_is_refused(store, bad):
    store.queue_path.write_text(json.dumps({
        "direct_downloader": False,
        "items": [{"name": "x", "id": bad, "installed": "1", "available": "2", "source": "winget", "state": "waiting"}],
    }), encoding="utf-8")
    assert store.load_queue() is None and store.corruption_notes


def test_corrupt_settings_gives_defaults(store):
    store.settings_path.write_text("nope", encoding="utf-8")
    assert store.load_settings() == Settings() and store.corruption_notes
    assert list(store.settings_path.parent.glob("settings_corrupt_*.json"))


def test_settings_with_wrong_types_gives_defaults(store):
    store.settings_path.write_text('{"ignored": 5, "defaults": "x"}', encoding="utf-8")
    assert store.load_settings() == Settings() and store.corruption_notes


def test_history_round_trip(store):
    e = HistoryEntry("2026-11-09", "Git.Git", "Git", "1", "2", "success", "0x00000000", "x.log")
    store.append_history(e)
    assert store.history() == [e]


def test_truncated_history_keeps_good_lines(store):
    e = HistoryEntry("2026-11-09", "Git.Git", "Git", "1", "2", "success", "0x00000000", "x.log")
    store.append_history(e)
    with store.history_path.open("a", encoding="utf-8") as f:
        f.write('{"when": "half')
    assert store.history() == [e] and store.corruption_notes


def test_second_instance_refused(tmp_data):
    with SingleInstance(tmp_data):
        with pytest.raises(AlreadyRunning):
            with SingleInstance(tmp_data):
                pass


def test_lock_free_after_normal_exit(tmp_data):
    with SingleInstance(tmp_data):
        pass
    with SingleInstance(tmp_data):
        pass


def test_lock_released_after_crash(tmp_data):
    code = (
        "import sys,time;from pathlib import Path;"
        "from wingetdeck.paths import DataDir;from wingetdeck.core.store import SingleInstance;"
        f"s=SingleInstance(DataDir(Path(r'{tmp_data.root}'),True));s.__enter__();print('held',flush=True);time.sleep(60)"
    )
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert child.stdout.readline().strip() == "held"
    with pytest.raises(AlreadyRunning):
        with SingleInstance(tmp_data):
            pass
    child.kill()
    child.wait()
    time.sleep(0.1)
    with SingleInstance(tmp_data):
        pass
