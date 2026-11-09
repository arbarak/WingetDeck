"""Findings from the whole-project review, each with the test that reproduced it."""

import json

from wingetdeck.core.logs import SessionLog
from wingetdeck.core.queue import ItemState, RunState
from wingetdeck.core.runner import Runner
from wingetdeck.core.store import Store
from wingetdeck.winget import proc
from wingetdeck.winget.backend import StageEvent, UpgradeOptions
from wingetdeck.winget.fake import FakeBackend
from wingetdeck.winget.models import ChangeKind, Package, Stage
from wingetdeck.winget.settings_file import enable_direct, read_downloader, undo
from wingetdeck.winget.stream import UpgradeStream


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


def stages(events):
    return [e.stage for e in events if isinstance(e, StageEvent)]


# A spawn failure of a type other than OSError


async def test_a_spawn_failure_of_any_type_fails_the_item_and_the_run_goes_on(tmp_data):
    class WinptyLikeError(Exception):
        pass

    class Broken(FakeBackend):
        def start_upgrade(self, package, options):
            raise WinptyLikeError("The handle is invalid")

    log = SessionLog(tmp_data, False, {})
    runner = Runner(Broken([]), Store(tmp_data, log), log, lambda view: None)
    await runner.start([pkg("A"), pkg("B")], lambda p: UpgradeOptions())
    await runner.wait()
    view = runner.view
    assert view.state is RunState.FINISHED
    assert [i.state for i in view.items] == [ItemState.FAILED, ItemState.FAILED]
    assert "handle is invalid" in view.items[0].message


async def test_a_winget_stream_that_breaks_fails_the_item_and_the_run_goes_on(tmp_data):
    class Handle:
        pid = 0

        def freeze(self):
            return False

        def thaw(self):
            pass

        def kill(self):
            return proc.KillResult(True)

        async def events(self):
            yield StageEvent(Stage.DOWNLOADING)
            raise RuntimeError("pseudo console went away")

    class Broken(FakeBackend):
        def start_upgrade(self, package, options):
            return Handle()

    log = SessionLog(tmp_data, False, {})
    runner = Runner(Broken([]), Store(tmp_data, log), log, lambda view: None)
    await runner.start([pkg("A")], lambda p: UpgradeOptions())
    await runner.wait()
    assert runner.view.state is RunState.FINISHED
    assert runner.view.items[0].state is ItemState.FAILED


# A reused process id


def test_a_process_older_than_its_listed_parent_is_not_its_child(monkeypatch):
    """Windows keeps a dead parent's id on its orphans and reuses ids. That orphan is not ours to kill."""
    rows = [(10, 1, "winget.exe"), (20, 10, "users-app.exe"), (30, 10, "setup.exe"), (40, 30, "msi.exe")]
    started = {10: 100, 20: 50, 30: 150, 40: 160}
    monkeypatch.setattr(proc, "_snapshot", lambda: rows)
    monkeypatch.setattr(proc, "_started_at", started.get, raising=False)
    assert proc.process_tree(10) == [10, 30, 40]


def test_a_child_with_an_unreadable_start_time_is_still_treated_as_a_child(monkeypatch):
    """An elevated installer may not tell us. Losing track of it would be the worse mistake."""
    rows = [(10, 1, "winget.exe"), (30, 10, "setup.exe")]
    monkeypatch.setattr(proc, "_snapshot", lambda: rows)
    monkeypatch.setattr(proc, "_started_at", {10: 100}.get, raising=False)
    assert proc.process_tree(10) == [10, 30]


def test_start_time_of_this_process_can_be_read():
    import os

    assert proc._started_at(os.getpid())


# Undo of the direct downloader


def test_undo_keeps_settings_changed_since_and_backs_up_first(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{\n  "visual": {"progressBar": "accent"}\n}\n', encoding="utf-8")
    backups = tmp_path / "backups"
    change = enable_direct(path, backups)
    edited = path.read_text(encoding="utf-8").replace('"accent"', '"rainbow"')
    path.write_text(edited, encoding="utf-8")
    undo(path, change)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["visual"]["progressBar"] == "rainbow", "the later edit survives"
    assert read_downloader(path) != "wininet"
    kept = [f.read_text(encoding="utf-8") for f in backups.iterdir()]
    assert edited in kept, "the file as it stood before Undo is kept"


def test_undo_keeps_later_settings_when_there_was_no_file_before(tmp_path):
    path = tmp_path / "settings.json"
    change = enable_direct(path, tmp_path / "backups")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["visual"] = {"progressBar": "rainbow"}
    path.write_text(json.dumps(data), encoding="utf-8")
    undo(path, change)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["visual"]["progressBar"] == "rainbow"
    assert read_downloader(path) != "wininet"


def test_enabling_does_not_add_carriage_returns_to_a_windows_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_bytes(b'{\r\n  "visual": {}\r\n}\r\n')
    enable_direct(path, tmp_path / "backups")
    assert b"\r\r" not in path.read_bytes()


def test_undo_with_nothing_changed_still_restores_the_exact_file(tmp_path):
    path = tmp_path / "settings.json"
    original = '// mine\n{ "visual": {} }\n'
    path.write_text(original, encoding="utf-8")
    change = enable_direct(path, tmp_path / "backups")
    undo(path, change)
    assert path.read_text(encoding="utf-8") == original


def test_undo_leaves_a_downloader_the_user_has_since_changed_alone(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}\n", encoding="utf-8")
    change = enable_direct(path, tmp_path / "backups")
    path.write_text('{"network": {"downloader": "do"}}\n', encoding="utf-8")
    undo(path, change)
    assert read_downloader(path) == "do"


# Agreement links printed before the download


AGREEMENTS = (
    "Found Thing [Vendor.Thing] Version 2.0\r\n"
    "Agreements for Thing [Vendor.Thing] Version 2.0\r\n"
    "License Terms: https://vendor.example/licence\r\n"
    "This application is licensed to you by its owner.\r\n"
    "Downloading https://vendor.example/thing.exe\r\n"
)


def test_an_agreement_link_does_not_cost_the_download_its_stage():
    stream = UpgradeStream()
    events = stream.feed(AGREEMENTS)
    assert stages(events)[-1] is Stage.DOWNLOADING


def test_the_same_in_another_language_where_only_the_link_shows_the_download():
    stream = UpgradeStream()
    events = stream.feed(
        "Gefunden Thing [Vendor.Thing]\r\n"
        "Lizenzbedingungen: https://vendor.example/licence\r\n"
        "Diese Anwendung wird Ihnen lizenziert.\r\n"
        "Herunterladen https://vendor.example/thing.exe\r\n"
    )
    assert stages(events)[-1] is Stage.DOWNLOADING


def test_a_link_after_a_real_download_does_not_go_back_to_downloading():
    stream = UpgradeStream()
    stream.feed("Downloading https://vendor.example/dependency.exe\r\n")
    stream.feed("\r  ██▉  10.0 MB / 20.0 MB")
    events = stream.feed("\r\nSome text\r\nDownloading https://vendor.example/second.exe\r\n")
    assert Stage.DOWNLOADING not in stages(events)


def test_a_link_after_the_install_began_does_not_go_back_to_downloading():
    stream = UpgradeStream()
    stream.feed(AGREEMENTS)
    stream.feed("Successfully verified installer hash\r\nStarting package install...\r\n")
    events = stream.feed("See https://vendor.example/help for help\r\n")
    assert Stage.DOWNLOADING not in stages(events)
