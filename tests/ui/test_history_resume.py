import asyncio
from dataclasses import replace

from textual.widgets import Button

from wingetdeck.core.queue import ItemState, RunState
from wingetdeck.core.store import HistoryEntry, QueueItem, QueueSnapshot
from wingetdeck.ui import app as app_module
from wingetdeck.ui.screens import settings as settings_module
from wingetdeck.ui.screens.dialogs import ConfirmDialog
from wingetdeck.ui.screens.history import HistoryScreen
from wingetdeck.ui.screens.logs import TranscriptScreen
from wingetdeck.ui.screens.progress import ProgressScreen
from wingetdeck.ui.screens.splash import SplashScreen
from wingetdeck.winget.fake import FakeBackend
from wingetdeck.winget.models import ChangeKind, Package, Stage

WIDE = (130, 100)


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


def plain(widget):
    return str(widget.render())


def asked(app):
    app.store.save_settings(replace(app.store.load_settings(), asked_agreements=True))


def queue_of(*ids, direct=False):
    return QueueSnapshot([QueueItem(i, i, "1.0", "1.1", "winget", "waiting") for i in ids], direct)


def history_row(app, package="A", from_version="1.0", log_path=""):
    app.store.append_history(
        HistoryEntry("2026-11-09T10:00:00", package, package, from_version, "2.0", "done", "0x00000000", log_path)
    )


async def until(check, seconds=8.0):
    async def poll():
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), seconds)


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def test_snapshot_written_before_first_package_with_dated_name(make_app):
    backend = FakeBackend([], speed=200)
    app = make_app(backend)
    asked(app)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        assert backend.calls[:2] == ["export_snapshot", "upgrade:A"]
        assert list(app.log_file.data_dir.snapshots.glob("winget_export_*.json"))


async def test_snapshot_failure_warns_and_asks_does_not_silently_continue(make_app):
    class Broken(FakeBackend):
        async def export_snapshot(self, path):
            raise OSError("disk full")

    backend = Broken([], speed=200)
    app = make_app(backend)
    asked(app)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await until(lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.pause()
        assert "disk full" in plain(app.screen.query_one("#dialog-text"))
        assert backend.calls == []
        await pilot.click("#cancel")
        await settle(app, pilot)
        assert backend.calls == [], "Cancel means nothing starts"
        app.start_upgrade([pkg("A")])
        await until(lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.pause()
        await pilot.click("#choice-0")
        await until(lambda: "upgrade:A" in backend.calls)
        await app.runner.shutdown()


async def test_restore_point_made_when_turned_on_and_admin(make_app, monkeypatch):
    made = []

    class Result:
        ok = True
        message = ""

    monkeypatch.setattr(app_module, "is_elevated", lambda: True)
    monkeypatch.setattr(app_module, "create_restore_point", lambda d: made.append(d) or Result())
    app = make_app(FakeBackend([], speed=200))
    app.store.save_settings(
        replace(app.store.load_settings(), asked_agreements=True, create_restore_point=True)
    )
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        assert made


async def test_no_restore_point_when_not_admin(make_app, monkeypatch):
    made = []
    monkeypatch.setattr(app_module, "is_elevated", lambda: False)
    monkeypatch.setattr(app_module, "create_restore_point", lambda d: made.append(d))
    app = make_app(FakeBackend([], speed=200))
    app.store.save_settings(
        replace(app.store.load_settings(), asked_agreements=True, create_restore_point=True)
    )
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        assert made == []


async def test_failed_restore_point_is_said_and_the_run_goes_on(make_app, monkeypatch):
    class Result:
        ok = False
        message = "System Restore is off"

    monkeypatch.setattr(app_module, "is_elevated", lambda: True)
    monkeypatch.setattr(app_module, "create_restore_point", lambda d: Result())
    app = make_app(FakeBackend([], speed=200))
    app.store.save_settings(
        replace(app.store.load_settings(), asked_agreements=True, create_restore_point=True)
    )
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        assert any("System Restore is off" in str(e.fields) for e in app.log_file.events("WARN"))


async def test_history_lists_entries(make_app):
    app = make_app()
    history_row(app, "Git.Git")
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        assert isinstance(app.screen, HistoryScreen) and [e.id for e in app.screen.entries] == ["Git.Git"]


async def test_empty_history_says_so(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        assert "no upgrades" in plain(app.screen.query_one("#history-note")).lower()
        assert app.screen.query_one("#rollback", Button).disabled


async def test_rollback_button_says_plainly_when_unavailable(make_app):
    backend = FakeBackend([], speed=200)
    backend.old_versions["A"] = ["2.0"]
    app = make_app(backend)
    history_row(app)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        await pilot.click("#rollback")
        await settle(app, pilot)
        text = plain(app.screen.query_one("#history-note"))
        assert "1.0" in text and "no longer" in text
        assert backend.calls == []


async def test_rollback_asks_then_installs_the_earlier_version(make_app):
    backend = FakeBackend([], speed=200)
    backend.old_versions["A"] = ["2.0", "1.0"]
    app = make_app(backend)
    history_row(app)
    asked(app)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        await pilot.click("#rollback")
        await settle(app, pilot)
        assert isinstance(app.screen, ConfirmDialog) and "1.0" in plain(app.screen.query_one("#dialog-text"))
        assert not any(c.startswith("install") for c in backend.calls)
        await pilot.click("#choice-0")
        await until(lambda: "install:A:1.0" in backend.calls)
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        await pilot.pause()
        assert isinstance(app.screen, ProgressScreen)
        assert app.runner.view.items[0].state is ItemState.DONE


async def test_rollback_refused_during_a_run(make_app):
    backend = FakeBackend([], speed=2)
    backend.old_versions["A"] = ["1.0"]
    app = make_app(backend)
    history_row(app)
    asked(app)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("B")])
        await until(lambda: app.runner.view.stage is Stage.DOWNLOADING)
        await pilot.press("h")
        await pilot.pause()
        assert app.screen.query_one("#rollback", Button).disabled
        await app.runner.shutdown()


async def test_history_see_log_opens_the_saved_file(make_app, tmp_path):
    saved = tmp_path / "winget_old.log"
    saved.write_text("from an earlier session", encoding="utf-8")
    app = make_app()
    history_row(app, log_path=str(saved))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("h")
        await pilot.pause()
        await pilot.click("#see-log")
        await pilot.pause()
        assert isinstance(app.screen, TranscriptScreen)
        assert "from an earlier session" in "\n".join(s.text for s in app.screen.query_one("#transcript").lines)


async def test_launch_with_saved_queue_offers_resume_with_count(make_app):
    backend = FakeBackend([], speed=200)
    app = make_app(backend)
    asked(app)
    app.store.save_queue(queue_of("A", "B", "C"))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert isinstance(app.screen, ConfirmDialog)
        assert "3 left" in app.screen.dialog_title
        await pilot.click("#choice-0")
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        assert [c for c in backend.calls if c.startswith("upgrade")] == ["upgrade:A", "upgrade:B", "upgrade:C"]


async def test_declining_resume_clears_queue_but_keeps_copy(make_app):
    app = make_app()
    app.store.save_queue(queue_of("A"))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.click("#choice-1")
        await pilot.pause()
        assert app.store.load_queue() is None
        assert list(app.log_file.data_dir.state.glob("queue_declined_*"))
        assert isinstance(app.screen, SplashScreen)


async def test_later_keeps_the_queue_for_next_time(make_app):
    app = make_app()
    app.store.save_queue(queue_of("A"))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.click("#cancel")
        await pilot.pause()
        assert app.store.load_queue() is not None


async def test_resume_uses_todays_downloader_not_the_saved_one(make_app):
    """The setting may have been undone since the queue was saved, and a stale yes would freeze a
    download that freezing cannot stop."""
    backend = FakeBackend([], speed=2, direct_downloader=False)
    app = make_app(backend)
    asked(app)
    app.store.save_queue(queue_of("A", direct=True))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.click("#choice-0")
        await until(lambda: app.runner.view.stage is Stage.DOWNLOADING)
        assert not app.runner.view.direct_downloader
        await app.runner.shutdown()


async def test_no_resume_question_with_no_saved_queue(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert isinstance(app.screen, SplashScreen)


async def test_restart_as_admin_button_uses_runas(make_app, monkeypatch):
    calls = []
    monkeypatch.setattr(settings_module, "restart_as_admin", lambda: calls.append(1) or True)
    monkeypatch.setattr(settings_module, "is_elevated", lambda: False)
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.click("#restart-admin")
        await pilot.pause()
        assert calls == [1]
    assert app.return_code == 0


async def test_restart_as_admin_declined_stays_open_and_says_so(make_app, monkeypatch):
    monkeypatch.setattr(settings_module, "restart_as_admin", lambda: False)
    monkeypatch.setattr(settings_module, "is_elevated", lambda: False)
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.click("#restart-admin")
        await pilot.pause()
        assert "did not restart" in plain(app.screen.query_one("#settings-note"))


async def test_restart_as_admin_hidden_when_already_admin(make_app, monkeypatch):
    monkeypatch.setattr(settings_module, "is_elevated", lambda: True)
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert not app.screen.query_one("#restart-admin", Button).display


async def test_restart_as_admin_blocked_during_a_run(make_app, monkeypatch):
    monkeypatch.setattr(settings_module, "is_elevated", lambda: False)
    app = make_app(FakeBackend([], speed=2))
    asked(app)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await until(lambda: app.runner.view.stage is Stage.DOWNLOADING)
        await pilot.press("t")
        await pilot.pause()
        assert app.screen.query_one("#restart-admin", Button).disabled
        await app.runner.shutdown()
