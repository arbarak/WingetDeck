import asyncio
from dataclasses import replace

from textual.widgets import Button, Checkbox, Input, RichLog, Select

from wingetdeck.core.queue import ItemState, RunState
from wingetdeck.ui.screens import logs as logs_module
from wingetdeck.ui.screens.details import DetailsScreen
from wingetdeck.ui.screens.dialogs import ConfirmDialog
from wingetdeck.ui.screens.logs import LogsScreen, TranscriptScreen
from wingetdeck.ui.screens.package_options import PackageOptionsScreen
from wingetdeck.ui.screens.progress import ProgressScreen
from wingetdeck.ui.screens.settings import SettingsScreen
from wingetdeck.ui.widgets.package_table import PackageTable
from wingetdeck.winget import real
from wingetdeck.winget.backend import PackageDetails, UpgradeOptions
from wingetdeck.winget.fake import FakeBackend
from wingetdeck.winget.models import ChangeKind, Package

WIDE = (130, 90)
AGREEMENTS = 0x8A150041


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


def plain(widget):
    return str(widget.render())


def consented(app):
    app.store.save_settings(replace(app.store.load_settings(), asked_agreements=True))


async def until(check, seconds=8.0):
    async def poll():
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), seconds)


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_table(app, pilot):
    await pilot.pause()
    app.show_packages(None)
    await settle(app, pilot)
    return app.screen.query_one(PackageTable)


async def test_logs_filter_by_level_and_package(make_app):
    app = make_app()
    app.log_file.info("plain info", package="A")
    app.log_file.error("bad thing", package="B")
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, LogsScreen)
        await pilot.click("#level-ERROR")
        await pilot.pause()
        assert [e.message for e in screen.shown] == ["bad thing"]
        await pilot.click("#level-ALL")
        await pilot.pause()
        screen.query_one("#package", Select).value = "A"
        await pilot.pause()
        assert [e.message for e in screen.shown] == ["plain info"]


async def test_error_see_details_opens_package_log(make_app):
    app = make_app()
    with app.log_file.package_transcript("Git.Git") as f:
        f.write("winget said this\n")
    app.log_file.error("failed", package="Git.Git")
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        await pilot.click("#level-ERROR")
        await pilot.pause()
        app.screen.open_event(0)
        await pilot.pause()
        assert isinstance(app.screen, TranscriptScreen)
        text = "\n".join(s.text for s in app.screen.query_one(RichLog).lines)
        assert "winget said this" in text


async def test_error_without_transcript_says_so(make_app):
    app = make_app()
    app.log_file.error("failed", package="Nothing.Here")
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        await pilot.click("#level-ERROR")
        await pilot.pause()
        app.screen.open_event(0)
        await pilot.pause()
        assert "no winget output" in "\n".join(s.text for s in app.screen.query_one(RichLog).lines).lower()


async def test_open_folder_uses_startfile(make_app, monkeypatch):
    opened = []
    monkeypatch.setattr(logs_module.os, "startfile", opened.append, raising=False)
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        await pilot.click("#open-folder")
        await pilot.pause()
        assert opened == [str(app.log_file.data_dir.logs)]


async def test_diagnostic_report_lists_contents_before_saving(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("l")
        await pilot.pause()
        await pilot.click("#save-report")
        await settle(app, pilot)
        assert isinstance(app.screen, ConfirmDialog)
        assert "winget_info.txt" in plain(app.screen.query_one("#dialog-text"))
        assert not list(app.log_file.data_dir.logs.glob("diagnostic_*"))
        await pilot.click("#choice-0")
        await settle(app, pilot)
        reports = list(app.log_file.data_dir.logs.glob("diagnostic_*.zip"))
        assert len(reports) == 1 and reports[0].name in plain(app.screen.query_one("#logs-note"))


async def test_size_warning_above_500_mb(make_app):
    app = make_app()
    app.log_file.total_size_bytes = lambda: 600 * 1024 * 1024
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        text = plain(app.screen.query_one("#log-size"))
        assert "600 MB" in text and "large" in text.lower()


async def test_cleanup_always_asks_and_keeps_current_session(make_app):
    app = make_app()
    old = app.log_file.data_dir.logs / "session_old.log"
    old.write_text("old", encoding="utf-8")
    current = app.log_file.text_path
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.click("#cleanup")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog) and old.exists()
        await pilot.click("#cancel")
        await pilot.pause(0.3)
        assert old.exists()
        await pilot.click("#cleanup")
        await pilot.pause()
        await pilot.click("#choice-0")
        await pilot.pause()
        assert not old.exists() and current.exists()


async def test_first_run_consent_prompt_once(make_app):
    backend = FakeBackend([], speed=200)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await pilot.pause()
        assert isinstance(app.screen, ConfirmDialog)
        assert "--accept-package-agreements" in plain(app.screen.query_one("#dialog-text"))
        assert backend.calls == [], "nothing starts before the answer"
        await pilot.click("#choice-0")
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        await pilot.pause()
        settings = app.store.load_settings()
        assert settings.asked_agreements and settings.consented_agreements
        assert backend.options_seen["A"].accept_agreements
        assert backend.accept_source_agreements
        app.start_upgrade([pkg("B")])
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmDialog)
        await until(lambda: "upgrade:B" in backend.calls)
        await app.runner.shutdown()


async def test_saying_cancel_to_consent_does_not_start_and_asks_again(make_app):
    backend = FakeBackend([], speed=200)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await pilot.pause()
        await pilot.click("#cancel")
        await pilot.pause()
        assert backend.calls == [] and not app.store.load_settings().asked_agreements


async def test_without_consent_agreement_packages_marked_skipped(make_app):
    backend = FakeBackend([], speed=200, script={"A": AGREEMENTS})
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await pilot.pause()
        await pilot.click("#choice-1")
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        await pilot.pause()
        assert not backend.options_seen["A"].accept_agreements
        assert app.runner.view.items[0].state is ItemState.SKIPPED
        assert "agreement" in app.runner.view.items[0].message.lower()


async def test_saved_consent_reaches_the_backend_on_launch(make_app):
    backend = FakeBackend([], speed=200)
    app = make_app(backend)
    app.store.save_settings(replace(app.store.load_settings(), asked_agreements=True, consented_agreements=True))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        assert backend.accept_source_agreements


async def test_per_package_options_override_defaults(make_app):
    backend = FakeBackend([pkg("A"), pkg("B")], speed=200)
    app = make_app(backend)
    consented(app)
    async with app.run_test(size=WIDE) as pilot:
        table = await open_table(app, pilot)
        table.focus()
        await pilot.press("d")
        await settle(app, pilot)
        assert isinstance(app.screen, DetailsScreen)
        target = app.screen.package.id
        await pilot.click("#options")
        await pilot.pause()
        assert isinstance(app.screen, PackageOptionsScreen)
        app.screen.query_one("#opt-force", Checkbox).value = True
        await pilot.pause()
        await pilot.click("#save-options")
        await pilot.pause()
        settings = app.store.load_settings()
        assert settings.per_package[target].force and not settings.defaults.force
        other = "B" if target == "A" else "A"
        assert app.options_for(pkg(target)).force and not app.options_for(pkg(other)).force


async def test_clearing_package_options_goes_back_to_defaults(make_app):
    app = make_app(FakeBackend([pkg("A")], speed=200))
    settings = app.store.load_settings()
    app.store.save_settings(replace(settings, per_package={"A": UpgradeOptions(force=True)}))
    async with app.run_test(size=WIDE) as pilot:
        table = await open_table(app, pilot)
        table.focus()
        await pilot.press("d")
        await settle(app, pilot)
        await pilot.click("#options")
        await pilot.pause()
        assert app.screen.query_one("#opt-force", Checkbox).value
        await pilot.click("#clear-options")
        await pilot.pause()
        assert "A" not in app.store.load_settings().per_package


async def test_default_options_saved_from_settings(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, SettingsScreen)
        screen.query_one("#opt-mode", Select).value = "interactive"
        screen.query_one("#opt-scope", Select).value = "machine"
        screen.query_one("#opt-custom", Input).value = "/quiet"
        await pilot.pause()
        await pilot.click("#save-settings")
        await pilot.pause()
        defaults = app.store.load_settings().defaults
        assert defaults.interactive and not defaults.silent
        assert defaults.scope == "machine" and defaults.custom == "/quiet"


async def test_settings_change_theme_and_times(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#theme", Select).value = "wingetdeck-amber"
        screen.query_one("#stall-minutes", Input).value = "20"
        screen.query_one("#auto-check", Input).value = "30"
        await pilot.pause()
        await pilot.click("#save-settings")
        await pilot.pause()
        saved = app.store.load_settings()
        assert (saved.theme, saved.stall_minutes, saved.auto_check_minutes) == ("wingetdeck-amber", 20, 30)
        assert app.theme == "wingetdeck-amber"


async def test_bad_numbers_in_settings_are_refused_with_a_message(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        screen = app.screen
        screen.query_one("#stall-minutes", Input).value = "soon"
        await pilot.pause()
        await pilot.click("#save-settings")
        await pilot.pause()
        assert app.store.load_settings().stall_minutes == 10
        assert "number" in plain(screen.query_one("#settings-note")).lower()


async def test_undo_direct_downloader_restores_file(make_app, tmp_path, monkeypatch):
    target = tmp_path / "settings.json"
    target.write_text('{"a": 1}', encoding="utf-8")
    monkeypatch.setattr(real, "default_settings_path", lambda: target)

    class Both(FakeBackend):
        enable_direct_downloader = real.RealBackend.enable_direct_downloader
        undo_direct_downloader = real.RealBackend.undo_direct_downloader

    app = make_app(Both([], speed=200))
    app.backend._log = app.log_file
    change = app.backend.enable_direct_downloader(tmp_path)
    assert "wininet" in target.read_text(encoding="utf-8")
    stored = {"previous_existed": change.previous_existed, "previous_value": change.previous_value,
              "backup": str(change.backup)}
    app.store.save_settings(replace(app.store.load_settings(), moved_downloader=stored))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert "on" in plain(app.screen.query_one("#direct-status")).lower()
        await pilot.click("#undo-direct")
        await pilot.pause()
        assert target.read_text(encoding="utf-8") == '{"a": 1}'
        assert app.store.load_settings().moved_downloader is None
        assert app.screen.query_one("#undo-direct", Button).disabled


async def test_save_stays_on_screen_in_a_small_window(make_app):
    app = make_app()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        await pilot.click("#save-settings")
        await pilot.pause()
        assert "Saved" in plain(app.screen.query_one("#settings-note"))


async def test_no_undo_when_nothing_was_changed(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        await pilot.press("t")
        await pilot.pause()
        assert app.screen.query_one("#undo-direct", Button).disabled


async def test_details_shows_publisher_homepage_notes(make_app):
    app = make_app(FakeBackend([pkg("A")], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        table = await open_table(app, pilot)
        table.focus()
        await pilot.press("d")
        await settle(app, pilot)
        text = plain(app.screen.query_one("#details-text"))
        assert "Example Publisher" in text and "https://example.com" in text and "Bug fixes" in text


async def test_details_missing_fields_show_dash(make_app):
    class Bare(FakeBackend):
        async def show(self, package_id):
            return PackageDetails()

    app = make_app(Bare([pkg("A")], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        table = await open_table(app, pilot)
        table.focus()
        await pilot.press("d")
        await settle(app, pilot)
        assert "Publisher: —" in plain(app.screen.query_one("#details-text"))


async def test_details_failure_is_shown_not_a_crash(make_app):
    class Broken(FakeBackend):
        async def show(self, package_id):
            raise real.WingetError("no details")

    app = make_app(Broken([pkg("A")], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        table = await open_table(app, pilot)
        table.focus()
        await pilot.press("d")
        await settle(app, pilot)
        assert "no details" in plain(app.screen.query_one("#details-text"))


async def test_pin_and_ignore_actions_persist(make_app):
    backend = FakeBackend([pkg("A"), pkg("B")], speed=200)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        table = await open_table(app, pilot)
        table.focus()
        await pilot.press("d")
        await settle(app, pilot)
        target = app.screen.package.id
        await pilot.click("#pin")
        await settle(app, pilot)
        assert backend.pin_ids == [target]
        assert "Unpin" in str(app.screen.query_one("#pin", Button).label)
        await pilot.pause(0.3)
        await pilot.click("#pin")
        await settle(app, pilot)
        assert backend.pin_ids == []
        await pilot.click("#ignore")
        await settle(app, pilot)
        assert target in app.store.load_settings().ignored
        assert target not in {p.id for p in table.rows}


async def test_removing_from_ignored_list_brings_the_package_back(make_app):
    app = make_app(FakeBackend([pkg("A")], speed=200))
    app.store.save_settings(replace(app.store.load_settings(), ignored={"A"}))
    async with app.run_test(size=WIDE) as pilot:
        table = await open_table(app, pilot)
        assert table.rows == []
        await pilot.press("t")
        await pilot.pause()
        await pilot.click("#clear-ignored")
        await pilot.pause()
        assert app.store.load_settings().ignored == set()
        await pilot.press("escape")
        await settle(app, pilot)
        assert [p.id for p in table.rows] == ["A"]


async def test_logs_settings_open_from_the_progress_screen(make_app):
    app = make_app(FakeBackend([], speed=5))
    consented(app)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await pilot.press("l")
        await pilot.pause()
        assert isinstance(app.screen, LogsScreen)
        await pilot.press("l")
        await pilot.pause()
        assert len([s for s in app.screen_stack if isinstance(s, LogsScreen)]) == 1
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, ProgressScreen)
        await app.runner.shutdown()
