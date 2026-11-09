import ctypes
import json
import subprocess
import sys

import pytest

from wingetdeck import cli
from wingetdeck.core.queue import Summary
from wingetdeck.ui.console import (
    ENABLE_EXTENDED_FLAGS,
    ENABLE_QUICK_EDIT_MODE,
    QuickEditGuard,
    TerminalInfo,
    check_support,
    detect_terminal,
    session_header,
    winget_too_old,
    windows_build,
)
from wingetdeck.ui.notify import notify_done, summary_text


class FakeConsole:
    def __init__(self, mode=0x01F7):
        self.mode = mode
        self.calls = []

    def get_mode(self):
        return self.mode

    def set_mode(self, mode):
        self.calls.append(mode)
        self.mode = mode
        return True


def test_quickedit_off_inside_and_restored_after():
    console = FakeConsole()
    with QuickEditGuard(console):
        assert not console.mode & ENABLE_QUICK_EDIT_MODE
        assert console.mode & ENABLE_EXTENDED_FLAGS, "Windows ignores the change without this flag"
    assert console.mode == 0x01F7


def test_quickedit_restored_on_exception():
    console = FakeConsole()
    with pytest.raises(ValueError):
        with QuickEditGuard(console):
            raise ValueError("crash")
    assert console.mode == 0x01F7


def test_quickedit_guard_does_nothing_without_a_console():
    console = FakeConsole(mode=None)
    with QuickEditGuard(console):
        pass
    assert console.calls == []


_REAL_CONSOLE_CHECK = """
import json, sys
from textual.drivers.win32 import enable_application_mode
from wingetdeck.ui.console import QuickEditGuard, RealConsole
console = RealConsole()
before = console.get_mode()
try:
    with QuickEditGuard(console):
        inside = console.get_mode()
        restore = enable_application_mode()  # what Textual does next must not turn it back on
        with_textual = console.get_mode()
        restore()
        raise ValueError
except ValueError:
    pass
after = console.get_mode()
open(sys.argv[1], "w").write(json.dumps([before, inside, with_textual, after]))
"""


def test_quickedit_guard_on_a_real_hidden_console(tmp_path):
    out = tmp_path / "modes.json"
    info = subprocess.STARTUPINFO()
    info.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # SW_HIDE: nothing appears on the desktop
    subprocess.run(
        [sys.executable, "-c", _REAL_CONSOLE_CHECK, str(out)],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        startupinfo=info,
        check=True,
        timeout=30,
    )
    before, inside, with_textual, after = json.loads(out.read_text())
    assert before is not None
    assert not inside & ENABLE_QUICK_EDIT_MODE
    assert not with_textual & ENABLE_QUICK_EDIT_MODE
    assert after == before


def test_below_1809_gets_message():
    assert "1809" in check_support(16299)


def test_17763_supported():
    assert check_support(17763) is None


def test_this_pc_build_is_read():
    assert windows_build() == sys.getwindowsversion().build


def test_old_windows_is_told_before_anything_starts(monkeypatch, capsys):
    monkeypatch.setattr(cli, "windows_build", lambda: 16299)
    assert cli.main([]) == 1
    assert "1809" in capsys.readouterr().err


def test_old_windows_can_still_try_the_demo_or_print_the_version(monkeypatch, capsys):
    monkeypatch.setattr(cli, "windows_build", lambda: 16299)
    assert cli.main(["--version"]) == 0


@pytest.mark.parametrize(
    "env,font,name,plain,basic",
    [
        ({"WT_SESSION": "x"}, None, "Windows Terminal", False, False),
        ({"TERM_PROGRAM": "vscode"}, None, "vscode", False, False),
        ({"ConEmuPID": "1"}, None, "ConEmu", False, False),
        ({}, "Consolas", "classic console", False, True),
        ({}, "Terminal", "classic console", True, False),
        ({}, None, "classic console", False, True),
    ],
)
def test_detect_terminal(env, font, name, plain, basic):
    info = detect_terminal(env, font)
    assert (info.name, info.ascii_recommended, info.basic_symbols) == (name, plain, basic)


def test_session_header_has_what_a_bug_report_needs():
    header = session_header(
        demo=False, terminal=TerminalInfo("Windows Terminal", False), size=(120, 40), locale_name="fr-MA", elevated=True
    )
    for key in ("app", "windows", "build", "machine", "terminal", "size", "locale", "elevated", "demo"):
        assert key in header
    assert header["terminal"] == "Windows Terminal" and header["size"] == "120x40" and header["locale"] == "fr-MA"
    json.dumps(header)


@pytest.mark.parametrize(
    "version,old",
    [("v1.3.2691", True), ("v0.9", True), ("v1.4.10173", False), ("v1.29.380", False), ("1.12", False), ("v?", False), ("", False), ("v0.0.0-demo", False)],
)
def test_winget_too_old(version, old):
    assert winget_too_old(version) is old


def test_notify_failure_returns_false():
    def broken(*a, **k):
        raise OSError("no powershell")

    assert notify_done(Summary(1, 0, 0, 0, 0), spawn=broken) is False


def test_notify_never_raises_on_a_bad_summary():
    assert notify_done(None, spawn=lambda *a, **k: None) is False


def test_notify_passes_the_text_by_environment_not_inside_the_command():
    seen = {}

    def spawn(command, **kw):
        seen["command"] = command
        seen["env"] = kw["env"]

    assert notify_done(Summary(3, 0, 0, 1, 0), spawn=spawn) is True
    assert "3 upgraded" in seen["env"]["WINGETDECK_NOTE"]
    assert "3 upgraded" not in " ".join(seen["command"])


def test_summary_text_lists_only_what_happened():
    assert summary_text(Summary(2, 1, 0, 1, 0)) == "2 upgraded, 1 needs a restart, 1 failed"
    assert summary_text(Summary(0, 0, 0, 0, 3)) == "3 stopped"
    assert summary_text(Summary(0, 0, 0, 0, 0)) == "Nothing to do"


def test_kernel32_font_lookup_does_not_raise():
    from wingetdeck.ui.console import console_font

    assert console_font() is None or isinstance(console_font(), str)
    assert ctypes.windll.kernel32 is not None
