import asyncio
from dataclasses import replace

import pytest
from textual.widgets import Button

from wingetdeck.core.queue import RunItem, RunState, Summary
from wingetdeck.core.runner import RunView
from wingetdeck.ui.responsive import MIN_HEIGHT, MIN_WIDTH, layout_band, taskbar_code, title_text
from wingetdeck.ui.screens.logs import LogsScreen
from wingetdeck.ui.screens.progress import ProgressScreen
from wingetdeck.ui.screens.settings import SettingsScreen
from wingetdeck.ui.widgets.package_table import PackageTable, columns
from wingetdeck.winget.fake import FakeBackend, demo_packages
from wingetdeck.winget.models import ChangeKind, Package, Progress, Stage

SIZES = [(160, 50), (120, 30), (119, 30), (80, 24), (79, 24), (60, 20), (50, 16)]


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


def view(done=2, total=7, percent=42.0, state=RunState.RUNNING):
    from wingetdeck.core.queue import ItemState

    items = [RunItem(pkg(str(n))) for n in range(total)]
    for item in items[:done]:
        item.state = ItemState.DONE
    return RunView(
        state=state,
        items=tuple(items),
        progress=Progress(percent, None, None) if percent is not None else None,
        summary=Summary(done, 0, 0, 0, 0),
    )


async def until(check, seconds=8.0):
    async def poll():
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), seconds)


def asked(app):
    app.store.save_settings(replace(app.store.load_settings(), asked_agreements=True))


def assert_buttons_inside(app, width, height):
    for button in app.screen.query(Button):
        if not button.display or not button.is_on_screen:
            continue
        region = button.region
        assert region.right <= width and region.x >= 0, f"{button} {region} at {width}x{height}"


@pytest.mark.parametrize("w,h", SIZES)
async def test_every_screen_renders_without_overflow(make_app, w, h):
    app = make_app(FakeBackend(demo_packages(), speed=2))
    asked(app)
    async with app.run_test(size=(w, h)) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert_buttons_inside(app, w, h)
        app.show_packages(None)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert_buttons_inside(app, w, h)
        assert app.screen.query_one("#upgrade", Button).region.height >= 1
        app.start_upgrade(demo_packages()[:3])
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await until(lambda: app.runner.view.stage is Stage.DOWNLOADING)
        await pilot.pause()
        assert_buttons_inside(app, w, h)
        for action, kind in ((app.action_show_logs, LogsScreen), (app.action_show_settings, SettingsScreen)):
            action()
            await pilot.pause()
            assert isinstance(app.screen, kind)
            assert_buttons_inside(app, w, h)
            app.pop_screen()
            await pilot.pause()
        await app.runner.shutdown()


@pytest.mark.parametrize("w,h", SIZES)
async def test_key_buttons_stay_reachable(make_app, w, h):
    app = make_app(FakeBackend(demo_packages(), speed=2))
    asked(app)
    async with app.run_test(size=(w, h)) as pilot:
        await pilot.pause()
        app.start_upgrade(demo_packages()[:2])
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await until(lambda: app.runner.view.stage is Stage.DOWNLOADING)
        await pilot.pause()
        for name in ("#pause", "#stop", "#back"):
            button = app.screen.query_one(name, Button)
            assert button.display and button.region.height >= 1 and button.region.bottom <= h
            assert button.region.right <= w, name
        await app.runner.shutdown()


def test_bands():
    assert [layout_band(w) for w in (160, 120, 119, 80, 79, 50)] == [
        "wide", "wide", "medium", "medium", "narrow", "narrow",
    ]


async def test_columns_per_band(make_app):
    app = make_app()
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        app.show_packages(None)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        table = app.screen.query_one(PackageTable)
        keys = lambda: [c.key for c in columns(table.size.width, table.all_rows)]
        assert keys() == ["tick", "name", "id", "installed", "available", "source", "change"]
        await pilot.resize_terminal(100, 30)
        await pilot.pause(0.1)
        assert keys() == ["tick", "name", "installed", "available", "source", "change"]
        await pilot.resize_terminal(70, 24)
        await pilot.pause(0.1)
        assert keys() == ["tick", "name", "versions"]


async def test_progress_narrow_uses_log_queue_tabs(make_app):
    app = make_app(FakeBackend([], speed=2))
    asked(app)
    async with app.run_test(size=(70, 30)) as pilot:
        await pilot.pause()
        app.start_upgrade(demo_packages()[:2])
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#run-tabs").display
        assert screen.query_one("#log-box").display and not screen.query_one("#queue-box").display
        await pilot.click("#tab-queue")
        await pilot.pause()
        assert screen.query_one("#queue-box").display and not screen.query_one("#log-box").display
        await pilot.resize_terminal(130, 40)
        await pilot.pause(0.1)
        assert not screen.query_one("#run-tabs").display
        assert screen.query_one("#queue-box").display and screen.query_one("#log-box").display
        await app.runner.shutdown()


async def test_progress_medium_hides_the_icon(make_app):
    app = make_app(FakeBackend([], speed=2))
    asked(app)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        app.start_upgrade(demo_packages()[:1])
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await pilot.pause()
        assert not app.screen.query_one("#run-icon").display
        await pilot.resize_terminal(130, 40)
        await pilot.pause(0.1)
        assert app.screen.query_one("#run-icon").display
        await app.runner.shutdown()


async def test_too_small_message_below_50x16_and_work_continues(make_app):
    backend = FakeBackend([], speed=4)
    app = make_app(backend)
    asked(app)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.start_upgrade([pkg("A")])
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await pilot.resize_terminal(MIN_WIDTH - 1, MIN_HEIGHT - 1)
        await pilot.pause(0.1)
        banner = app.screen.query_one("#too-small")
        assert banner.display and "too small" in str(banner.render()).lower()
        await until(lambda: app.runner.view.state is RunState.FINISHED, 12)
        await pilot.resize_terminal(120, 40)
        await pilot.pause(0.1)
        assert not app.screen.query_one("#too-small").display


async def test_too_small_applies_to_a_screen_opened_while_small(make_app):
    app = make_app()
    async with app.run_test(size=(40, 10)) as pilot:
        await pilot.pause()
        assert app.screen.query_one("#too-small").display
        assert not app.screen.show_vertical_scrollbar and not app.screen.show_horizontal_scrollbar


async def test_resize_during_run_keeps_ticks_scroll_and_progress(make_app):
    many = [pkg(f"P{n:02}") for n in range(40)]
    app = make_app(FakeBackend(many, speed=2))
    asked(app)
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        app.show_packages(None)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        table = screen.query_one(PackageTable)
        table.focus()
        await pilot.press("space", "pagedown", "pagedown", "pagedown")
        await pilot.pause()
        ticked, cursor = set(table.ticked), table.cursor
        top = table.scroll_offset.y
        assert top > 0
        await pilot.resize_terminal(70, 20)
        await pilot.pause(0.1)
        await pilot.resize_terminal(120, 24)
        await pilot.pause(0.1)
        assert table.ticked == ticked and table.cursor == cursor and table.scroll_offset.y == top
        app.start_upgrade([many[0]])
        await until(lambda: app.runner.view.progress is not None)
        await pilot.resize_terminal(90, 20)
        await pilot.pause(0.1)
        assert app.runner.view.state is RunState.RUNNING
        await pilot.resize_terminal(50, 16)
        await pilot.pause(0.1)
        assert app.runner.view.state is RunState.RUNNING
        await app.runner.shutdown()


async def test_logo_shrinks_then_hides_on_short_windows(make_app):
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        logo = app.screen.query_one("#logo")
        tall = logo.region.height
        assert logo.display and tall > 8
        await pilot.resize_terminal(120, 24)
        await pilot.pause(0.1)
        assert logo.display and logo.region.height < tall
        await pilot.resize_terminal(120, 16)
        await pilot.pause(0.1)
        assert not logo.display


async def test_table_log_collapses_before_the_table(make_app):
    app = make_app()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.show_packages(None)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#table-log-box").display
        await pilot.resize_terminal(120, 16)
        await pilot.pause(0.1)
        assert not screen.query_one("#table-log-box").display
        assert screen.query_one(PackageTable).region.height >= 3


async def test_window_title_follows_the_run(make_app):
    app = make_app(FakeBackend([], speed=4))
    asked(app)
    written = []
    async with app.run_test(size=(120, 40)) as pilot:
        app.write_terminal = written.append
        await pilot.pause()
        app.start_upgrade([pkg("A"), pkg("B")])
        await until(lambda: app.runner.view.progress is not None)
        await pilot.pause()
        assert any("· WingetDeck" in text for text in written)
        await app.runner.shutdown()


def test_title_text():
    assert title_text(view(done=2, total=7, percent=42)) == "3/7 · 42% · WingetDeck"


def test_title_paused_has_no_fake_percent():
    assert title_text(view(state=RunState.PAUSED)) == "3/7 · Paused · WingetDeck"


def test_title_without_a_number_has_no_percent():
    assert title_text(view(percent=None)) == "3/7 · WingetDeck"


def test_title_when_finished_and_idle():
    assert title_text(view(done=7, state=RunState.FINISHED)) == "Done · WingetDeck"
    assert title_text(None) == "WingetDeck"
    assert title_text(RunView()) == "WingetDeck"


def test_taskbar_code_with_a_number():
    assert taskbar_code(view(percent=42)) == "\x1b]9;4;1;42\x1b\\"


def test_taskbar_code_with_no_number_is_the_busy_state_not_a_percent():
    assert taskbar_code(view(percent=None)) == "\x1b]9;4;3;0\x1b\\"


def test_taskbar_code_paused_and_finished():
    assert taskbar_code(view(state=RunState.PAUSED)) == "\x1b]9;4;4;42\x1b\\"
    assert taskbar_code(view(state=RunState.FINISHED)) == "\x1b]9;4;0;0\x1b\\"
    assert taskbar_code(None) == "\x1b]9;4;0;0\x1b\\"


async def test_a_screen_coming_back_fits_a_window_resized_while_it_was_away(make_app):
    from wingetdeck.ui.screens.packages import PackagesScreen

    app = make_app(FakeBackend(demo_packages(), speed=2))
    asked(app)
    async with app.run_test(size=(130, 40)) as pilot:
        await pilot.pause()
        app.show_packages(None)
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.start_upgrade(demo_packages()[:2])
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await until(lambda: app.runner.view.stage is Stage.DOWNLOADING)
        await pilot.pause()
        progress = app.screen
        assert progress.query_one("#run-icon").display
        await pilot.click("#back")
        await until(lambda: isinstance(app.screen, PackagesScreen))
        await pilot.resize_terminal(70, 24)
        await pilot.pause(0.1)
        app.show_progress()
        await until(lambda: app.screen is progress)
        await pilot.pause(0.1)
        assert progress.has_class("-narrow") and not progress.has_class("-wide")
        assert progress.query_one("#run-tabs").display
        assert not progress.query_one("#run-icon").display
        await pilot.click("#back")
        await until(lambda: isinstance(app.screen, PackagesScreen))
        await pilot.resize_terminal(40, 10)
        await pilot.pause(0.1)
        app.show_progress()
        await until(lambda: app.screen is progress)
        await pilot.pause(0.1)
        assert progress.query_one("#too-small").display
        await app.runner.shutdown()
