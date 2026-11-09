import asyncio
from dataclasses import replace

from textual.widgets import Button, RichLog

from wingetdeck.core.queue import ItemState, RunState
from wingetdeck.ui.screens.dialogs import ConfirmDialog
from wingetdeck.ui.screens.packages import PackagesScreen
from wingetdeck.ui.screens.progress import ProgressScreen
from wingetdeck.ui.widgets.meters import Meter, PercentBar, StageList, sparkline
from wingetdeck.ui.widgets.queue_panel import QueuePanel
from wingetdeck.winget.backend import FinishedEvent, ProgressEvent, StageEvent
from wingetdeck.winget.fake import FakeBackend
from wingetdeck.winget.models import ChangeKind, Package, Progress, Stage

WIDE = (130, 40)
IN_USE = 0x8A150101
RESTART = 0x8A150109


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


def plain(widget):
    return str(widget.render())


async def until(check, seconds=8.0):
    async def poll():
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), seconds)


async def begin(app, pilot, ids=("A", "B"), stage=None):
    await pilot.pause()
    app.store.save_settings(replace(app.store.load_settings(), asked_agreements=True))
    app.start_upgrade([pkg(i) for i in ids])
    await until(lambda: isinstance(app.screen, ProgressScreen))
    if stage is not None:
        await until(lambda: app.runner.view.stage is stage)
    await pilot.pause()
    return app.screen


async def finished(app, pilot):
    await until(lambda: app.runner.view.state is RunState.FINISHED)
    await pilot.pause()
    await pilot.pause()


class Scripted(FakeBackend):
    """Stays in one stage, with or without numbers, until released."""

    def __init__(self, events, direct=True):
        super().__init__([], direct_downloader=direct)
        self.events = events
        self.release = None
        self.started = []

    def start_upgrade(self, package, options):
        backend = self
        backend.started.append(package.id)

        class Handle:
            pid = 0

            def freeze(self):
                return True

            def thaw(self):
                pass

            def kill(self):
                from wingetdeck.winget.proc import KillResult

                backend.release.set()
                return KillResult(True)

            async def events(self):
                backend.release = asyncio.Event()
                for event in backend.events:
                    yield event
                await backend.release.wait()
                yield FinishedEvent(0)

        return Handle()


async def test_pause_label_during_download_with_direct_downloader(make_app):
    app = make_app(Scripted([StageEvent(Stage.DOWNLOADING)]))
    async with app.run_test(size=WIDE) as pilot:
        screen = await begin(app, pilot, stage=Stage.DOWNLOADING)
        assert str(screen.query_one("#pause", Button).label) == "Pause"
        await app.runner.shutdown()


async def test_pause_button_label_follows_controls_during_install(make_app):
    backend = Scripted([StageEvent(Stage.INSTALLING)])
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        screen = await begin(app, pilot, stage=Stage.INSTALLING)
        pause = screen.query_one("#pause", Button)
        assert str(pause.label) == "Pause after this install"
        await pilot.click("#pause")
        await pilot.pause()
        assert str(pause.label) == "Pausing after this install…" and pause.disabled
        backend.release.set()
        await until(lambda: app.runner.view.state is RunState.PAUSED)
        await pilot.pause()
        assert str(pause.label) == "Resume" and not pause.disabled
        await app.runner.shutdown()


async def test_pause_holds_progress_then_resume_continues(make_app):
    app = make_app(FakeBackend([], speed=1))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await until(lambda: app.runner.view.progress is not None)
        await pilot.click("#pause")
        await pilot.pause()
        held = app.runner.view.progress.percent
        await asyncio.sleep(0.2)
        assert app.runner.view.progress.percent == held
        assert "PAUSED" in plain(app.screen.query_one("#chip"))
        await pilot.click("#pause")
        await until(lambda: app.runner.view.progress and app.runner.view.progress.percent > held)
        await app.runner.shutdown()


async def test_stop_opens_dialog_with_stage_choices(make_app):
    app = make_app(FakeBackend([], speed=1))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await pilot.click("#stop")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        assert app.screen.choices == ("Stop after this one", "Stop now")
        assert "partial" in plain(app.screen.query_one("#dialog-text")).lower()
        await pilot.click("#cancel")
        await pilot.pause()
        assert isinstance(app.screen, ProgressScreen)
        assert app.runner.view.state is RunState.RUNNING
        await app.runner.shutdown()


async def test_stop_now_from_the_dialog_stops_the_run(make_app):
    backend = Scripted([StageEvent(Stage.DOWNLOADING)])
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await pilot.click("#stop")
        await pilot.pause()
        await pilot.click("#choice-1")
        await finished(app, pilot)
        assert [i.state for i in app.runner.view.items] == [ItemState.STOPPED, ItemState.STOPPED]
        assert backend.started == ["A"]


async def test_stop_after_this_one_from_the_dialog(make_app):
    backend = Scripted([StageEvent(Stage.DOWNLOADING)])
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await pilot.click("#stop")
        await pilot.pause()
        await pilot.click("#choice-0")
        await pilot.pause()
        backend.release.set()
        await finished(app, pilot)
        assert [i.state for i in app.runner.view.items] == [ItemState.DONE, ItemState.STOPPED]


async def test_force_stop_warns_about_broken_app(make_app):
    app = make_app(Scripted([StageEvent(Stage.INSTALLING)]))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A",), stage=Stage.INSTALLING)
        await pilot.click("#stop")
        await pilot.pause()
        assert app.screen.choices == ("Stop after this one", "Force stop")
        await pilot.click("#choice-1")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog), "force stop asks a second time"
        assert "broken" in plain(app.screen.query_one("#dialog-text")).lower()
        assert app.runner.view.state is RunState.RUNNING
        await pilot.click("#choice-0")
        await finished(app, pilot)
        assert app.runner.view.items[0].state is ItemState.FAILED


async def test_force_stop_can_be_called_off(make_app):
    app = make_app(Scripted([StageEvent(Stage.INSTALLING)]))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A",), stage=Stage.INSTALLING)
        await pilot.click("#stop")
        await pilot.pause()
        await pilot.click("#choice-1")
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()
        assert app.runner.view.state is RunState.RUNNING
        await app.runner.shutdown()


async def test_stop_now_without_direct_says_download_may_continue(make_app):
    app = make_app(FakeBackend([], speed=1, direct_downloader=False))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await pilot.click("#stop")
        await pilot.pause()
        text = plain(app.screen.query_one("#dialog-text")).lower()
        assert "background" in text and "nothing will install" in text
        await pilot.click("#cancel")
        await app.runner.shutdown()


async def test_stop_between_packages_has_one_choice(make_app):
    backend = Scripted([StageEvent(Stage.INSTALLING)])
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.INSTALLING)
        await pilot.click("#pause")
        await pilot.pause()
        backend.release.set()
        await until(lambda: app.runner.view.state is RunState.PAUSED)
        await pilot.pause()
        await pilot.click("#stop")
        await pilot.pause()
        assert app.screen.choices == ("Stop",)
        await pilot.click("#choice-0")
        await finished(app, pilot)
        assert app.runner.view.items[1].state is ItemState.STOPPED


async def test_first_pause_during_download_offers_direct_downloader_once(make_app):
    backend = Scripted([StageEvent(Stage.DOWNLOADING)], direct=False)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await pilot.click("#pause")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        assert "all winget" in plain(app.screen.query_one("#dialog-text")).lower()
        await pilot.click("#cancel")
        await pilot.pause()
        assert not backend.direct_downloader
        assert app.store.load_settings().offered_direct_downloader
        assert str(app.screen.query_one("#pause", Button).label) == "Pausing after this package…"
        await app.runner.shutdown()


async def test_offer_is_not_repeated(make_app):
    backend = FakeBackend([], speed=1, direct_downloader=False)
    app = make_app(backend)
    app.store.save_settings(replace(app.store.load_settings(), offered_direct_downloader=True))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await pilot.click("#pause")
        await pilot.pause()
        assert isinstance(app.screen, ProgressScreen)
        await app.runner.shutdown()


async def test_no_offer_when_settings_are_locked(make_app):
    class Locked(FakeBackend):
        def capabilities(self):
            return replace(super().capabilities(), settings_locked=True)

    app = make_app(Locked([], speed=1, direct_downloader=False))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await pilot.click("#pause")
        await pilot.pause()
        assert isinstance(app.screen, ProgressScreen)
        await app.runner.shutdown()


async def test_accepting_offer_records_the_change_and_applies_from_next_package(make_app):
    backend = Scripted([StageEvent(Stage.DOWNLOADING)], direct=False)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await pilot.click("#pause")
        await until(lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.pause()
        await pilot.click("#choice-0")
        await pilot.pause()
        assert backend.direct_downloader
        assert app.store.load_settings().moved_downloader is not None
        assert not app.runner.view.direct_downloader, "the running package started under the old setting"
        backend.release.set()
        await until(lambda: app.runner.view.state is RunState.PAUSED)
        await pilot.pause()
        await pilot.click("#pause")
        await until(lambda: app.runner.view.direct_downloader)
        await app.runner.shutdown()


async def test_failing_to_change_the_setting_is_reported(make_app):
    class Broken(FakeBackend):
        def enable_direct_downloader(self, backups):
            raise OSError("read only")

    app = make_app(Broken([], speed=1, direct_downloader=False))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, stage=Stage.DOWNLOADING)
        await pilot.click("#pause")
        await until(lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.pause()
        await pilot.click("#choice-0")
        await pilot.pause()
        assert "read only" in plain(app.screen.query_one("#notice"))
        assert app.store.load_settings().moved_downloader is None
        await app.runner.shutdown()


async def test_no_number_shows_animation_and_elapsed_not_percent(make_app):
    app = make_app(Scripted([StageEvent(Stage.INSTALLING)]))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A",), stage=Stage.INSTALLING)
        bar = plain(app.screen.query_one(PercentBar))
        assert "%" not in bar and "00:0" in bar
        first = bar
        await asyncio.sleep(0.5)
        await pilot.pause()
        assert plain(app.screen.query_one(PercentBar)) != first, "the animation moves"
        await app.runner.shutdown()


async def test_numbers_come_from_winget(make_app):
    app = make_app(Scripted([StageEvent(Stage.DOWNLOADING), ProgressEvent(Progress(45.0, 223.0, 494.0))]))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A",), stage=Stage.DOWNLOADING)
        await until(lambda: app.runner.view.progress is not None)
        await pilot.pause()
        bar = plain(app.screen.query_one(PercentBar))
        assert "45%" in bar and "223 MB / 494 MB" in bar
        assert "—" in plain(app.screen.query_one("#meter-speed", Meter)), "one sample gives no speed"
        await app.runner.shutdown()


async def test_percent_without_sizes_shows_only_the_percent(make_app):
    app = make_app(Scripted([StageEvent(Stage.DOWNLOADING), ProgressEvent(Progress(30.0, None, None))]))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A",), stage=Stage.DOWNLOADING)
        await until(lambda: app.runner.view.progress is not None)
        await pilot.pause()
        bar = plain(app.screen.query_one(PercentBar))
        assert "30%" in bar and "MB" not in bar


async def test_stages_mark_where_the_package_is(make_app):
    app = make_app(Scripted([StageEvent(Stage.VERIFYING)]))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A",), stage=Stage.VERIFYING)
        lines = plain(app.screen.query_one(StageList)).splitlines()
        assert lines[0].startswith("✓") and lines[1].startswith("›") and lines[2].startswith(" ")
        await app.runner.shutdown()


async def test_stall_warning_appears(make_app):
    app = make_app(Scripted([StageEvent(Stage.INSTALLING)]))
    app.runner._stall_seconds = 0.03
    app.runner._tick = 0.01
    async with app.run_test(size=WIDE) as pilot:
        screen = await begin(app, pilot, ids=("A",), stage=Stage.INSTALLING)
        await until(lambda: app.runner.view.stalled)
        await pilot.pause()
        text = plain(screen.query_one("#notice"))
        assert "no output" in text.lower() and "nothing was stopped" in text.lower()
        assert app.runner.view.state is RunState.RUNNING
        await app.runner.shutdown()


async def test_log_panel_shows_winget_output(make_app):
    app = make_app(FakeBackend([], speed=100))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A",))
        await finished(app, pilot)
        text = "\n".join(strip.text for strip in app.screen.query_one("#run-log", RichLog).lines)
        assert "Successfully installed" in text


async def test_queue_move_and_remove_only_waiting(make_app):
    app = make_app(FakeBackend([], speed=1))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A", "B", "C"), stage=Stage.DOWNLOADING)
        panel = app.screen.query_one(QueuePanel)
        assert not list(panel.query("#up-A, #down-A, #remove-A")), "the active item has no controls"
        await pilot.click("#up-C")
        await pilot.pause()
        assert [i.package.id for i in app.runner.view.items] == ["A", "C", "B"]
        await pilot.click("#remove-B")
        await pilot.pause()
        assert [i.package.id for i in app.runner.view.items] == ["A", "C"]
        await app.runner.shutdown()


async def test_back_keeps_run_going_and_return_button_appears(make_app):
    app = make_app(FakeBackend([pkg("A")], speed=1))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.show_packages(None)
        await pilot.pause()
        await begin(app, pilot, ids=("A",), stage=Stage.DOWNLOADING)
        await pilot.click("#back")
        await pilot.pause()
        assert isinstance(app.screen, PackagesScreen)
        assert app.runner.view.state is RunState.RUNNING
        back = app.screen.query_one("#to-run", Button)
        assert back.display
        await pilot.click(back)
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await app.runner.shutdown()


async def test_finished_run_rescans_the_packages_screen(make_app):
    backend = FakeBackend([pkg("A"), pkg("B")], speed=100)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.show_packages(None)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await begin(app, pilot, ids=("A",))
        await finished(app, pilot)
        await pilot.click("#back")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        from wingetdeck.ui.widgets.package_table import PackageTable

        assert [p.id for p in app.screen.query_one(PackageTable).rows] == ["B"]


async def test_summary_shows_counts_restart_needed_and_retry(make_app):
    backend = FakeBackend([], speed=200, script={"B": RESTART, "C": [IN_USE, 0]})
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A", "B", "C"))
        await finished(app, pilot)
        screen = app.screen
        text = plain(screen.query_one("#summary"))
        assert "2 upgraded" in text and "1 needs a restart" in text and "1 failed" in text
        assert screen.query_one("#summary").display
        retry = screen.query_one("#retry", Button)
        assert retry.display
        assert not screen.query_one("#pause", Button).display
        await pilot.click(retry)
        await until(lambda: backend.calls.count("upgrade:C") == 2)
        await finished(app, pilot)
        assert [i.package.id for i in app.runner.view.items] == ["C"]
        assert app.runner.view.items[0].state is ItemState.DONE


async def test_no_retry_button_when_nothing_failed(make_app):
    app = make_app(FakeBackend([], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A",))
        await finished(app, pilot)
        assert not app.screen.query_one("#retry", Button).display


async def test_in_use_failure_names_the_app_and_offers_retry_only(make_app):
    app = make_app(FakeBackend([], speed=200, script={"Git.Git": IN_USE}))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("Git.Git",))
        await finished(app, pilot)
        text = plain(app.screen.query_one("#item-notes"))
        assert "Git.Git" in text and "close" in text.lower()
        labels = [str(b.label).lower() for b in app.screen.query(Button)]
        assert "retry failed" in labels and not any(label.startswith("close") for label in labels)


async def test_access_denied_is_shown(make_app):
    class Denied(Scripted):
        def start_upgrade(self, package, options):
            handle = super().start_upgrade(package, options)
            from wingetdeck.winget.proc import KillResult

            handle.kill = lambda: KillResult(False, access_denied=True)
            return handle

    app = make_app(Denied([StageEvent(Stage.INSTALLING)]))
    async with app.run_test(size=WIDE) as pilot:
        await begin(app, pilot, ids=("A",), stage=Stage.INSTALLING)
        await pilot.click("#stop")
        await pilot.pause()
        await pilot.click("#choice-1")
        await pilot.pause()
        await pilot.click("#choice-0")
        await pilot.pause()
        assert "administrator" in plain(app.screen.query_one("#notice")).lower()
        await app.runner.shutdown()


def test_sparkline_scales_to_the_highest_value_and_fits():
    top, bottom = sparkline([0, 5, 10], width=5, ascii_mode=False)
    assert len(top) == len(bottom) == 5
    assert bottom[-1] == "█" and top[-1] == "█"
    assert bottom[0] == " "


def test_sparkline_ascii_is_ascii():
    top, bottom = sparkline([1, 2, 3], width=5, ascii_mode=True)
    assert (top + bottom).isascii()


def test_sparkline_with_no_data_is_blank():
    assert sparkline([], width=4, ascii_mode=False) == ("    ", "    ")
