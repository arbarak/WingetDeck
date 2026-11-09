"""What every full screen shares: the title bar, the footer, the "window too small" cover, and being redrawn in a
newly chosen language."""

from __future__ import annotations

from datetime import datetime

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer as TextualFooter
from textual.widgets import Static
from textual.widgets._footer import FooterKey

from ... import i18n
from ...i18n import N_, t
from ..responsive import MIN_HEIGHT, MIN_WIDTH

_TOO_SMALL = N_("Window too small.\nMake it bigger: any running upgrade continues.")


class TitleBar(Widget):
    """Our own, because the stock header can fail if its screen closes while it is still mounting."""

    DEFAULT_CSS = "TitleBar { dock: top; width: 100%; height: 1; }"

    def on_mount(self) -> None:
        self.set_interval(1.0, self.refresh)

    def render(self) -> Text:
        width = max(self.size.width, 1)
        app = self.app
        icon = "○"
        name = t(app.title)
        title = f"{name} — {app.sub_title}"
        now = datetime.now().strftime("%H:%M:%S")
        clock_at = max(width - cell_len(now) - 1, 0)
        first_free = cell_len(icon) + 2
        room = clock_at - first_free - 1
        if room < cell_len(title):
            title = name if room >= cell_len(name) else ""
        title_at = max((width - cell_len(title)) // 2, first_free)
        title_at = min(title_at, clock_at - cell_len(title) - 1)
        line = f" {icon}".ljust(title_at) + title
        line = line.ljust(clock_at) + now + " "
        return Text(line[:width], no_wrap=True)


class Footer(TextualFooter):
    """The stock footer, with each key's description in the chosen language."""

    def compose(self) -> ComposeResult:
        for widget in super().compose():
            if isinstance(widget, FooterKey) and widget.description:
                widget.description = t(widget.description)
            yield widget


class DeckScreen(Screen):
    def __init__(self) -> None:
        super().__init__()
        self.language = i18n.current()

    def fresh(self) -> Screen | None:
        """A new copy of this screen, drawn in the current language. None keeps this one as it is."""
        return type(self)()

    def on_mount(self) -> None:
        self.mount(Static(t(_TOO_SMALL), id="too-small", markup=False))
        self._update_too_small()

    def on_screen_resume(self) -> None:
        if self.language != i18n.current():
            self.app.call_later(self.app.renew_screen, self)

    def on_resize(self) -> None:
        self._update_too_small()

    def _update_too_small(self) -> None:
        cover = self.query("#too-small")
        if cover:
            small = self.size.width < MIN_WIDTH or self.size.height < MIN_HEIGHT
            cover.first().display = small
            self.set_class(small, "-too-small")
