import asyncio
import threading
import time
from dataclasses import replace

import pytest
from rich.cells import cell_len
from textual.app import App
from textual.drivers.headless_driver import HeadlessDriver

from wingetdeck.core.queue import RunState, Summary
from wingetdeck.ui.screens.no_winget import NoWingetScreen
from wingetdeck.ui.screens.progress import ProgressScreen
from wingetdeck.ui.screens.splash import SplashScreen
from wingetdeck.ui.symbols import to_ascii
from wingetdeck.ui.widgets.meters import PercentBar
from wingetdeck.winget.backend import FinishedEvent, StageEvent
from wingetdeck.winget.fake import FakeBackend
from wingetdeck.winget.models import ChangeKind, Package, Stage


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


async def until(check, seconds=8.0):
    async def poll():
        while not check():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(poll(), seconds)


@pytest.mark.parametrize(
    "text",
    ["WingetDeck — v1", "▔▔▁▁ ─│┌┐└┘ ╭╮╰╯", "[✓] → ‹ › … · ● ○ ✗ ■ ↻ ✕", "▀▄█░▏▕▐▌ ▁▂▃▄▅▆▇", "Büro 日本語 🎉"],
)
def test_to_ascii_is_ascii_and_keeps_every_column(text):
    out = to_ascii(text)
    assert out.isascii()
    assert cell_len(out) == cell_len(text)


def test_to_ascii_leaves_escape_codes_alone():
    code = "\x1b[38;2;1;2;3m\x1b]0;title\x07plain"
    assert to_ascii(code) == code


def test_to_ascii_reads_sensibly():
    assert to_ascii("[✓] a → b — c…") == "[x] a > b - c~"


def test_ascii_app_uses_a_driver_that_only_writes_ascii(make_app, monkeypatch):
    app = make_app(ascii_mode=True)
    written = []

    class Recording(HeadlessDriver):
        def write(self, data):
            written.append(data)

    monkeypatch.setattr(App, "get_driver_class", lambda self: Recording)
    driver_class = app.get_driver_class()
    driver_class.__new__(driver_class).write("[✓] → …")
    assert written == ["[x] > ~"]


def test_normal_app_keeps_the_stock_driver(make_app):
    app = make_app()
    assert "Ascii" not in app.get_driver_class().__name__


def test_ascii_mode_has_no_non_ascii_in_rendered_screen(tmp_path, demo_command):
    """The real driver in a real pseudo-console: every byte sent to the terminal is checked."""
    from winpty import PtyProcess

    process = PtyProcess.spawn([*demo_command, "--ascii"], dimensions=(36, 120), cwd=str(tmp_path))
    seen = []

    def read():
        while True:
            try:
                seen.append(process.read(65536))
            except EOFError:
                return

    threading.Thread(target=read, daemon=True).start()

    def wait_for(text, seconds=25.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if text in "".join(seen):
                return True
            time.sleep(0.1)
        return False

    try:
        assert wait_for("START")
        process.write("\r")
        assert wait_for("UPGRADE")
        time.sleep(1.5)  # the scan finishes and the table draws
        process.write(" ")
        process.write("u")
        time.sleep(4.0)  # consent question or run screen
        process.write("l")
        time.sleep(1.0)
        output = "".join(seen)
        odd = sorted({c for c in output if not c.isascii()})
        assert not odd, f"not ASCII: {odd!r}"
    finally:
        if process.isalive():
            process.terminate(force=True)


async def test_x86_style_no_pty_runs_full_flow_with_animation(make_app):
    """No pseudo console: no live numbers, and the rest of the app works from start to finish."""

    class Piped(FakeBackend):
        def start_upgrade(self, package, options):
            class Handle:
                pid = 0

                def freeze(self):
                    return False

                def thaw(self):
                    pass

                def kill(self):
                    from wingetdeck.winget.proc import KillResult

                    return KillResult(True)

                async def events(self):
                    yield StageEvent(Stage.INSTALLING)
                    await asyncio.sleep(1.0)
                    yield FinishedEvent(0)

            return Handle()

    app = make_app(Piped([pkg("A"), pkg("B")], live_progress=False))
    app.store.save_settings(replace(app.store.load_settings(), asked_agreements=True))
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        await until(lambda: isinstance(app.screen, SplashScreen) and app.screen.query("#start"))
        await pilot.click("#start")
        await pilot.pause(0.3)
        await app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press("a", "u")
        await until(lambda: isinstance(app.screen, ProgressScreen))
        await until(lambda: app.runner.view.stage is Stage.INSTALLING)
        await pilot.pause(0.1)
        first = str(app.screen.query_one(PercentBar).render())
        assert "%" not in first
        await asyncio.sleep(0.4)
        await pilot.pause()
        assert str(app.screen.query_one(PercentBar).render()) != first, "the animation moves"
        await until(lambda: app.runner.view.state is RunState.FINISHED)
        assert app.runner.view.summary.done == 2


def view(state, seconds, summary=Summary(2, 0, 0, 0, 0)):
    from wingetdeck.core.runner import RunView

    return RunView(state=state, elapsed_s=seconds, summary=summary)


async def test_long_run_notifies_once_when_it_ends(make_app):
    app = make_app()
    sent = []
    app.notifier = sent.append
    async with app.run_test() as pilot:
        await pilot.pause()
        app._run_changed(view(RunState.RUNNING, 90))
        assert sent == []
        app._run_changed(view(RunState.FINISHED, 90))
        app._run_changed(view(RunState.FINISHED, 90))
        assert sent == [Summary(2, 0, 0, 0, 0)]
        app._run_changed(view(RunState.RUNNING, 1))
        app._run_changed(view(RunState.FINISHED, 91))
        assert len(sent) == 2


async def test_short_run_does_not_notify(make_app):
    app = make_app()
    sent = []
    app.notifier = sent.append
    async with app.run_test() as pilot:
        await pilot.pause()
        app._run_changed(view(RunState.FINISHED, 5))
        assert sent == []


async def test_winget_too_old_gets_the_help_screen(make_app):
    class Old(FakeBackend):
        def capabilities(self):
            return replace(super().capabilities(), version="v1.3.2691")

    app = make_app(Old([]))
    async with app.run_test() as pilot:
        await pilot.pause()
        await until(lambda: isinstance(app.screen, NoWingetScreen))
        text = str(app.screen.query_one("#help").render())
        assert "v1.3.2691" in text and "1.4" in text


async def test_winget_details_are_logged_for_bug_reports(make_app):
    app = make_app()
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        found = [e for e in app.log_file.events("INFO") if e.message == "winget found"]
        assert found and {"version", "live_progress", "direct_downloader"} <= set(found[0].fields)
