"""The application: holds the shared objects and moves between screens."""

from __future__ import annotations

from pathlib import Path

from textual.app import App

from .. import __version__
from ..core.logs import SessionLog
from ..core.runner import Runner
from ..core.store import Store
from ..winget.backend import WingetBackend
from .screens.no_winget import NoWingetScreen
from .screens.packages import PackagesScreen
from .screens.splash import SplashScreen
from .themes import DEFAULT_THEME, DEFAULT_VARIABLES, THEMES


class WingetDeckApp(App):
    TITLE = "WingetDeck — Package Upgrader"
    CSS_PATH = Path(__file__).parent / "app.tcss"

    def __init__(
        self,
        backend: WingetBackend,
        store: Store,
        log: SessionLog,
        runner: Runner,
        ascii_mode: bool = False,
    ) -> None:
        self.backend = backend
        self.store = store
        self.log_file = log  # App.log is Textual's own
        self.runner = runner
        self.ascii_mode = ascii_mode
        super().__init__()
        self.sub_title = f"v{__version__}"
        for theme in THEMES:
            self.register_theme(theme)
        saved = store.load_settings().theme
        self.theme = saved if saved in self.available_themes else DEFAULT_THEME

    def get_css_variables(self) -> dict[str, str]:
        return {**DEFAULT_VARIABLES, **super().get_css_variables()}

    def on_mount(self) -> None:
        self.push_screen(SplashScreen())

    def show_packages(self, source: str | None) -> None:
        self.log_file.info("Source chosen", source=source or "all")
        self.push_screen(PackagesScreen(source))

    def show_no_winget(self, reason: str | None = None) -> None:
        self.switch_screen(NoWingetScreen(reason))

    def check_winget_again(self) -> None:
        self.backend.refresh_capabilities()
        self.switch_screen(SplashScreen())

    async def action_quit(self) -> None:
        await self.runner.shutdown()
        self.exit()
