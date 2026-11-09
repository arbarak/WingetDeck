from textual.widgets import Button, ListItem, Static

from wingetdeck.paths import DataDir
from wingetdeck.ui.pixels import LOGO, PixelArt, PALETTE
from wingetdeck.ui.screens.no_winget import NoWingetScreen
from wingetdeck.ui.screens.packages import PackagesScreen
from wingetdeck.ui.screens.splash import SplashScreen
from wingetdeck.ui.themes import DEFAULT_THEME, THEMES
from wingetdeck.winget.fake import FakeBackend, demo_packages
from wingetdeck.winget.real import WingetError


def text_of(widget):
    return str(widget.render())


def source_labels(app):
    return [text_of(i.query_one(Static)) for i in app.screen.query("#sources ListItem")]


async def test_splash_lists_sources_from_backend(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SplashScreen)
        assert source_labels(app) == ["All sources", "Microsoft Store only", "winget only"]


async def test_click_start_opens_packages_with_chosen_source(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        items = list(app.screen.query("#sources ListItem").results(ListItem))
        await pilot.click(items[2])
        await pilot.click("#start")
        await pilot.pause()
        assert isinstance(app.screen, PackagesScreen) and app.screen.source == "winget"


async def test_clicking_a_source_does_not_start_by_itself(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click(list(app.screen.query("#sources ListItem").results(ListItem))[1])
        await pilot.pause()
        assert isinstance(app.screen, SplashScreen)


async def test_default_source_is_all(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#start")
        await pilot.pause()
        assert app.screen.source is None


async def test_enter_key_starts(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("down", "enter")
        await pilot.pause()
        assert isinstance(app.screen, PackagesScreen) and app.screen.source == "msstore"


async def test_shows_winget_and_windows_versions(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        line = text_of(app.screen.query_one("#versions"))
        assert "v0.0.0-demo" in line and "Windows" in line


async def test_missing_winget_shows_help_not_crash(make_app):
    class NoWinget(FakeBackend):
        def capabilities(self):
            return None

    app = make_app(NoWinget([]))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, NoWingetScreen)
        assert "App Installer" in text_of(app.screen.query_one("#help"))


async def test_check_again_continues_once_winget_appears(make_app):
    class Appears(FakeBackend):
        present = False

        def capabilities(self):
            return super().capabilities() if self.present else None

    backend = Appears(demo_packages(), speed=200)
    app = make_app(backend)
    async with app.run_test() as pilot:
        await pilot.pause()
        backend.present = True
        await pilot.click("#check-again")
        await pilot.pause()
        assert isinstance(app.screen, SplashScreen)
        assert "v0.0.0-demo" in text_of(app.screen.query_one("#versions"))


async def test_broken_source_list_still_offers_all_sources(make_app):
    class NoSources(FakeBackend):
        async def sources(self):
            raise WingetError("source list failed")

    app = make_app(NoSources(demo_packages()))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert source_labels(app) == ["All sources"]
        assert "source list failed" in text_of(app.screen.query_one("#notes"))
        assert any("source list failed" in str(e.fields) for e in app.log_file.events("ERROR"))


async def test_data_folder_shown_when_fallback_in_use(make_app, tmp_path):
    data = DataDir(tmp_path / "profile", portable=False)
    app = make_app(data=data)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "profile" in text_of(app.screen.query_one("#notes"))


async def test_data_folder_not_mentioned_when_portable(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "Data folder" not in text_of(app.screen.query_one("#notes"))


async def test_default_theme_is_green_and_others_exist(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == DEFAULT_THEME == "wingetdeck-green"
        assert len(THEMES) >= 2


async def test_unknown_saved_theme_falls_back(make_app, tmp_data):
    from dataclasses import replace

    app = make_app()
    app.store.save_settings(replace(app.store.load_settings(), theme="gone"))
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.theme == DEFAULT_THEME


async def test_quit_button_exits(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.click("#quit")
        await pilot.pause()
    assert app.return_code == 0


async def test_start_button_is_clickable_at_small_size(make_app):
    app = make_app()
    async with app.run_test(size=(50, 16)) as pilot:
        await pilot.pause()
        assert app.screen.query_one("#start", Button).region.height >= 3


def test_logo_is_original_box_and_arrow_in_half_blocks():
    lines = PixelArt(LOGO, PALETTE).to_plain()
    assert any("▀" in line or "▄" in line for line in lines)
    assert len(lines) == (len(LOGO) + 1) // 2


def test_pixel_art_ascii_mode_has_only_ascii():
    lines = PixelArt(LOGO, PALETTE, ascii_mode=True).to_plain()
    assert all(line.isascii() for line in lines) and any("#" in line for line in lines)
