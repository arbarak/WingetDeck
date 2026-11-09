"""Findings from the whole-project review, each with the test that reproduced it."""

import asyncio
from dataclasses import replace

from wingetdeck.core.queue import RunState
from wingetdeck.core.safety import RestoreResult
from wingetdeck.core.store import QueueItem, QueueSnapshot
from wingetdeck.ui.screens.dialogs import ConfirmDialog
from wingetdeck.ui.screens.packages import PackagesScreen
from wingetdeck.ui.screens.progress import ProgressScreen
from wingetdeck.ui.screens.settings import SettingsScreen
from wingetdeck.ui.screens.splash import SplashScreen
from wingetdeck.ui.widgets.package_table import PackageTable
from wingetdeck.winget.backend import FinishedEvent, StageEvent
from wingetdeck.winget.fake import FakeBackend, demo_packages
from wingetdeck.winget.models import ChangeKind, Package, Stage
from wingetdeck.winget.real import WingetError

WIDE = (130, 40)
AGREEMENTS_NOT_ACCEPTED = 0x8A150046


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


async def until(check, seconds=8.0):
    async def poll():
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), seconds)


class Held(FakeBackend):
    """Stays in one stage until released."""

    def __init__(self, stage):
        super().__init__([])
        self.stage = stage
        self.release = None
        self.killed = False

    def start_upgrade(self, package, options):
        backend = self

        class Handle:
            pid = 0

            def freeze(self):
                return True

            def thaw(self):
                pass

            def kill(self):
                from wingetdeck.winget.proc import KillResult

                backend.killed = True
                backend.release.set()
                return KillResult(True)

            async def events(self):
                backend.release = asyncio.Event()
                yield StageEvent(backend.stage)
                await backend.release.wait()
                yield FinishedEvent(0)

        return Handle()


async def running(app, pilot, stage, ids=("A",)):
    await pilot.pause()
    app.store.save_settings(replace(app.store.load_settings(), asked_agreements=True))
    app.start_upgrade([pkg(i) for i in ids])
    await until(lambda: isinstance(app.screen, ProgressScreen))
    await until(lambda: app.runner.view.stage is stage)
    await pilot.pause()


# Quitting during a run


async def test_quitting_during_an_install_says_what_will_really_happen(make_app):
    app = make_app(Held(Stage.INSTALLING))
    async with app.run_test(size=WIDE) as pilot:
        await running(app, pilot, Stage.INSTALLING)
        await app.action_quit()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        text = str(app.screen.query_one("#dialog-text").render())
        assert "half-installed" in text and "winget" in text
        assert app.screen.choices == ("Quit after this package", "Quit now")
        assert app.is_running
        await pilot.click("#cancel")
        await pilot.pause()
        assert isinstance(app.screen, ProgressScreen)
        assert app.runner.view.state is RunState.RUNNING
        await app.runner.shutdown()


async def test_quit_after_this_package_finishes_it_and_leaves(make_app):
    backend = Held(Stage.INSTALLING)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await running(app, pilot, Stage.INSTALLING, ids=("A", "B"))
        await app.action_quit()
        await pilot.pause()
        await pilot.click("#choice-0")
        await pilot.pause()
        assert app.is_running and not backend.killed
        backend.release.set()
        await until(lambda: not app.is_running)
    assert app.return_code == 0
    assert app._exception is None


async def test_quit_now_leaves_at_once_and_keeps_the_queue(make_app):
    app = make_app(Held(Stage.INSTALLING))
    async with app.run_test(size=WIDE) as pilot:
        await running(app, pilot, Stage.INSTALLING, ids=("A", "B"))
        await app.action_quit()
        await pilot.pause()
        await pilot.click("#choice-1")
        await until(lambda: not app.is_running)
    assert app._exception is None
    assert app.store.load_queue() is not None


async def test_quit_key_on_the_splash_with_no_run_just_quits(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.action_quit()
        await pilot.pause()
    assert not app.is_running


async def test_the_log_no_longer_claims_an_installer_is_left_to_finish(make_app):
    app = make_app(Held(Stage.INSTALLING))
    async with app.run_test(size=WIDE) as pilot:
        await running(app, pilot, Stage.INSTALLING)
        app.runner.emergency_stop()
        messages = [e.message for e in app.log_file.events("WARN")]
        assert not any("left to finish" in m for m in messages)
        assert any("winget ends with" in m for m in messages)
        await app.runner.shutdown()


# The "warn after no output" setting


async def test_the_saved_stall_setting_reaches_the_run(make_app):
    app = make_app()
    app.store.save_settings(replace(app.store.load_settings(), stall_minutes=2))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.runner._stall_seconds == 120


async def test_changing_the_stall_setting_applies_straight_away(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.action_show_settings()
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)
        app.screen.query_one("#stall-minutes").value = "3"
        await pilot.click("#save-settings")
        await pilot.pause()
        assert app.store.load_settings().stall_minutes == 3
        assert app.runner._stall_seconds == 180


# A PC that has never accepted winget's source agreements


class NeedsAgreement(FakeBackend):
    async def scan(self, source, include_pinned=False):
        if not self.accept_source_agreements:
            raise WingetError("Source agreements were not agreed to (0x8A150046)", code=AGREEMENTS_NOT_ACCEPTED)
        return await super().scan(source, include_pinned)


async def test_a_scan_refused_for_agreements_asks_and_scans_again(make_app):
    app = make_app(NeedsAgreement(demo_packages(), speed=200))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.show_packages(None)
        await until(lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.pause()
        await pilot.click("#choice-0")
        await until(lambda: isinstance(app.screen, PackagesScreen))
        await until(lambda: len(app.screen.query_one(PackageTable).rows) > 0)
        settings = app.store.load_settings()
        assert settings.consented_agreements and settings.asked_agreements


async def test_declining_after_a_refused_scan_says_how_to_change_it(make_app):
    app = make_app(NeedsAgreement(demo_packages(), speed=200))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.show_packages(None)
        await until(lambda: isinstance(app.screen, ConfirmDialog))
        await pilot.pause()
        await pilot.click("#cancel")
        await until(lambda: isinstance(app.screen, PackagesScreen))
        await pilot.pause()
        assert "Settings" in str(app.screen.query_one("#table-log").render())


# A damaged data file


async def test_a_damaged_settings_file_is_mentioned_on_the_start_screen(make_app, tmp_data):
    (tmp_data.state / "settings.json").write_text("{ half a fi", encoding="utf-8")
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        notes = str(app.screen.query_one("#notes").render())
        assert "settings.json could not be read" in notes


# Text from PowerShell reaching a toast


async def test_a_bracket_in_a_toast_does_not_crash(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.notify("CategoryInfo : [/Checkpoint-Computer], Win32Exception [oops=]", severity="warning")
        await pilot.pause(0.3)
        assert app._exception is None
    assert app._exception is None


async def test_a_bracket_in_a_restore_point_error_does_not_crash(make_app, monkeypatch):
    import wingetdeck.ui.app as app_module

    message = "CategoryInfo : [/Checkpoint-Computer], Win32Exception [oops=]"
    monkeypatch.setattr(app_module, "create_restore_point", lambda *a, **k: RestoreResult(False, message))
    monkeypatch.setattr(app_module, "is_elevated", lambda: True, raising=False)
    app = make_app(Held(Stage.DOWNLOADING))
    settings = replace(app.store.load_settings(), create_restore_point=True, asked_agreements=True)
    app.store.save_settings(settings)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await until(lambda: app.runner.view.stage is Stage.DOWNLOADING)
        await pilot.pause(0.2)
        assert app._exception is None
        await app.runner.shutdown()
    assert app._exception is None


# The resume offer must come before a new run can overwrite the saved queue


async def test_resume_is_offered_even_while_the_source_list_is_slow(make_app):
    class SlowSources(FakeBackend):
        async def sources(self):
            await asyncio.sleep(30)
            return []

    app = make_app(SlowSources(demo_packages(), speed=200))
    app.store.save_queue(QueueSnapshot([QueueItem("A", "A", "1.0", "1.1", "winget", "waiting")], False))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause(0.3)
        assert isinstance(app.screen, ConfirmDialog), "offered before START can be pressed"
        assert SplashScreen in [type(s) for s in app.screen_stack]
