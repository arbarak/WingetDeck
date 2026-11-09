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
