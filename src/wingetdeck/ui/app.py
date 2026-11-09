"""The application: holds the shared objects and moves between screens."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from textual.app import App

from .. import __version__
from ..core.logs import SessionLog
from ..core.queue import ItemState
from ..core.runner import Runner, RunView
from ..core.store import Store
from ..winget.backend import UpgradeOptions, WingetBackend
from ..winget.models import Package
from .screens.no_winget import NoWingetScreen
from .screens.packages import PackagesScreen
from .screens.progress import ProgressScreen
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
        self._run_listeners: list[Callable[[RunView], None]] = []
        super().__init__()
        runner.on_change = self._run_changed
        self.sub_title = f"v{__version__}"
        for theme in THEMES:
            self.register_theme(theme)
        saved = store.load_settings().theme
        self.theme = saved if saved in self.available_themes else DEFAULT_THEME

    def get_css_variables(self) -> dict[str, str]:
        return {**DEFAULT_VARIABLES, **super().get_css_variables()}

    def on_mount(self) -> None:
        self.push_screen(SplashScreen())

    def add_run_listener(self, listener: Callable[[RunView], None]) -> None:
        self._run_listeners.append(listener)

    def remove_run_listener(self, listener: Callable[[RunView], None]) -> None:
        if listener in self._run_listeners:
            self._run_listeners.remove(listener)

    def _run_changed(self, view: RunView) -> None:
        for listener in list(self._run_listeners):
            listener(view)

    def show_packages(self, source: str | None) -> None:
        self.log_file.info("Source chosen", source=source or "all")
        self.push_screen(PackagesScreen(source))

    def start_upgrade(self, packages: list[Package]) -> None:
        self.log_file.info("Upgrade requested", packages=[p.id for p in packages])
        self.run_worker(self._begin_run(packages), group="run-start", exclusive=True)

    def options_for(self, package: Package) -> UpgradeOptions:
        settings = self.store.load_settings()
        return settings.per_package.get(package.id, settings.defaults)

    async def _begin_run(self, packages: list[Package]) -> None:
        try:
            await self.runner.start(packages, self.options_for)
        except RuntimeError as e:
            self.log_file.warn("Run not started", error=str(e))
            self.notify(str(e), severity="warning")
            return
        screen = self.progress_screen()
        if screen.is_mounted:
            screen.new_run()
        self.show_progress()

    def progress_screen(self) -> ProgressScreen:
        if not self.is_screen_installed("progress"):
            self.install_screen(ProgressScreen(), "progress")
        return self.get_screen("progress")

    def show_progress(self) -> None:
        screen = self.progress_screen()
        if self.screen is not screen:
            self.push_screen(screen)

    def retry_failed(self) -> None:
        failed = [i.package for i in self.runner.view.items if i.state is ItemState.FAILED]
        if failed:
            self.start_upgrade(failed)

    def show_no_winget(self, reason: str | None = None) -> None:
        self.switch_screen(NoWingetScreen(reason))

    def check_winget_again(self) -> None:
        self.backend.refresh_capabilities()
        self.switch_screen(SplashScreen())

    async def action_quit(self) -> None:
        await self.runner.shutdown()
        self.exit()
