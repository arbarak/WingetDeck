import pytest

from wingetdeck import __version__, cli
from wingetdeck.core.console import CTRL_C, CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN, make_ctrl_handler
from wingetdeck.core.store import SingleInstance
from wingetdeck.ui.app import WingetDeckApp


@pytest.fixture
def data(tmp_data, monkeypatch):
    monkeypatch.setattr(cli, "app_data_dir", lambda: tmp_data)
    monkeypatch.setattr(cli, "install_close_handler", lambda callback: None)
    return tmp_data


def test_cli_version_prints_and_exits_zero(capsys):
    assert cli.main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_cli_crash_writes_crash_file_and_returns_one(data, monkeypatch, capsys):
    class Boom:
        return_code = None
        _exception = None

        def __init__(self, *a, **kw):
            pass

        def run(self):
            raise ValueError("kaboom")

    monkeypatch.setattr(cli, "WingetDeckApp", Boom)
    assert cli.main([]) == 1
    crash = list(data.logs.glob("crash_*"))
    assert crash and "kaboom" in crash[0].read_text(encoding="utf-8")
    assert str(crash[0]) in capsys.readouterr().err


def test_cli_crash_inside_textual_is_also_written(data, monkeypatch):
    class Broken(WingetDeckApp):
        def on_mount(self):
            raise ValueError("kaboom inside")

        def run(self, **kw):
            return super().run(headless=True, **kw)

    monkeypatch.setattr(cli, "WingetDeckApp", Broken)
    assert cli.main([]) == 1
    assert "kaboom inside" in next(data.logs.glob("crash_*")).read_text(encoding="utf-8")


def test_second_instance_prints_message_and_returns_one(data, capsys):
    with SingleInstance(data):
        assert cli.main([]) == 1
    assert "already running" in capsys.readouterr().err.lower()


def test_demo_data_is_kept_apart_from_real_data(tmp_data):
    demo = cli.demo_data_dir(tmp_data)
    assert demo.root != tmp_data.root and demo.root.parent == tmp_data.root
    assert demo.logs.is_dir() and demo.state.is_dir()


def test_close_handler_runs_callback_for_closing_events():
    calls = []
    handler = make_ctrl_handler(lambda: calls.append(1))
    for event in (CTRL_CLOSE, CTRL_LOGOFF, CTRL_SHUTDOWN):
        assert handler(event)
    assert len(calls) == 3


def test_close_handler_leaves_ctrl_c_alone():
    calls = []
    assert not make_ctrl_handler(lambda: calls.append(1))(CTRL_C)
    assert calls == []


def test_close_handler_survives_a_failing_callback():
    def broken():
        raise ValueError("no")

    assert make_ctrl_handler(broken)(CTRL_CLOSE)


def test_the_app_is_told_which_language_windows_shows(data, monkeypatch):
    given = {}

    class Catch:
        return_code = 0
        _exception = None

        def __init__(self, *a, **kw):
            given.update(kw)

        def run(self):
            return None

    monkeypatch.setattr(cli, "WingetDeckApp", Catch)
    monkeypatch.setattr(cli, "ui_language", lambda: "fr-FR")
    cli.main(["--demo"])
    assert given["system_language"]() == "fr-FR"
