"""Faults found by running the app on another PC, seen from the screens."""

import asyncio
from dataclasses import replace

from wingetdeck.core.queue import STOP_NOW
from wingetdeck.ui.screens.progress import ProgressScreen
from wingetdeck.winget.fake import FakeBackend, demo_packages
from wingetdeck.winget.fake import FakeBackend
from wingetdeck.winget.models import Stage


def agreed(app):
    app.store.save_settings(replace(app.store.load_settings(), asked_agreements=True, consented_agreements=True))


async def until(condition, pilot, tries=300):
    for _ in range(tries):
        if condition():
            return True
        await pilot.pause(0.02)
    return False


async def test_pressing_upgrade_again_while_it_is_starting_changes_nothing(make_app):
    """The list of installed apps took 9 seconds on the tester's PC with nothing on screen, so they pressed again."""
    backend = FakeBackend(demo_packages(), speed=200)
    backend.export_seconds = 0.2
    app = make_app(backend)
    async with app.run_test(size=(120, 36)) as pilot:
        agreed(app)
        package = demo_packages()[0]
        app.start_upgrade([package])
        await pilot.pause(0.02)
        app.start_upgrade([package])
        await pilot.pause(0.02)
        assert await until(lambda: isinstance(app.screen, ProgressScreen), pilot)
        assert backend.calls.count("export_snapshot") == 1
        await app.runner.wait()


async def test_something_on_screen_says_why_the_start_takes_a_moment(make_app):
    backend = FakeBackend(demo_packages(), speed=200)
    backend.export_seconds = 0.2
    app = make_app(backend)
    async with app.run_test(size=(120, 36)) as pilot:
        agreed(app)
        app.start_upgrade([demo_packages()[0]])
        assert await until(lambda: any("list of installed apps" in n.message for n in app._notifications), pilot, 25)
        assert await until(lambda: isinstance(app.screen, ProgressScreen), pilot)
        await app.runner.wait()


async def test_upgrade_works_again_after_a_start_that_was_declined(make_app):
    backend = FakeBackend(demo_packages(), speed=200)
    app = make_app(backend)
    async with app.run_test(size=(120, 36)) as pilot:
        agreed(app)
        package = demo_packages()[0]
        app.start_upgrade([package])
        assert await until(lambda: isinstance(app.screen, ProgressScreen), pilot)
        await app.runner.wait()
        await pilot.pause(0.05)
        app.start_upgrade([package])
        assert await until(lambda: backend.calls.count("export_snapshot") == 2, pilot)
        await asyncio.sleep(0.05)
        await app.runner.wait()


async def test_stop_now_never_ends_an_installer_even_if_the_stage_looks_like_a_download(make_app):
    """A translation that changed in a new winget would leave the stage at Downloading while an installer runs."""
    backend = FakeBackend(demo_packages(), speed=5)
    backend.installer_started = True
    app = make_app(backend)
    async with app.run_test(size=(120, 36)) as pilot:
        agreed(app)
        app.start_upgrade([demo_packages()[0]])
        assert await until(lambda: isinstance(app.screen, ProgressScreen), pilot)
        runner = app.runner
        assert await until(lambda: runner.view.stage is Stage.DOWNLOADING, pilot)
        assert STOP_NOW in runner.view.controls.stop_choices
        assert runner.stop_now() is None
        assert runner.view.stage is Stage.INSTALLING
        assert STOP_NOW not in runner.view.controls.stop_choices
        backend.speed = 500
        await runner.wait()
