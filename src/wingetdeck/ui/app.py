"""The application: holds the shared objects and moves between screens."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from textual.app import App
from textual.binding import Binding
from textual.screen import ModalScreen

from .. import __version__
from ..core.logs import SessionLog
from ..core.queue import ItemState, RunQueue
from ..core.runner import Runner, RunView
from ..core.safety import SnapshotFailed, create_restore_point, take_snapshot
from ..core.store import HistoryEntry, Store
from ..paths import is_elevated
from ..winget.backend import UpgradeOptions, WingetBackend
from ..winget.models import ChangeKind, Package
from .responsive import MEDIUM, WIDE, taskbar_code, title_text
from .screens.dialogs import ConfirmDialog
from .screens.history import HistoryScreen
from .screens.logs import LogsScreen
from .screens.no_winget import NoWingetScreen
from .screens.packages import PackagesScreen
from .screens.progress import ProgressScreen
from .screens.settings import SettingsScreen
from .screens.splash import SplashScreen
from .themes import DEFAULT_THEME, DEFAULT_VARIABLES, THEMES


_CONSENT = (
    "Many packages come with licence agreements, and winget's sources have terms of their own. "
    "Winget stops and asks about these, but an upgrade running here cannot answer it.\n\n"
    "To go on without being asked, WingetDeck can add --accept-package-agreements and "
    "--accept-source-agreements to each upgrade, which accepts them on your behalf. "
    "You can read a package's licence on its homepage from the details panel.\n\n"
    "Without this, packages that need it are marked as skipped. You can change it in Settings."
)
_AGREE = "Accept agreements"
_NO_AGREE = "Skip those packages"
_GO_ON = "Go on without it"
_RESUME = "Resume"
_DISCARD = "Don't resume"


class WingetDeckApp(App):
    TITLE = "WingetDeck — Package Upgrader"
    CSS_PATH = Path(__file__).parent / "app.tcss"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (MEDIUM, "-medium"), (WIDE, "-wide")]
    VERTICAL_BREAKPOINTS = [(0, "-short"), (20, "-compact"), (30, "-tall")]
    BINDINGS = [
        Binding("l", "show_logs", "Logs"),
        Binding("t", "show_settings", "Settings"),
        Binding("h", "show_history", "History"),
    ]

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
        self._resume_offered = False
        self._last_title = ""
        self._last_taskbar = ""
        super().__init__()
        runner.on_change = self._run_changed
        self.sub_title = f"v{__version__}"
        for theme in THEMES:
            self.register_theme(theme)
        settings = store.load_settings()
        self.theme = settings.theme if settings.theme in self.available_themes else DEFAULT_THEME

    def get_css_variables(self) -> dict[str, str]:
        return {**DEFAULT_VARIABLES, **super().get_css_variables()}

    def on_mount(self) -> None:
        self.backend.accept_source_agreements = self.store.load_settings().consented_agreements
        self._show_on_taskbar(None)
        self.push_screen(SplashScreen())

    def add_run_listener(self, listener: Callable[[RunView], None]) -> None:
        self._run_listeners.append(listener)

    def remove_run_listener(self, listener: Callable[[RunView], None]) -> None:
        if listener in self._run_listeners:
            self._run_listeners.remove(listener)

    def _run_changed(self, view: RunView) -> None:
        for listener in list(self._run_listeners):
            listener(view)
        self._show_on_taskbar(view)

    def write_terminal(self, text: str) -> None:
        if self._driver is not None:
            self._driver.write(text)

    def _show_on_taskbar(self, view: RunView | None) -> None:
        """The window title and taskbar button show progress while minimised."""
        title, code = title_text(view), taskbar_code(view)
        if title != self._last_title:
            self._last_title = title
            self.write_terminal(f"\x1b]0;{title}\x07")
        if code != self._last_taskbar:
            self._last_taskbar = code
            self.write_terminal(code)

    def on_unmount(self) -> None:
        self._show_on_taskbar(None)

    def show_packages(self, source: str | None) -> None:
        self.log_file.info("Source chosen", source=source or "all")
        self.push_screen(PackagesScreen(source))

    def start_upgrade(self, packages: list[Package]) -> None:
        self.log_file.info("Upgrade requested", packages=[p.id for p in packages])
        settings = self.store.load_settings()
        if settings.asked_agreements:
            self.run_worker(self._begin_run(packages), group="run-start", exclusive=True)
            return

        def answered(choice: str | None) -> None:
            if choice is None:
                return
            consent = choice == _AGREE
            self.store.save_settings(
                replace(self.store.load_settings(), asked_agreements=True, consented_agreements=consent)
            )
            self.backend.accept_source_agreements = consent
            self.log_file.info("Agreements answered", consent=consent)
            self.run_worker(self._begin_run(packages), group="run-start", exclusive=True)

        self.push_screen(ConfirmDialog("Licence agreements", _CONSENT, (_AGREE, _NO_AGREE)), answered)

    def options_for(self, package: Package) -> UpgradeOptions:
        settings = self.store.load_settings()
        chosen = settings.per_package.get(package.id, settings.defaults)
        return replace(chosen, accept_agreements=settings.consented_agreements)

    async def _begin_run(self, packages: list[Package], starter=None) -> None:
        if not await self._safety_steps():
            return
        try:
            await self.runner.start(packages, self.options_for, starter)
        except RuntimeError as e:
            self.log_file.warn("Run not started", error=str(e))
            self.notify(str(e), severity="warning")
            return
        screen = self.progress_screen()
        if screen.is_mounted:
            screen.new_run()
        self.show_progress()

    async def _safety_steps(self) -> bool:
        """False means the user chose not to go on."""
        try:
            path = await take_snapshot(self.backend, self.log_file.data_dir)
            self.log_file.info("Snapshot saved", path=str(path))
        except SnapshotFailed as e:
            self.log_file.warn("Snapshot failed", error=str(e))
            dialog = ConfirmDialog(
                "Could not save the list of installed apps",
                f"Before each run a list of installed versions is saved, so there is a record of how "
                f"things were. This time it failed: {e}\n\nGo on without it?",
                (_GO_ON,),
            )
            if await self.push_screen_wait(dialog) != _GO_ON:
                return False
        settings = self.store.load_settings()
        if settings.create_restore_point and is_elevated():
            result = await asyncio.to_thread(create_restore_point, "Before WingetDeck run")
            if result.ok:
                self.log_file.info("Restore point created")
            else:
                self.log_file.warn("No restore point", reason=result.message)
                self.notify(result.message, severity="warning")
        return True

    def offer_resume(self) -> None:
        snapshot = self.store.load_queue()
        if snapshot is None or not snapshot.items or self._resume_offered:
            return
        self._resume_offered = True
        names = ", ".join(i.name for i in snapshot.items[:5])
        count = len(snapshot.items)

        def answered(choice: str | None) -> None:
            if choice == _RESUME:
                self.log_file.info("Queue resumed", count=count)
                packages = RunQueue.restore(snapshot).items
                self.start_upgrade([item.package for item in packages])
            elif choice == _DISCARD:
                self.store.clear_queue(keep_copy=True)
                self.log_file.info("Queue declined, a copy was kept", count=count)

        text = (
            f"The last run did not finish: {names}{'…' if count > 5 else ''}.\n\n"
            "An interrupted download starts again from the beginning."
        )
        self.push_screen(
            ConfirmDialog(f"Resume unfinished queue ({count} left)?", text, (_RESUME, _DISCARD), cancel_label="Ask me later"),
            answered,
        )

    def start_rollback(self, entry: HistoryEntry, version: str) -> None:
        self.log_file.warn("Roll back requested", package=entry.id, version=version)
        package = Package(entry.name, entry.id, entry.to_version, version, None, ChangeKind.UNKNOWN)

        def starter(chosen: Package, options: UpgradeOptions):
            return self.backend.start_install_version(chosen.id, version, options)

        self.run_worker(self._begin_run([package], starter), group="run-start", exclusive=True)

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

    def _on_top(self, kind: type) -> bool:
        return isinstance(self.screen, kind) or isinstance(self.screen, ModalScreen)

    def action_show_logs(self) -> None:
        if not self._on_top(LogsScreen):
            self.push_screen(LogsScreen())

    def action_show_settings(self) -> None:
        if not self._on_top(SettingsScreen):
            self.push_screen(SettingsScreen())

    def action_show_history(self) -> None:
        if not self._on_top(HistoryScreen):
            self.push_screen(HistoryScreen())

    async def action_quit(self) -> None:
        await self.runner.shutdown()
        self.exit()
