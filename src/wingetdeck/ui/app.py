"""The application: holds the shared objects and moves between screens."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from textual.app import App
from textual.driver import Driver
from textual.binding import Binding
from textual.screen import ModalScreen, Screen

from .. import __version__, i18n
from ..i18n import N_, t
from ..core.logs import SessionLog
from ..core.queue import ItemState, RunQueue, RunState
from ..core.runner import Runner, RunView
from ..core.safety import SnapshotFailed, create_restore_point, take_snapshot
from ..core.store import HistoryEntry, Store
from ..paths import is_elevated
from ..winget.backend import UpgradeOptions, WingetBackend
from ..winget.models import ChangeKind, Package, Stage
from .notify import notify_done
from .responsive import MEDIUM, WIDE, taskbar_code, title_text
from .screens.dialogs import ConfirmDialog
from .screens.history import HistoryScreen
from .screens.logs import LogsScreen
from ..winget.repair import WingetRepair
from .screens.no_winget import NoWingetScreen
from .screens.packages import PackagesScreen, run_is_active
from .screens.progress import ProgressScreen
from .screens.settings import SettingsScreen
from .screens.splash import SplashScreen
from .symbols import to_ascii
from .themes import DEFAULT_THEME, DEFAULT_VARIABLES, THEMES


_CONSENT = N_(
    "Many packages come with licence agreements, and winget's sources have terms of their own. "
    "Winget stops and asks about these, but an upgrade running here cannot answer it.\n\n"
    "To go on without being asked, WingetDeck can add --accept-package-agreements and "
    "--accept-source-agreements to each upgrade, which accepts them on your behalf. "
    "You can read a package's licence on its homepage from the details panel.\n\n"
    "Without this, packages that need it are marked as skipped. You can change it in Settings."
)
_CONSOLE_SETTLE_SECONDS = 0.3  # the classic console puts its scrollbars back just after a resize
_AGREE = N_("Accept agreements")
_NO_AGREE = N_("Skip those packages")
_GO_ON = N_("Go on without it")
_QUIT_TITLE = N_("A run is going")
_QUIT_AFTER = N_("Quit after this package")
_QUIT_NOW = N_("Quit now")
_QUIT_KEEPS = N_("Your queue is saved, and WingetDeck offers to continue it next time.")
_QUIT_INSTALLING = N_(
    "This package may be installing. Quitting now ends winget along with this app. An installer that has "
    "already started may carry on by itself, but the package could be left half-installed."
)
_QUIT_DOWNLOADING = N_(
    "A download is running. Quitting now stops winget, which can leave a partial file in its temp "
    "folder. Nothing has been installed for this package yet."
)
_RESUME = N_("Resume")
_DISCARD = N_("Don't resume")

_NOTIFY_AFTER_SECONDS = 60  # a shorter run is one the person is probably still watching


class WingetDeckApp(App):
    TITLE = N_("WingetDeck — Package Upgrader")
    CSS_PATH = Path(__file__).parent / "app.tcss"
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (MEDIUM, "-medium"), (WIDE, "-wide")]
    VERTICAL_BREAKPOINTS = [(0, "-short"), (20, "-compact"), (30, "-tall")]
    BINDINGS = [
        Binding("l", "show_logs", N_("Logs")),
        Binding("t", "show_settings", N_("Settings")),
        Binding("h", "show_history", N_("History")),
    ]

    def __init__(
        self,
        backend: WingetBackend,
        store: Store,
        log: SessionLog,
        runner: Runner,
        ascii_mode: bool = False,
        symbols: Callable[[str], str] | None = None,
        tidy_console: Callable[[], None] | None = None,
        repair: WingetRepair | None = None,
        system_language: Callable[[], str] | None = None,
    ) -> None:
        self.backend = backend
        self.store = store
        self.log_file = log  # App.log is Textual's own
        self.runner = runner
        self.ascii_mode = ascii_mode
        self.symbols = to_ascii if ascii_mode else symbols
        self.tidy_console = tidy_console
        self.repair = repair or WingetRepair()
        self._run_starting = False
        self._run_listeners: list[Callable[[RunView], None]] = []
        self._resume_offered = False
        self._last_title = ""
        self._last_taskbar = ""
        self.notifier = notify_done
        self._notified = False
        self._quit_when_finished = False
        self.system_language = system_language or (lambda: "en")
        super().__init__()
        runner.on_change = self._run_changed
        self.sub_title = f"v{__version__}"
        for theme in THEMES:
            self.register_theme(theme)
        settings = store.load_settings()
        self.theme = settings.theme if settings.theme in self.available_themes else DEFAULT_THEME
        i18n.set_language(i18n.choose(settings.language, self.system_language()))

    def get_css_variables(self) -> dict[str, str]:
        return {**DEFAULT_VARIABLES, **super().get_css_variables()}

    def on_mount(self) -> None:
        settings = self.store.load_settings()
        self.backend.accept_source_agreements = settings.consented_agreements
        self.runner.set_stall_minutes(settings.stall_minutes)
        self.log_file.info("Language", language=i18n.current(), setting=settings.language or "automatic",
                           windows=self.system_language())
        self._show_on_taskbar(None)
        self.push_screen(SplashScreen())
        self._tidy_console()

    def on_resize(self) -> None:
        self._tidy_console()
        self.set_timer(_CONSOLE_SETTLE_SECONDS, self._tidy_console)

    def _tidy_console(self) -> None:
        if self.tidy_console is not None:
            self.tidy_console()

    def add_run_listener(self, listener: Callable[[RunView], None]) -> None:
        self._run_listeners.append(listener)

    def remove_run_listener(self, listener: Callable[[RunView], None]) -> None:
        if listener in self._run_listeners:
            self._run_listeners.remove(listener)

    def _run_changed(self, view: RunView) -> None:
        for listener in list(self._run_listeners):
            listener(view)
        self._show_on_taskbar(view)
        self._notify_if_finished(view)
        if self._quit_when_finished and view.state is RunState.FINISHED:
            self._quit_when_finished = False
            self.call_later(self._quit_now)

    def _notify_if_finished(self, view: RunView) -> None:
        if view.state is not RunState.FINISHED:
            self._notified = False
        elif not self._notified and view.summary is not None and view.elapsed_s >= _NOTIFY_AFTER_SECONDS:
            self._notified = True
            self.notifier(view.summary)

    def get_driver_class(self) -> type[Driver]:
        driver = super().get_driver_class()
        translate = self.symbols
        if translate is None:
            return driver

        class SymbolDriver(driver):
            def write(self, data: str) -> None:
                super().write(translate(data))

        return SymbolDriver

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
        if self._run_starting:
            self.log_file.info("Upgrade pressed again while starting, ignored")
            return
        self.log_file.info("Upgrade requested", packages=[p.id for p in packages])

        def begin() -> None:
            self._run_starting = True
            self.run_worker(self._begin_run(packages), group="run-start", exclusive=True)

        if self.store.load_settings().asked_agreements:
            begin()
            return

        def answered(consent: bool | None) -> None:
            if consent is not None:
                begin()

        self.ask_agreements(answered)

    def ask_agreements(self, then: Callable[[bool | None], None], reason: str = "") -> None:
        """Ask, remember the answer, and tell `then`: True, False, or None for Cancel, which is not remembered."""

        def answered(choice: str | None) -> None:
            if choice is None:
                then(None)
                return
            consent = choice == _AGREE
            self.store.save_settings(
                replace(self.store.load_settings(), asked_agreements=True, consented_agreements=consent)
            )
            self.backend.accept_source_agreements = consent
            self.log_file.info("Agreements answered", consent=consent)
            then(consent)

        text = f"{t(reason)}\n\n{t(_CONSENT)}" if reason else _CONSENT
        self.push_screen(ConfirmDialog(N_("Licence agreements"), text, (_AGREE, _NO_AGREE)), answered)

    def options_for(self, package: Package) -> UpgradeOptions:
        settings = self.store.load_settings()
        chosen = settings.per_package.get(package.id, settings.defaults)
        return replace(chosen, accept_agreements=settings.consented_agreements)

    async def _begin_run(self, packages: list[Package], starter=None) -> None:
        try:
            if not await self._safety_steps():
                return
            try:
                await self.runner.start(packages, self.options_for, starter)
            except RuntimeError as e:
                self.log_file.warn("Run not started", error=str(e))
                self.notify(str(e), severity="warning")
                return
        finally:
            self._run_starting = False
        screen = self.progress_screen()
        if screen.is_mounted:
            screen.new_run()
        self.show_progress()

    async def _safety_steps(self) -> bool:
        """False means the user chose not to go on."""
        self.notify(t("Saving the list of installed apps before starting…"), timeout=4)
        try:
            path = await take_snapshot(self.backend, self.log_file.data_dir)
            self.log_file.info("Snapshot saved", path=str(path))
        except SnapshotFailed as e:
            self.log_file.warn("Snapshot failed", error=str(e))
            dialog = ConfirmDialog(
                N_("Could not save the list of installed apps"),
                t(
                    "Before each run a list of installed versions is saved, so there is a record of how "
                    "things were. This time it failed: {error}\n\nGo on without it?",
                    error=e,
                ),
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

        text = t(
            "The last run did not finish: {names}.\n\nAn interrupted download starts again from the beginning.",
            names=names + ("…" if count > 5 else ""),
        )
        title = t("Resume unfinished queue ({count} left)?", count=count)
        self.push_screen(
            ConfirmDialog(title, text, (_RESUME, _DISCARD), cancel_label=N_("Ask me later")),
            answered,
        )

    def start_rollback(self, entry: HistoryEntry, version: str) -> None:
        self.log_file.warn("Roll back requested", package=entry.id, version=version)
        package = Package(entry.name, entry.id, entry.to_version, version, None, ChangeKind.UNKNOWN)

        def starter(chosen: Package, options: UpgradeOptions):
            return self.backend.start_install_version(chosen.id, version, options)

        self.run_worker(self._begin_run([package], starter), group="run-start", exclusive=True)

    def progress_screen(self) -> ProgressScreen:
        if self.is_screen_installed("progress"):
            screen = self.get_screen("progress")
            if screen.language == i18n.current() or screen in self.screen_stack:
                return screen
            self.uninstall_screen("progress")  # drawn in the earlier language and not on show: start afresh
            screen.remove()
        self.install_screen(ProgressScreen(), "progress")
        return self.get_screen("progress")

    def apply_language(self, setting: str) -> None:
        """The screen on top redraws itself. Each one below gets a fresh copy when it comes back into view."""
        i18n.set_language(i18n.choose(setting, self.system_language()))
        self.log_file.info("Language chosen", language=i18n.current(), setting=setting or "automatic")
        if self.screen_stack:
            self.refresh_bindings()

    async def renew_screen(self, screen: Screen) -> None:
        """Replace a screen drawn in the earlier language, once it is back on top."""
        if self.screen is not screen or screen.language == i18n.current():
            return
        progress = self.is_screen_installed("progress") and self.get_screen("progress") is screen
        if progress and run_is_active(self.runner.view):
            return  # the run's screen keeps its words until the run is over
        fresh = ProgressScreen() if progress else screen.fresh()
        if fresh is None:
            screen.language = i18n.current()
            return
        await self.switch_screen(fresh)
        if progress:
            self.uninstall_screen("progress")
            await screen.remove()
            self.install_screen(fresh, "progress")

    def show_progress(self) -> None:
        screen = self.progress_screen()
        if self.screen is not screen:
            self.push_screen(screen)

    def retry_failed(self) -> None:
        failed = [i.package for i in self.runner.view.items if i.state is ItemState.FAILED]
        if failed:
            self.start_upgrade(failed)

    def show_no_winget(self, reason: str | None = None, too_old: bool = False) -> None:
        self.switch_screen(NoWingetScreen(reason, too_old))

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
        view = self.runner.view
        if not run_is_active(view):
            await self._quit_now()
            return
        if isinstance(self.screen, ConfirmDialog) and self.screen.dialog_title == _QUIT_TITLE:
            return
        text = t(_QUIT_DOWNLOADING if view.stage is Stage.DOWNLOADING else _QUIT_INSTALLING) + "\n\n" + t(_QUIT_KEEPS)
        dialog = ConfirmDialog(
            _QUIT_TITLE, text, (_QUIT_AFTER, _QUIT_NOW), danger=(_QUIT_NOW,), cancel_label=N_("Keep running")
        )
        self.push_screen(dialog, self._quit_answered)

    def _quit_answered(self, choice: str | None) -> None:
        if choice == _QUIT_NOW:
            self.log_file.warn("Quit now pressed during a run")
            self.call_later(self._quit_now)
        elif choice == _QUIT_AFTER:
            self.log_file.info("Quit after this package pressed")
            self._quit_when_finished = True
            self.runner.stop_after()

    async def _quit_now(self) -> None:
        await self.runner.shutdown()
        self.exit()
