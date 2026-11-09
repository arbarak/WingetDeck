"""Choosing the language in Settings, and every screen following it."""

import asyncio
from dataclasses import replace

import pytest
from rich.cells import cell_len
from textual.widgets import Button, Input, Select, Static
from textual.widgets._footer import FooterKey

from wingetdeck import i18n
from wingetdeck.core.queue import RunState
from wingetdeck.locales.fr import FR
from wingetdeck.ui.screens.dialogs import ConfirmDialog
from wingetdeck.ui.screens.packages import PackagesScreen
from wingetdeck.ui.screens.progress import ProgressScreen
from wingetdeck.ui.screens.settings import SettingsScreen
from wingetdeck.ui.screens.splash import SplashScreen
from wingetdeck.ui.symbols import to_ascii
from wingetdeck.winget.fake import FakeBackend, demo_packages
from wingetdeck.winget.models import Stage

SIZE = (100, 40)


async def until(check, seconds=8.0):
    async def poll():
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), seconds)


async def settle(app, pilot):
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def asked(app, language=""):
    """As if it had been saved before this start: the app reads it when it opens."""
    app.store.save_settings(replace(app.store.load_settings(), asked_agreements=True, language=language))
    app.apply_language(language)


def footer_words(screen):
    return {key.description for key in screen.query(FooterKey)}


async def choose(app, pilot, value):
    app.screen.query_one("#language", Select).value = value
    await pilot.pause()
    await until(lambda: isinstance(app.screen, SettingsScreen) and app.screen.language == i18n.current())
    await pilot.pause()


async def test_choosing_french_redraws_settings_at_once_and_saves_it(make_app):
    app = make_app()
    asked(app)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.action_show_settings()
        await pilot.pause()
        assert str(app.screen.query_one("#save-settings", Button).label) == "Save"
        await choose(app, pilot, "fr")
        assert str(app.screen.query_one("#save-settings", Button).label) == "Enregistrer"
        assert "Langue changée" in str(app.screen.query_one("#settings-note", Static).render())
        assert app.store.load_settings().language == "fr"
        assert "Retour" in footer_words(app.screen)
        assert app.screen.query_one("#language", Select).has_focus


async def test_back_in_english_from_french(make_app):
    app = make_app()
    asked(app, "fr")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.action_show_settings()
        await pilot.pause()
        assert str(app.screen.query_one("#save-settings", Button).label) == "Enregistrer"
        await choose(app, pilot, "en")
        assert str(app.screen.query_one("#save-settings", Button).label) == "Save"
        assert app.store.load_settings().language == "en"


async def test_unsaved_changes_on_the_page_survive_the_switch(make_app):
    app = make_app()
    asked(app)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.action_show_settings()
        await pilot.pause()
        app.screen.query_one("#stall-minutes", Input).value = "25"
        await choose(app, pilot, "fr")
        assert app.screen.query_one("#stall-minutes", Input).value == "25"
        assert app.store.load_settings().stall_minutes == 10  # not saved until Save, as before


async def test_the_screen_underneath_comes_back_in_french(make_app):
    app = make_app(FakeBackend(demo_packages(), speed=50))
    asked(app)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.show_packages(None)
        await settle(app, pilot)
        assert str(app.screen.query_one("#upgrade", Button).label) == "UPGRADE"
        app.action_show_settings()
        await pilot.pause()
        await choose(app, pilot, "fr")
        await pilot.press("escape")
        await until(lambda: isinstance(app.screen, PackagesScreen) and app.screen.language == "fr")
        await settle(app, pilot)
        assert str(app.screen.query_one("#upgrade", Button).label) == "METTRE À JOUR"
        assert "Actualiser" in footer_words(app.screen)
        assert app.screen.source is None
        await pilot.press("escape")
        await until(lambda: isinstance(app.screen, SplashScreen) and app.screen.language == "fr")
        await settle(app, pilot)
        assert str(app.screen.query_one("#start", Button).label) == "DÉMARRER"


async def test_picking_the_same_language_changes_nothing(make_app):
    app = make_app()
    asked(app, "en")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.action_show_settings()
        await pilot.pause()
        screen = app.screen
        app.screen.query_one("#language", Select).value = "en"
        await pilot.pause()
        assert app.screen is screen


async def test_automatic_follows_the_language_windows_shows(make_app):
    app = make_app(system_language=lambda: "fr-FR")
    asked(app)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert i18n.current() == "fr"
        assert str(app.screen.query_one("#prompt", Static).render()) == FR["Select a source and press START"]
        app.action_show_settings()
        await pilot.pause()
        select = app.screen.query_one("#language", Select)
        assert select.value == ""
        assert "Automatique (Français)" in [str(prompt) for prompt, _ in select._options]


async def test_a_chosen_language_wins_over_windows(make_app):
    app = make_app(system_language=lambda: "fr-FR")
    asked(app, "en")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        assert str(app.screen.query_one("#prompt", Static).render()) == "Select a source and press START"


async def test_the_label_names_the_setting_in_english_too(make_app):
    """Someone who cannot read the current language can still find the way back."""
    app = make_app()
    asked(app, "fr")
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.action_show_settings()
        await pilot.pause()
        labels = [str(label.render()) for label in app.screen.query(".form-label")]
        assert "Langue (Language)" in labels


async def test_a_dialog_shows_french_and_answers_with_the_english_choice(make_app):
    app = make_app()
    asked(app, "fr")
    answers = []
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.push_screen(ConfirmDialog("Roll back?", "The packages still waiting will not be upgraded.", ("Roll back",)), answers.append)
        await pilot.pause()
        assert str(app.screen.query_one("#dialog-title", Static).render()) == FR["Roll back?"]
        assert str(app.screen.query_one("#choice-0", Button).label) == FR["Roll back"]
        assert str(app.screen.query_one("#cancel", Button).label) == "Annuler"
        await pilot.click("#choice-0")
        await pilot.pause()
    assert answers == ["Roll back"]


async def test_the_run_screen_keeps_working_when_the_language_changes_during_a_run(make_app):
    app = make_app(FakeBackend(demo_packages(), speed=2))
    asked(app)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.start_upgrade(demo_packages()[:2])
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await until(lambda: app.runner.view.stage is Stage.DOWNLOADING)
        running = app.screen
        app.action_show_settings()
        await pilot.pause()
        await choose(app, pilot, "fr")
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is running  # not swapped mid-run
        await pilot.press("p")
        await until(lambda: app.runner.view.state is RunState.PAUSED or "Pause" in str(running.query_one("#pause", Button).label))
        assert app.runner.view.state in (RunState.RUNNING, RunState.PAUSED)
        await app.runner.shutdown()


async def test_the_run_screen_is_drawn_afresh_for_the_next_run(make_app):
    app = make_app(FakeBackend(demo_packages(), speed=500))
    asked(app)
    async with app.run_test(size=SIZE) as pilot:
        await settle(app, pilot)
        app.start_upgrade(demo_packages()[:1])
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        await pilot.pause()
        first = app.progress_screen()
        await pilot.press("b")
        await pilot.pause()
        app.action_show_settings()
        await pilot.pause()
        await choose(app, pilot, "fr")
        await pilot.press("escape")
        await pilot.pause()
        app.show_progress()
        await pilot.pause()
        assert app.screen is not first and isinstance(app.screen, ProgressScreen)
        assert str(app.screen.query_one("#chip", Static).render()) == "TERMINÉ"


async def test_a_long_french_label_still_fits_the_upgrade_button_at_the_smallest_size(make_app):
    app = make_app()
    asked(app, "fr")
    async with app.run_test(size=(50, 16)) as pilot:
        await settle(app, pilot)
        app.show_packages(None)
        await settle(app, pilot)
        button = app.screen.query_one("#upgrade", Button)
        assert button.region.right <= 50


@pytest.mark.parametrize("language", ["en", "fr"])
@pytest.mark.parametrize("width", [80, 100, 120])
async def test_package_buttons_show_their_whole_label(make_app, language, width):
    app = make_app()
    asked(app, language)
    async with app.run_test(size=(width, 24)) as pilot:
        await settle(app, pilot)
        app.show_packages(None)
        await settle(app, pilot)
        await pilot.press("a")  # UPGRADE gets a count, its longest label
        await pilot.pause()
        lines = [strip.text for strip in app.screen._compositor.render_strips()]
        for button in app.screen.query("#table-actions Button").results(Button):
            if not button.display:
                continue
            region = button.region
            assert region.right <= width, (button.id, region)
            drawn = lines[region.y + 1][region.x : region.right]
            assert str(button.label) in drawn, (button.id, str(button.label), drawn)


def test_french_in_plain_ascii_keeps_every_column():
    for text in FR.values():
        plain = to_ascii(text)
        assert plain.isascii(), text
        assert cell_len(plain) == cell_len(text), text
