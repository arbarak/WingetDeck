import sys

import pytest

from wingetdeck.core.logs import SessionLog
from wingetdeck.core.runner import Runner
from wingetdeck.core.store import Store
from wingetdeck.ui.app import WingetDeckApp
from wingetdeck.winget.fake import FakeBackend, demo_packages


@pytest.fixture
def make_app(tmp_data):
    def make(backend=None, data=None, **kw):
        folder = data or tmp_data
        log = SessionLog(folder, False, {})
        store = Store(folder, log)
        backend = backend or FakeBackend(demo_packages(), speed=200)
        runner = Runner(backend, store, log, lambda view: None)
        return WingetDeckApp(backend, store, log, runner, **kw)

    return make


@pytest.fixture
def demo_command(tmp_path):
    """Starts the demo as its own process, with a data folder of its own.

    These tests kill the app in the middle of a run, which leaves a queue to resume. In the shared data folder, that
    queue would put a question in front of the next run's start screen.
    """
    launcher = tmp_path / "launch_demo.py"
    launcher.write_text(
        "import pathlib, sys\n"
        "from wingetdeck import cli\n"
        "from wingetdeck.paths import DataDir\n"
        f"cli.app_data_dir = lambda: DataDir(pathlib.Path({str(tmp_path / 'data')!r}), True)\n"
        "sys.exit(cli.main(sys.argv[1:]))\n",
        encoding="utf-8",
    )
    return [sys.executable, str(launcher), "--demo"]
