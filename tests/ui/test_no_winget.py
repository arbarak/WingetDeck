"""The help screen on a PC without a usable winget: it asks first, and only then activates, finds or installs."""

import asyncio
import re
import threading

import pytest
from textual.widgets import Button

from wingetdeck.ui.screens.dialogs import ConfirmDialog
from wingetdeck.ui.screens.no_winget import NoWingetScreen
from wingetdeck.ui.screens.splash import SplashScreen
from wingetdeck.winget.fake import FakeBackend
from wingetdeck.winget.repair import Asset, Offer, RepairCancelled, RepairError

OFFER = Offer(
    "v1.29.380",
    Asset("bundle", "u", 200 * 1024 * 1024, "a"),
    Asset("deps", "u", 100 * 1024 * 1024, "b"),
    17763,
)


class Missing(FakeBackend):
    """No winget until `present` is set."""

    present = False

    def capabilities(self):
        return super().capabilities() if self.present else None


class Repair:
    def __init__(self, backend, activate_works=False, version=None, offer=OFFER, find_error=None, install_error=None):
        self.backend = backend
        self.activate_works = activate_works
        self.version = version
        self.offer = offer
        self.find_error = find_error
        self.install_error = install_error
        self.calls = []
        self.hold = None
        self.message = "Downloading winget: 45% of 300 MB"

    def activate(self):
        self.calls.append("activate")
        if not self.activate_works:
            raise RepairError("not registered")
        self.backend.present = True

    def app_installer_version(self):
        self.calls.append("version")
        return self.version

    def find_offer(self, build, architecture):
        self.calls.append("find")
        if self.find_error:
            raise self.find_error
        return self.offer

    def download_and_install(self, offer, architecture, progress, cancel):
        self.calls.append("install")
        progress(self.message)
        if self.hold:
            self.hold.wait(5)
            if cancel.is_set():
                raise RepairCancelled
        if self.install_error:
            raise self.install_error
        self.backend.present = True


async def until(condition, pilot, tries=200):
    for _ in range(tries):
        if condition():
            return True
        await pilot.pause(0.02)
    return False


async def opened(app, pilot):
    await pilot.pause()
    assert await until(lambda: isinstance(app.screen, NoWingetScreen), pilot)
    return app.screen


def note(screen):
    return str(screen.query_one("#repair-note").render())


async def answer(app, pilot, label=None):
    """Press a dialog button, or None to cancel. Waits for that button: the last dialog may still be closing."""

    def ready():
        dialog = app.screen
        if not isinstance(dialog, ConfirmDialog) or not dialog.is_current:
            return False
        if label is None:
            return bool(dialog.query("#cancel"))
        return label in dialog.choices and bool(dialog.query(f"#choice-{dialog.choices.index(label)}"))

    assert await until(ready, pilot), f"no question offering {label!r} was asked"
    dialog = app.screen
    if label is None:
        dialog.query_one("#cancel", Button).press()
    else:
        index = dialog.choices.index(label)
        dialog.query_one(f"#choice-{index}", Button).press()
    await pilot.pause()
    return dialog


async def reached_the_start_screen(app, pilot):
    """Waits for the screen to finish opening, because closing the app halfway through is not what is being tested."""
    assert await until(lambda: isinstance(app.screen, SplashScreen) and app.screen.query("#start"), pilot)
    await app.workers.wait_for_complete()
    await pilot.pause()


async def offered(app, pilot):
    def ready():
        dialog = app.screen
        return isinstance(dialog, ConfirmDialog) and "Install winget" in dialog.dialog_title and dialog.query("#cancel")

    assert await until(ready, pilot), "the offer was not shown"
    return app.screen


async def get_winget(app, pilot, screen):
    screen.query_one("#get-winget", Button).press()
    await pilot.pause()


def setup(make_app, **kw):
    backend = Missing([])
    repair = Repair(backend, **kw)
    return make_app(backend, repair=repair), repair


async def test_nothing_happens_until_the_button_is_pressed(make_app):
    app, repair = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        await opened(app, pilot)
        await pilot.pause(0.1)
        assert repair.calls == []


async def test_the_help_screen_fits_a_small_window_with_every_button_showing(make_app):
    app, _ = setup(make_app)
    async with app.run_test(size=(80, 24)) as pilot:
        screen = await opened(app, pilot)
        for name in ("get-winget", "store", "check-again", "quit"):
            region = screen.query_one(f"#{name}", Button).region
            assert region.width and region.right <= 80 and region.bottom <= 24, name


def shown(app):
    """Every line as it is really drawn, so text cut off at the edge of the window counts as missing."""
    width, height = app.size
    lines = []
    for y in range(height):
        strip = app.screen._compositor.render_strips()[y]
        lines.append(strip.text)
    return re.sub(r"\s+", " ", " ".join(lines))


@pytest.mark.parametrize("size", [(80, 24), (70, 30), (120, 30)])
async def test_the_help_text_is_never_cut_off(make_app, size):
    app, _ = setup(make_app)
    async with app.run_test(size=size) as pilot:
        await opened(app, pilot)
        assert await until(lambda: app.screen.query("#help"), pilot)
        await pilot.pause(0.05)
        text = shown(app)
        for words in ("could not be used here", "then offers", "cannot run on Server Core"):
            assert words in text, f"{words!r} is missing at {size}"


async def test_a_long_message_wraps_and_the_buttons_stay_on_screen_in_a_small_window(make_app):
    app, _ = setup(make_app, version="1.29.380.0")
    async with app.run_test(size=(80, 24)) as pilot:
        await opened(app, pilot)
        app.show_no_winget("Winget stopped answering after 60 seconds while WingetDeck was asking for its version.")
        await pilot.pause()
        assert await until(lambda: app.screen.query("#get-winget"), pilot)
        screen = app.screen
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        assert await until(lambda: "App execution aliases" in note(screen), pilot)
        await pilot.pause(0.05)
        assert "App execution aliases" in shown(app) and "press Check again" in shown(app)
        for name in ("get-winget", "store", "check-again", "quit"):
            region = screen.query_one(f"#{name}", Button).region
            assert region.right <= 80 and region.bottom <= 24, name


async def test_a_very_long_error_cannot_put_the_buttons_out_of_reach(make_app):
    app, _ = setup(make_app)
    async with app.run_test(size=(80, 24)) as pilot:
        await opened(app, pilot)
        app.show_no_winget("Windows said: " + "this went wrong and that went wrong too. " * 40)
        await pilot.pause()
        assert await until(lambda: app.screen.query("#get-winget"), pilot)
        screen = app.screen
        assert app.focused is not None and app.focused.id == "get-winget"
        for name in ("get-winget", "store", "check-again", "quit"):
            await pilot.pause(0.05)
            assert app.focused.id == name
            assert 0 <= app.focused.region.y and app.focused.region.bottom <= 24, name
            await pilot.press("tab")
        assert screen.query_one("#no-winget-body").max_scroll_y > 0


async def test_enter_during_a_download_cancels_rather_than_quits(make_app):
    app, repair = setup(make_app)
    repair.hold = threading.Event()
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        await offered(app, pilot)
        await answer(app, pilot, "Download and install")
        assert await until(lambda: "45%" in note(screen), pilot)
        assert await until(lambda: app.focused is not None and app.focused.id == "cancel-get", pilot), app.focused
        repair.hold.set()


async def test_quit_cannot_be_pressed_while_windows_is_installing(make_app):
    app, repair = setup(make_app)
    repair.hold = threading.Event()
    repair.message = "Installing winget. This can take a few minutes."
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        await offered(app, pilot)
        await answer(app, pilot, "Download and install")
        assert await until(lambda: "Installing" in note(screen), pilot)
        assert await until(lambda: screen.query_one("#quit", Button).disabled, pilot)
        assert not screen.query_one("#cancel-get", Button).display
        assert app.focused is None or app.focused.id != "quit"
        repair.install_error = RepairError("Windows refused it")
        repair.hold.set()
        assert await until(lambda: "Windows refused it" in note(screen), pilot)
        assert await until(lambda: not screen.query_one("#quit", Button).disabled, pilot)


async def test_after_a_failure_the_focus_is_back_on_get_winget_not_quit(make_app):
    app, _ = setup(make_app, install_error=RepairError("Windows refused it"))
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        await offered(app, pilot)
        await answer(app, pilot, "Download and install")
        assert await until(lambda: "Windows refused it" in note(screen), pilot)
        assert await until(lambda: app.focused is not None and app.focused.id == "get-winget", pilot), app.focused


async def test_activating_asks_first_and_declining_does_nothing(make_app):
    app, repair = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, None)
        assert await until(lambda: not screen.query_one("#get-winget", Button).disabled, pilot)
        assert repair.calls == []
        assert isinstance(app.screen, NoWingetScreen)


async def test_activation_that_works_needs_no_download(make_app):
    app, repair = setup(make_app, activate_works=True)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        dialog = await answer(app, pilot, "Activate winget")
        assert "Nothing is downloaded" in dialog.text
        await reached_the_start_screen(app, pilot)
        assert repair.calls == ["activate"]


async def test_when_activation_fails_a_compatible_version_is_found_and_offered(make_app):
    app, repair = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        dialog = await offered(app, pilot)
        assert "v1.29.380" in dialog.dialog_title
        assert "300 MB" in dialog.text and "Microsoft" in dialog.text and "signature" in dialog.text
        assert "install" not in repair.calls, "the download must wait for an answer"


async def test_enter_alone_on_the_offer_starts_nothing(make_app):
    """A second press of Enter, meant for Get winget, must not count as agreeing to a 300 MB download."""
    app, repair = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        dialog = await offered(app, pilot)
        await pilot.pause(0.05)
        await pilot.press("enter")
        await pilot.pause(0.05)
        assert app.screen is dialog
        assert "install" not in repair.calls


async def test_escape_declines_the_offer(make_app):
    app, repair = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        await offered(app, pilot)
        await pilot.pause(0.05)
        await pilot.press("escape")
        assert await until(lambda: not screen.query_one("#get-winget", Button).disabled, pilot)
        assert "install" not in repair.calls


async def test_declining_the_offer_downloads_nothing(make_app):
    app, repair = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        await offered(app, pilot)
        await answer(app, pilot, None)
        assert await until(lambda: not screen.query_one("#get-winget", Button).disabled, pilot)
        assert "install" not in repair.calls
        assert isinstance(app.screen, NoWingetScreen)
        assert await until(lambda: not screen.query_one("#get-winget", Button).disabled, pilot)


async def test_accepting_the_offer_installs_and_carries_on_into_the_app(make_app):
    app, repair = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        await offered(app, pilot)
        await answer(app, pilot, "Download and install")
        await reached_the_start_screen(app, pilot)
        assert "install" in repair.calls


async def test_winget_that_is_too_old_skips_activating(make_app):
    app, repair = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        await opened(app, pilot)
        app.show_no_winget("This PC has winget v1.2. WingetDeck needs 1.4 or newer.", too_old=True)
        await pilot.pause()
        assert await until(lambda: app.screen.query("#get-winget"), pilot)
        await get_winget(app, pilot, app.screen)
        await offered(app, pilot)
        assert "activate" not in repair.calls


async def test_app_installer_present_with_its_command_off_says_how_to_turn_it_on(make_app):
    app, repair = setup(make_app, version="1.29.380.0")
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        assert await until(lambda: "App execution aliases" in note(screen), pilot)
        assert "find" not in repair.calls, "downloading again would not help"


async def test_no_compatible_version_points_to_the_store(make_app):
    app, _ = setup(make_app, offer=None)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        assert await until(lambda: "No version" in note(screen), pilot)
        assert "Microsoft Store" in note(screen)
        assert await until(lambda: not screen.query_one("#get-winget", Button).disabled, pilot)


async def test_no_internet_is_said_and_the_screen_stays_usable(make_app):
    app, _ = setup(make_app, find_error=RepairError("Could not reach GitHub: no route to host"))
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        assert await until(lambda: "Could not reach GitHub" in note(screen), pilot)
        assert await until(lambda: not screen.query_one("#get-winget", Button).disabled, pilot)


async def test_a_failed_install_is_said_and_the_screen_stays_usable(make_app):
    app, _ = setup(make_app, install_error=RepairError("Windows refused it"))
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        await offered(app, pilot)
        await answer(app, pilot, "Download and install")
        assert await until(lambda: "Windows refused it" in note(screen), pilot)
        assert isinstance(app.screen, NoWingetScreen)
        assert await until(lambda: not screen.query_one("#get-winget", Button).disabled, pilot)


async def test_progress_shows_and_cancel_stops_it(make_app):
    app, repair = setup(make_app)
    repair.hold = threading.Event()
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        await offered(app, pilot)
        await answer(app, pilot, "Download and install")
        assert await until(lambda: "45%" in note(screen), pilot)
        assert screen.query_one("#get-winget", Button).disabled
        cancel = screen.query_one("#cancel-get", Button)
        assert cancel.display
        cancel.press()
        await pilot.pause()
        repair.hold.set()
        assert await until(lambda: "Cancelled" in note(screen), pilot)
        assert await until(lambda: not screen.query_one("#get-winget", Button).disabled, pilot)
        assert not screen.query_one("#cancel-get", Button).display
        assert not app.backend.present


async def test_leaving_the_screen_cancels_a_download(make_app):
    app, repair = setup(make_app)
    repair.hold = threading.Event()
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        await get_winget(app, pilot, screen)
        await answer(app, pilot, "Activate winget")
        await offered(app, pilot)
        await answer(app, pilot, "Download and install")
        await until(lambda: "45%" in note(screen), pilot)
        cancel = screen._cancel
        assert not cancel.is_set()
        app.check_winget_again()
        assert await until(cancel.is_set, pilot), "the download must not carry on behind another screen"
        repair.hold.set()
        await asyncio.sleep(0.05)


async def test_the_store_button_opens_app_installers_page(make_app, monkeypatch):
    opened_links = []
    monkeypatch.setattr("wingetdeck.ui.screens.no_winget.open_store", lambda: opened_links.append(True))
    app, repair = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        screen.query_one("#store", Button).press()
        await pilot.pause()
        assert opened_links == [True]
        assert repair.calls == []


async def test_a_pc_without_the_store_says_so(make_app, monkeypatch):
    def no_store():
        raise RepairError("The Microsoft Store could not be opened on this PC.")

    monkeypatch.setattr("wingetdeck.ui.screens.no_winget.open_store", no_store)
    app, _ = setup(make_app)
    async with app.run_test(size=(120, 36)) as pilot:
        screen = await opened(app, pilot)
        screen.query_one("#store", Button).press()
        await pilot.pause()
        assert "could not be opened" in note(screen)
