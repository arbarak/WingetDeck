"""What every full screen shares: the title bar and the "window too small" cover."""

from __future__ import annotations

from datetime import datetime

from rich.cells import cell_len
from rich.text import Text
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Static

from ..responsive import MIN_HEIGHT, MIN_WIDTH

_TOO_SMALL = "Window too small.\nMake it bigger: any running upgrade continues."


class TitleBar(Widget):
    """Our own, because the stock header can fail if its screen closes while it is still mounting."""

    DEFAULT_CSS = "TitleBar { dock: top; width: 100%; height: 1; }"

    def on_mount(self) -> None:
        self.set_interval(1.0, self.refresh)

    def render(self) -> Text:
        width = max(self.size.width, 1)
        app = self.app
        icon = "o" if app.ascii_mode else "○"
        title = f"{app.title} - {app.sub_title}" if app.ascii_mode else f"{app.title} — {app.sub_title}"
        title = title.encode("ascii", "replace").decode() if app.ascii_mode else title
        now = datetime.now().strftime("%H:%M:%S")
        clock_at = max(width - cell_len(now) - 1, 0)
        first_free = cell_len(icon) + 2
        room = clock_at - first_free - 1
        if room < cell_len(title):
            title = app.title if room >= cell_len(app.title) else ""
        title_at = max((width - cell_len(title)) // 2, first_free)
        title_at = min(title_at, clock_at - cell_len(title) - 1)
        line = f" {icon}".ljust(title_at) + title
        line = line.ljust(clock_at) + now + " "
        return Text(line[:width], no_wrap=True)


class DeckScreen(Screen):
    def on_mount(self) -> None:
        self.mount(Static(_TOO_SMALL, id="too-small", markup=False))
        self._update_too_small()

    def on_resize(self) -> None:
        self._update_too_small()

    def _update_too_small(self) -> None:
        cover = self.query("#too-small")
        if cover:
            small = self.size.width < MIN_WIDTH or self.size.height < MIN_HEIGHT
            cover.first().display = small
            self.set_class(small, "-too-small")
