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


def contrast(one, two) -> float:
    """WCAG contrast ratio between two (r, g, b) colours."""

    def luminance(rgb):
        def channel(value):
            value /= 255
            return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

        r, g, b = (channel(v) for v in rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    high, low = sorted((luminance(one), luminance(two)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.fixture
def faint_pixels():
    """Colours of a pixel-art widget, as really drawn on screen, that stand out less than `minimum` from the theme's
    background. `lines` picks the widget's lines to look at."""

    def faint(app, widget, minimum, lines=slice(None)):
        background = app.current_theme.to_color_system().background.rgb
        region = widget.region
        strips = app.screen._compositor.render_strips()
        drawn = set()
        for y in list(range(region.y, region.bottom))[lines]:
            x = 0
            for segment in strips[y]:
                end = x + len(segment.text)
                if end > region.x and x < region.right and segment.style and any(c in segment.text for c in "▀▄#"):
                    for colour in (segment.style.color, segment.style.bgcolor):
                        if colour is not None:
                            rgb = colour.get_truecolor()
                            drawn.add((rgb.red, rgb.green, rgb.blue))
                x = end
        assert drawn, "nothing drawn"
        return {c for c in drawn if c != background and contrast(c, background) < minimum}

    return faint
