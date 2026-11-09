import asyncio
from dataclasses import replace

from textual.widgets import Button, Input

from wingetdeck.ui.screens.packages import PackagesScreen
from wingetdeck.ui.widgets.package_table import PackageTable, columns
from wingetdeck.winget.fake import FakeBackend, demo_packages
from wingetdeck.winget.models import ChangeKind, Package
from wingetdeck.winget.real import WingetError

WIDE = (130, 40)


def pkg(i, change=ChangeKind.MINOR, **kw):
    return Package(i, i, "1.0", "1.1", "winget", change, **kw)


async def opened(app, pilot, source=None):
    await pilot.pause()
    app.show_packages(source)
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()
    return app.screen, app.screen.query_one(PackageTable)


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def plain(widget):
    return str(widget.render())


async def click_row(pilot, table, index, **kw):
    await pilot.click(table, offset=(10, 1 + index), **kw)


async def test_click_row_ticks_and_button_counts(make_app):
    app = make_app(FakeBackend([pkg("A"), pkg("B")], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        screen, table = await opened(app, pilot)
        upgrade = screen.query_one("#upgrade", Button)
        assert upgrade.disabled and "UPGRADE" in str(upgrade.label)
        await click_row(pilot, table, 0)
        await pilot.pause()
        assert table.ticked == {table.rows[0].id}
        assert not upgrade.disabled and "(1)" in str(upgrade.label)
        await click_row(pilot, table, 0)
        await pilot.pause()
        assert table.ticked == set() and upgrade.disabled


async def test_shift_click_range(make_app):
    app = make_app(FakeBackend([pkg(c) for c in "ABCDE"], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        await click_row(pilot, table, 1)
        await click_row(pilot, table, 3, shift=True)
        await pilot.pause()
        assert table.ticked == {table.rows[i].id for i in (1, 2, 3)}


async def test_header_click_sorts_then_reverses(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        await pilot.click(table, offset=(8, 0))
        await pilot.pause()
        names = [p.name for p in table.rows]
        assert names == sorted(names, key=str.lower)
        await pilot.click(table, offset=(8, 0))
        await pilot.pause()
        assert [p.name for p in table.rows] == list(reversed(names))


async def test_default_sort_puts_major_first(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        assert table.rows[0].change is ChangeKind.MAJOR


async def test_filter_narrows_and_select_all_only_affects_visible(make_app):
    app = make_app(FakeBackend([pkg("Git.Git"), pkg("Git.LFS"), pkg("7zip.7zip")], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        screen, table = await opened(app, pilot)
        await pilot.press("slash")
        await pilot.press(*"git")
        await pilot.pause()
        assert {p.id for p in table.rows} == {"Git.Git", "Git.LFS"}
        await pilot.click("#select-all")
        await pilot.pause()
        assert table.ticked == {"Git.Git", "Git.LFS"}
        await pilot.press("escape")
        await pilot.pause()
        assert len(table.rows) == 3 and not screen.query_one("#filter", Input).display


async def test_select_by_change_type(make_app):
    app = make_app(FakeBackend([pkg("A", ChangeKind.MAJOR), pkg("B", ChangeKind.PATCH)], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        await opened(app, pilot)
        await pilot.click("#select-patch")
        await pilot.pause()
        assert app.screen.query_one(PackageTable).ticked == {"B"}


async def test_select_none_clears(make_app):
    app = make_app(FakeBackend([pkg("A")], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        await click_row(pilot, table, 0)
        await pilot.click("#select-none")
        await pilot.pause()
        assert table.ticked == set()


async def test_refresh_updates_sources_then_scans_in_that_order(make_app):
    backend = FakeBackend([pkg("A")], speed=200)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await opened(app, pilot)
        backend.calls.clear()
        await pilot.click("#refresh")
        await settle(app, pilot)
        assert backend.calls == ["update_sources", "scan"]


async def test_f5_and_r_also_refresh(make_app):
    backend = FakeBackend([pkg("A")], speed=200)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        await opened(app, pilot)
        await pilot.press("f5")
        await settle(app, pilot)
        await pilot.press("r")
        await settle(app, pilot)
        assert backend.source_updates == 2


async def test_source_update_failure_still_rescans_and_says_so(make_app):
    class Offline(FakeBackend):
        async def update_sources(self):
            raise WingetError("no internet")

    app = make_app(Offline([pkg("A")], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        screen, table = await opened(app, pilot)
        await pilot.click("#refresh")
        await settle(app, pilot)
        assert len(table.rows) == 1
        assert "no internet" in plain(screen.query_one("#table-log"))


async def test_new_row_tagged_and_ticks_survive_refresh(make_app):
    backend = FakeBackend([pkg("A")], speed=200)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        await click_row(pilot, table, 0)
        backend.add_package(pkg("B"))
        await pilot.click("#refresh")
        await settle(app, pilot)
        assert table.ticked == {"A"} and table.new_ids == {"B"}
        row = table.rows.index(next(p for p in table.rows if p.id == "B"))
        assert "NEW" in table.render_line(1 + row).text


async def test_new_tag_clears_on_the_next_refresh(make_app):
    backend = FakeBackend([pkg("A")], speed=200)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        backend.add_package(pkg("B"))
        await pilot.press("r")
        await settle(app, pilot)
        await pilot.press("r")
        await settle(app, pilot)
        assert table.new_ids == set()


async def test_refresh_disabled_during_active_run_and_enabled_when_paused_between(make_app):
    from wingetdeck.core.queue import RunState
    from wingetdeck.winget.backend import UpgradeOptions
    from wingetdeck.winget.models import Stage

    backend = FakeBackend([pkg("A"), pkg("B")], speed=30)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        screen, _ = await opened(app, pilot)
        refresh = screen.query_one("#refresh", Button)
        assert not refresh.disabled
        await app.runner.start([pkg("A"), pkg("B")], lambda p: UpgradeOptions())
        await pilot.pause()
        assert refresh.disabled and "upgrade" in str(refresh.tooltip).lower()
        while app.runner.view.stage is not Stage.INSTALLING:
            await pilot.pause(0.01)
        app.runner.pause()
        while app.runner.view.state is not RunState.PAUSED:
            await pilot.pause(0.01)
        await pilot.pause()
        assert not refresh.disabled
        await app.runner.shutdown()


async def test_empty_scan_shows_message_and_disabled_upgrade(make_app):
    app = make_app(FakeBackend([], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        screen, table = await opened(app, pilot)
        assert "up to date" in plain(screen.query_one("#empty")).lower()
        assert screen.query_one("#empty").display and not table.display
        assert screen.query_one("#upgrade", Button).disabled


async def test_scan_error_is_shown_and_logged_not_crash(make_app):
    app = make_app(FakeBackend([], speed=200, scan_error=WingetError("winget broke")))
    async with app.run_test(size=WIDE) as pilot:
        screen, _ = await opened(app, pilot)
        assert "winget broke" in plain(screen.query_one("#table-log"))
        assert any("winget broke" in str(e.fields) for e in app.log_file.events("ERROR"))
        assert not screen.query_one("#refresh", Button).disabled


async def test_failed_refresh_keeps_the_rows_on_screen(make_app):
    backend = FakeBackend([pkg("A")], speed=200)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        backend.scan_error = WingetError("winget broke")
        await pilot.press("r")
        await settle(app, pilot)
        assert [p.id for p in table.rows] == ["A"]


async def test_pinned_not_selectable_unless_include_pinned(make_app):
    app = make_app(FakeBackend([pkg("A", pinned=True)], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        await click_row(pilot, table, 0)
        await pilot.click("#select-all")
        await pilot.pause()
        assert table.ticked == set()
        assert "pinned" in table.render_line(1).text
        table.include_pinned = True
        await click_row(pilot, table, 0)
        await pilot.pause()
        assert table.ticked == {"A"}


async def test_unresolved_truncated_id_cannot_be_ticked(make_app):
    app = make_app(FakeBackend([pkg("Very.Long.Pac…", truncated_id=True)], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        await click_row(pilot, table, 0)
        await pilot.pause()
        assert table.ticked == set()


async def test_explicit_only_row_can_be_ticked_and_labelled(make_app):
    app = make_app(FakeBackend([pkg("A", explicit_only=True)], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        await click_row(pilot, table, 0)
        await pilot.pause()
        assert table.ticked == {"A"} and "explicit" in table.render_line(1).text


async def test_ignored_package_hidden_with_count_in_log(make_app):
    app = make_app(FakeBackend([pkg("A"), pkg("B")], speed=200))
    app.store.save_settings(replace(app.store.load_settings(), ignored={"B"}))
    async with app.run_test(size=WIDE) as pilot:
        screen, table = await opened(app, pilot)
        assert [p.id for p in table.rows] == ["A"]
        assert "1 ignored" in plain(screen.query_one("#table-log"))


async def test_source_choice_is_passed_to_the_scan(make_app):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot, source="msstore")
        assert {p.source for p in table.rows} == {"msstore"}


async def test_keyboard_moves_and_space_ticks(make_app):
    app = make_app(FakeBackend([pkg("A"), pkg("B")], speed=200))
    async with app.run_test(size=WIDE) as pilot:
        _, table = await opened(app, pilot)
        table.focus()
        await pilot.press("down", "space")
        await pilot.pause()
        assert table.ticked == {table.rows[1].id}


async def test_auto_check_is_off_by_default_and_never_runs_during_a_run(make_app):
    backend = FakeBackend([pkg("A")], speed=20)
    app = make_app(backend)
    async with app.run_test(size=WIDE) as pilot:
        screen, _ = await opened(app, pilot)
        assert screen.auto_check_timer is None
        from wingetdeck.winget.backend import UpgradeOptions

        await app.runner.start([pkg("A")], lambda p: UpgradeOptions())
        backend.calls.clear()
        screen.auto_check()
        await pilot.pause()
        assert "update_sources" not in backend.calls
        await app.runner.shutdown()


async def test_escape_goes_back_to_the_splash(make_app):
    from wingetdeck.ui.screens.splash import SplashScreen

    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await opened(app, pilot)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, SplashScreen)


def test_columns_drop_as_the_window_narrows():
    rows = demo_packages()
    assert [c.key for c in columns(130, rows)] == ["tick", "name", "id", "installed", "available", "source", "change"]
    assert [c.key for c in columns(100, rows)] == ["tick", "name", "installed", "available", "source", "change"]
    assert [c.key for c in columns(60, rows)] == ["tick", "name", "versions"]


def test_columns_fit_the_window_and_share_extra_space():
    rows = demo_packages()
    for width in (50, 79, 80, 119, 120, 200, 300):
        total = sum(c.width for c in columns(width, rows)) + len(columns(width, rows)) - 1
        assert total <= width, width
    wide = {c.key: c.width for c in columns(300, rows)}
    assert wide["name"] > 40 and wide["id"] > 40 and wide["installed"] > 40


def test_wide_names_are_cut_by_display_width(tmp_path):
    from wingetdeck.ui.widgets.package_table import fit

    from rich.cells import cell_len

    assert cell_len(fit("漢字漢字漢字漢字", 7, "…")) == 7
    assert cell_len(fit("ab", 7, "…")) == 7


async def test_quitting_during_a_scan_ends_cleanly(make_app):
    from wingetdeck.winget.fake import FakeBackend, demo_packages

    class SlowScan(FakeBackend):
        async def scan(self, source, include_pinned=False):
            await asyncio.sleep(30)
            return await super().scan(source, include_pinned)

    app = make_app(SlowScan(demo_packages()))
    async with app.run_test() as pilot:
        await pilot.pause()
        app.show_packages(None)
        await pilot.pause(0.2)
        assert app.screen._scanning
        await app.action_quit()
    assert app._exception is None
