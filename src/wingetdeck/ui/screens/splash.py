"""The first screen: logo, choose a source, START."""

from __future__ import annotations

import asyncio
import platform

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Horizontal, Vertical
from textual.widgets import Button, Footer, ListItem, ListView, Static

from ..pixels import BOX, LOGO, PALETTE, PixelArt
from ..console import MIN_WINGET, winget_too_old
from .base import DeckScreen, TitleBar

_ALL_SOURCES = "All sources"
_LOGO_FULL_ROWS = 30
_LOGO_SMALL_ROWS = 20
_FRIENDLY = {"msstore": "Microsoft Store only"}


def source_label(name: str) -> str:
    return _FRIENDLY.get(name, f"{name} only")


class SourceList(ListView):
    """Enter means START here. A click only chooses."""

    BINDINGS = [Binding("enter", "screen.start", "Start", show=False)]


class SplashScreen(DeckScreen):
    BINDINGS = [
        Binding("s", "start", "Start"),
        Binding("q", "app.quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._choices: list[str | None] = [None]
        self._notes: list[str] = []

    def compose(self) -> ComposeResult:
        yield TitleBar()
        with Vertical(id="splash-body"):
            with Center():
                yield PixelArt(LOGO, PALETTE, ascii_mode=self.app.ascii_mode, id="logo")
            with Center():
                yield Static("Select a source and press START", id="prompt")
            with Center():
                with Horizontal(id="splash-row"):
                    yield SourceList(ListItem(Static(_ALL_SOURCES, markup=False)), id="sources")
                    yield Button("START", id="start", disabled=True)
                    yield Button("✕" if not self.app.ascii_mode else "x", id="quit", classes="red")
            with Center():
                yield Static("Looking for winget…", id="versions", markup=False)
            with Center():
                yield Static("", id="notes", markup=False)
        yield Footer()

    def on_resize(self) -> None:
        self._fit_logo()

    def _fit_logo(self) -> None:
        """The logo shrinks, then goes, on a short window."""
        logo = self.query_one("#logo", PixelArt)
        height = self.size.height
        logo.parent.display = height >= _LOGO_SMALL_ROWS
        logo.display = height >= _LOGO_SMALL_ROWS
        wanted = LOGO if height >= _LOGO_FULL_ROWS else BOX
        if logo.art is not wanted:
            logo.art = wanted
            logo.refresh(layout=True)

    def on_mount(self) -> None:
        self._fit_logo()
        self.query_one("#sources", SourceList).index = 0
        data = self.app.log_file.data_dir
        if not data.portable:
            self._note(f"Data folder: {data.root}")
        self.load()

    def _note(self, text: str) -> None:
        self._notes.append(text)
        self.query_one("#notes", Static).update("\n".join(self._notes))

    @work(exclusive=True)
    async def load(self) -> None:
        app = self.app
        try:
            caps = await asyncio.to_thread(app.backend.capabilities)
        except Exception as e:  # a hung or broken winget must end at the help screen, not a crash
            app.log_file.error("Could not read winget capabilities", error=repr(e))
            app.show_no_winget(str(e))
            return
        if caps is None:
            app.log_file.warn("winget not found")
            app.show_no_winget()
            return
        app.log_file.info(
            "winget found",
            version=caps.version,
            live_progress=caps.live_progress,
            direct_downloader=caps.direct_downloader,
            settings_locked=caps.settings_locked,
        )
        if winget_too_old(caps.version):
            needed = ".".join(str(part) for part in MIN_WINGET)
            app.show_no_winget(f"This PC has winget {caps.version}. WingetDeck needs {needed} or newer.")
            return
        self.query_one("#versions", Static).update(f"winget {caps.version}  ·  Windows {platform.version()}")
        self.query_one("#start", Button).disabled = False  # All sources needs no list, which can be slow
        try:
            names = await app.backend.sources()
        except Exception as e:  # All sources still works without the list
            app.log_file.error("Could not list sources", error=repr(e))
            self._note(f"Could not list winget sources: {e}")
            names = []
        self._choices = [None, *names]
        listing = self.query_one("#sources", SourceList)
        await listing.extend(ListItem(Static(source_label(n), markup=False)) for n in names)
        listing.index = 0
        listing.focus()
        app.offer_resume()

    def action_start(self) -> None:
        if self.query_one("#start", Button).disabled:
            return
        index = self.query_one("#sources", SourceList).index or 0
        self.app.show_packages(self._choices[index])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start":
            self.action_start()
        elif event.button.id == "quit":
            self.app.exit()
