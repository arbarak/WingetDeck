"""The classic console draws a box for any character its font lacks, so those characters must never reach it."""

import asyncio

import pytest
from rich.cells import cell_len
from textual.widgets import Checkbox
from textual.widgets._footer import FooterKey

from wingetdeck.ui.console import TerminalInfo, detect_terminal, font_has_glyph
from wingetdeck.ui.symbols import basic_symbols, stand_ins
from wingetdeck.ui.widgets.package_table import columns
from wingetdeck.winget.fake import FakeBackend, demo_packages
from wingetdeck.winget.models import ChangeKind, Package

CONSOLAS_LACKS = "↻▁▂▃▅▆▇▉▊▋▍▎▏▔▕▖▗▘▙▛▜▝▟✓✕✗"


def lacking(chars):
    return lambda char: char not in chars


def test_a_character_the_font_has_is_left_alone():
    translate = basic_symbols(lacking(""))
    assert translate("┌─┐ █ ▀ ▄ ● ✓ → é") == "┌─┐ █ ▀ ▄ ● ✓ → é"


def test_a_missing_character_gets_its_nearest_stand_in():
    translate = basic_symbols(lacking(CONSOLAS_LACKS))
    assert translate("✕") == "×"
    assert translate("✓") == "√"
    assert translate("▏") == "▌"
    assert translate("█") == "█"


def test_the_next_stand_in_is_used_when_the_font_lacks_the_first():
    translate = basic_symbols(lacking("✕×"))
    assert translate("✕") == "x"


def test_a_character_with_no_stand_in_falls_back_to_plain_text():
    translate = basic_symbols(lacking("é"))
    assert translate("café") == "cafe"


def test_escape_sequences_pass_through_untouched():
    translate = basic_symbols(lacking(CONSOLAS_LACKS))
    code = "\x1b[38;2;1;2;3m\x1b]0;WingetDeck\x07"
    assert translate(code) == code


@pytest.mark.parametrize("char", sorted(stand_ins()))
def test_every_stand_in_keeps_the_column_width(char):
    translate = basic_symbols(lacking(char))
    assert cell_len(translate(char)) == cell_len(char)


@pytest.mark.parametrize("face", ["Consolas", "Lucida Console", "Courier New"])
def test_real_console_fonts_get_only_characters_they_can_draw(face):
    has = font_has_glyph(face)
    assert has is not None
    translate = basic_symbols(has)
    for char in stand_ins():
        out = translate(char)
        assert all(ord(c) < 128 or has(c) for c in out), (face, char, out)


def test_the_font_check_reads_the_real_font():
    has = font_has_glyph("Consolas")
    assert has("A") and has("█") and has("─")
    assert not has("▔") and not has("✕") and not has("↻")
    assert not has("🔎")


def test_a_classic_console_with_a_normal_font_gets_basic_symbols():
    info = detect_terminal({}, "Consolas", True)
    assert info == TerminalInfo("classic console", False, True, "Consolas")


def test_the_old_raster_font_still_gets_plain_text():
    assert detect_terminal({}, "Terminal", True).ascii_recommended


def test_a_console_with_a_hidden_window_is_some_other_terminal_drawing_for_it():
    """Windows 11 can hand a console to Windows Terminal without setting WT_SESSION. Its fonts draw everything."""
    info = detect_terminal({}, "Consolas", False)
    assert not info.basic_symbols and not info.ascii_recommended


def test_windows_terminal_keeps_every_symbol():
    assert not detect_terminal({"WT_SESSION": "x"}, "Consolas", True).basic_symbols


def _pkg(name, package_id):
    return Package(name, package_id, "1.0", "1.1", "winget", ChangeKind.MINOR)


def test_a_maximised_window_shows_long_ids_in_full():
    rows = [_pkg("Visual Studio Community 2022", "Microsoft.VisualStudio.2022.Community")]
    by_key = {c.key: c.width for c in columns(237, rows)}
    assert by_key["id"] >= len("Microsoft.VisualStudio.2022.Community")


def test_spare_width_is_shared_so_the_name_column_is_not_a_gulf():
    rows = demo_packages()
    by_key = {c.key: c.width for c in columns(237, rows)}
    longest = max(len(p.name) for p in rows)
    assert by_key["name"] < longest + 60
    assert by_key["installed"] > 15


def test_a_tight_window_still_favours_names_over_long_ids():
    rows = [_pkg("A rather long application name here", "Microsoft.VisualStudio.2022.Community.Preview")]
    by_key = {c.key: c.width for c in columns(120, rows)}
    assert by_key["name"] >= len("A rather long application name here")
    assert by_key["id"] < len("Microsoft.VisualStudio.2022.Community.Preview")


def _walk_every_screen(tmp_path, demo_command, *flags):
    """Every screen, in a real pseudo console. Returns every character the app sent to the terminal."""
    import threading
    import time

    winpty = pytest.importorskip("winpty")
    seen = []
    drawn = set()

    def launch():
        started = winpty.PtyProcess.spawn([*demo_command, *flags], dimensions=(36, 120), cwd=str(tmp_path))

        def read():
            while True:
                try:
                    chunk = started.read(65536)
                except EOFError:
                    return
                seen.append(chunk)
                drawn.update(chunk)

        threading.Thread(target=read, daemon=True).start()
        return started

    process = launch()

    def wait_for(text, seconds=25.0):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if text in "".join(seen):
                return True
            time.sleep(0.1)
        return False

    def go(keys, reaches):
        """Send keys and prove the screen was really reached: a walk that misses a screen proves nothing."""
        seen.clear()
        for key in keys:
            process.write(key)
            time.sleep(0.5)
        assert wait_for(reaches), f"never reached {reaches!r} after {keys!r}"

    escape = "\x1b"
    try:
        assert wait_for("START")
        go(["\r"], "UPGRADE")
        time.sleep(1.5)
        go([" ", "d"], "Publisher")
        go([escape, "/"], "Type to filter")
        go([escape, "t"], "Upgrade options")
        go([escape, "l"], "Save diagnostic report")
        go([escape, "h"], "See log")
        go([escape, "\x10"], "Search")
        process.write(escape)
        time.sleep(0.5)
        for rows, columns_wide, text in ((10, 40, "too small"), (20, 70, "NAME")):
            seen.clear()
            process.setwinsize(rows, columns_wide)
            assert wait_for(text), text
        process.setwinsize(36, 120)
        time.sleep(1.0)
        go(["a", "u"], "Licence agreements")
        go(["\t", "\t", "\r"], "DOWNLOADING")
        go(["p"], "PAUSED")
        go(["s"], "Stop now")
        go([escape, "\x11"], "A run is going")
        process.write(escape)
        time.sleep(0.5)
        assert process.isalive()
        process.terminate(force=True)
        seen.clear()
        process = launch()
        assert wait_for("Resume unfinished"), "the killed run did not offer to resume"
    finally:
        process.terminate(force=True)
    return drawn


def test_every_screen_draws_only_what_the_console_font_has(tmp_path, demo_command):
    drawn = _walk_every_screen(tmp_path, demo_command, "--basic")
    has = font_has_glyph("Consolas")
    missing = sorted(c for c in drawn if ord(c) > 127 and not has(c))
    assert not missing, missing
    assert "×" in drawn or "√" in drawn, "the walk never reached a replaced symbol"


def test_everything_the_full_app_draws_can_be_replaced_for_every_console_font(tmp_path, demo_command):
    drawn = _walk_every_screen(tmp_path, demo_command)
    assert "▔" in drawn and "✕" in drawn, "the walk did not draw the symbols that showed as boxes"
    for face in ("Consolas", "Lucida Console", "Courier New"):
        has = font_has_glyph(face)
        translate = basic_symbols(has)
        missing = sorted(c for c in drawn for out in translate(c) if ord(out) > 127 and not has(out))
        assert not missing, (face, missing)


def test_every_footer_key_fits_the_standard_console_window(make_app):
    """A new console window is 120 columns wide. Windows 10 showed the last key cut off at that size."""

    async def run():
        app = make_app(FakeBackend(demo_packages()))
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            app.show_packages(None)
            await pilot.pause()
            await app.workers.wait_for_complete()
            await pilot.pause()
            keys = list(app.screen.query(FooterKey))
            right_edge = min((k.region.x for k in keys if k.has_class("-command-palette")), default=120)
            cut_off = [k.description for k in keys if not k.has_class("-command-palette") and k.region.right > right_edge]
            assert keys and not cut_off, cut_off

    asyncio.run(run())


def test_settings_checkboxes_line_up_instead_of_forming_a_staircase(make_app):
    async def run():
        app = make_app(FakeBackend(demo_packages()))
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause()
            await pilot.press("t")
            await pilot.pause()
            widths = {box.region.width for box in app.screen.query(Checkbox)}
            assert len(widths) == 1, widths

    asyncio.run(run())
