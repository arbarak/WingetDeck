"""Shown instead of a crash when winget cannot be used on this PC. It can also fix that, and asks before each step."""

from __future__ import annotations

import asyncio
import sys
import threading

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Static

from ...winget.repair import Offer, RepairCancelled, RepairError, device_architecture, open_store
from ...i18n import N_, t
from .base import DeckScreen, Footer, TitleBar
from .dialogs import ConfirmDialog

HELP = N_("""\
WingetDeck upgrades apps through winget, which could not be used here.

Get winget can sort this out, and it asks before each step:
  1. It tries to activate a winget that is already on this PC.
  2. If that is not enough, it finds the newest version made for this
     PC, then offers to download and install it from Microsoft's releases.

Or install "App Installer" from the Microsoft Store, then press Check again.
Winget needs Windows 10 1809 or newer, and cannot run on Server Core.""")

_ACTIVATE = N_("Activate winget")
_ACTIVATE_TEXT = N_(
    "Windows can have winget on a PC without having set it up for your account yet. WingetDeck can ask Windows to "
    "do that now.\n\nNothing is downloaded, and no admin rights are needed."
)
_INSTALL = N_("Download and install")
_COMMAND_OFF = N_(
    "App Installer {version} is on this PC, but its winget command is switched off. Open Windows Settings, then Apps, "
    "then Advanced app settings (on Windows 10, Apps & features), then App execution aliases. Turn on winget, then "
    "press Check again."
)
_NO_VERSION = N_(
    "No version of winget was found for this PC (Windows build {build}, {architecture}). Try the Microsoft Store."
)
_NOT_SHOWING = N_(
    "Winget was installed, but this PC is not showing it yet. Press Check again, or sign out of Windows and back in."
)
_CANCELLED = N_("Cancelled. Nothing was installed.")


def _offer_text(offer: Offer, build: int, architecture: str) -> str:
    return t(
        "This version is made for this PC: Windows build {build}, {architecture} processor.\n\n"
        "WingetDeck will download {size} MB from Microsoft's official releases on GitHub, check the "
        "checksum and Microsoft's signature, then install it for your Windows account. No admin rights are needed.\n\n"
        "It needs about {space} MB free while it works. The downloaded files are removed afterwards.",
        build=build,
        architecture=architecture,
        size=offer.total_megabytes,
        space=round(offer.space_needed / 1024 / 1024),
    )


class NoWingetScreen(DeckScreen):
    def __init__(self, reason: str | None = None, too_old: bool = False) -> None:
        super().__init__()
        self.reason = reason
        self.too_old = too_old
        self._cancel = threading.Event()

    def compose(self) -> ComposeResult:
        yield TitleBar()
        with VerticalScroll(id="no-winget-body", can_focus=False):  # a long error must not push the buttons out of reach
            text = t(HELP) if not self.reason else f"{t(HELP)}\n\n" + t("What happened: {reason}", reason=self.reason)
            yield Static(text, id="help", markup=False)
            yield Static("", id="repair-note", markup=False)
            with Horizontal(id="no-winget-buttons"):
                yield Button(t("Get winget"), id="get-winget")
                cancel = Button(t("Cancel"), id="cancel-get", classes="gray")
                cancel.display = False
                yield cancel
                yield Button("Microsoft Store", id="store", classes="gray")
                yield Button(t("Check again"), id="check-again", classes="gray")
                yield Button(t("Quit"), id="quit", classes="red")
        yield Footer()

    def fresh(self) -> DeckScreen | None:
        """Not while getting winget: closing this screen would cancel it."""
        busy = any(worker.is_running and worker.node is self for worker in self.app.workers)
        return None if busy else NoWingetScreen(self.reason, self.too_old)

    def on_mount(self) -> None:
        self.call_after_refresh(self.query_one("#no-winget-buttons").scroll_visible, animate=False)

    def on_unmount(self) -> None:
        self._cancel.set()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        button = event.button.id
        if button == "get-winget":
            self.get_winget()
        elif button == "cancel-get":
            self._cancel.set()
            self._note(t("Cancelling…"))
        elif button == "store":
            self._open_store()
        elif button == "check-again":
            self.app.check_winget_again()
        elif button == "quit":
            await self.app.action_quit()

    def _open_store(self) -> None:
        try:
            open_store()
        except RepairError as e:
            self._note(str(e))
        else:
            self._note(t('Install "App Installer" from the Store page, then press Check again.'))

    # These use query, not query_one: the screen can be closing while the work finishes, with its widgets gone.

    def _note(self, text: str) -> None:
        for note in self.query("#repair-note").results(Static):
            note.update(text)

    def _set_busy(self, busy: bool, cancellable: bool = False) -> None:
        for button in self.query("#get-winget, #store, #check-again").results(Button):
            button.disabled = busy
        for button in self.query("#cancel-get").results(Button):
            button.display = cancellable
            if cancellable:
                button.focus()
        if not busy:  # otherwise the focus stays on Quit, the only button left, and Enter would close the app
            for button in self.query("#get-winget").results(Button):
                button.focus()

    def _set_installing(self) -> None:
        """Windows cannot be stopped partway through, so neither Cancel nor Quit is on offer until it answers."""
        self.set_focus(None)
        self._set_busy(True)
        for button in self.query("#quit").results(Button):
            button.disabled = True

    @work(exclusive=True)
    async def get_winget(self) -> None:
        log = self.app.log_file
        self._set_busy(True)
        try:
            await self._repair()
        except RepairCancelled:
            log.info("Getting winget cancelled")
            self._note(t(_CANCELLED))
        except RepairError as e:
            log.error("Getting winget failed", error=str(e))
            self._note(str(e))
        finally:
            for button in self.query("#quit").results(Button):
                button.disabled = False
            self._set_busy(False)

    async def _repair(self) -> None:
        if not self.too_old and await self._activate():
            return
        build = sys.getwindowsversion().build
        architecture = device_architecture()
        self._note(t("Looking for a version of winget made for this PC…"))
        offer = await asyncio.to_thread(self.app.repair.find_offer, build, architecture)
        if offer is None:
            self.app.log_file.warn("No compatible winget found", build=build, architecture=architecture)
            self._note(t(_NO_VERSION, build=build, architecture=architecture))
            return
        self._note("")
        self.app.log_file.info("Compatible winget found", version=offer.version, min_build=offer.min_build)
        question = ConfirmDialog(
            t("Install winget {version}?", version=offer.version), _offer_text(offer, build, architecture), (_INSTALL,)
        )
        if await self.app.push_screen_wait(question) != _INSTALL:
            return
        await self._install(offer, architecture)

    async def _activate(self) -> bool:
        """True when there is nothing more to do, because winget now works or a download would not help."""
        question = ConfirmDialog(N_("Activate winget?"), _ACTIVATE_TEXT, (_ACTIVATE,))
        if await self.app.push_screen_wait(question) != _ACTIVATE:
            return True
        repair = self.app.repair
        self.app.log_file.info("Activating winget")
        self._note(t("Asking Windows to activate winget…"))
        try:
            await asyncio.to_thread(repair.activate)
        except RepairError as e:
            self.app.log_file.info("Activating winget did not work", error=str(e))
        if await asyncio.to_thread(self._winget_works):
            self.app.log_file.info("Winget activated")
            self.app.check_winget_again()
            return True
        version = await asyncio.to_thread(repair.app_installer_version)
        if version:
            self.app.log_file.warn("App Installer is present but winget cannot be found", version=version)
            self._note(t(_COMMAND_OFF, version=version))
            return True
        return False

    async def _install(self, offer: Offer, architecture: str) -> None:
        self._cancel = threading.Event()
        loop = asyncio.get_running_loop()

        def progress(text: str) -> None:
            loop.call_soon_threadsafe(self._show_progress, text)

        self.app.log_file.info("Installing winget", version=offer.version)
        self._set_busy(True, cancellable=True)
        await asyncio.to_thread(self.app.repair.download_and_install, offer, architecture, progress, self._cancel)
        self.app.log_file.info("Winget installed", version=offer.version)
        if await asyncio.to_thread(self._winget_works):
            self.app.check_winget_again()
        else:
            self._note(t(_NOT_SHOWING))

    def _show_progress(self, text: str) -> None:
        if self._cancel.is_set():
            return
        self._note(t(text))
        if text.startswith("Installing"):  # the English, as sent: see repair.download_and_install
            self._set_installing()

    def _winget_works(self) -> bool:
        backend = self.app.backend
        backend.refresh_capabilities()
        try:
            return backend.capabilities() is not None
        except Exception as e:  # a winget that still misbehaves is the same as one not yet there
            self.app.log_file.warn("Winget still cannot be used", error=repr(e))
            return False
