"""One package: what winget knows about it, and pin, ignore and options."""

from __future__ import annotations

from dataclasses import replace

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ...winget.backend import PackageDetails
from ...winget.models import Package
from .package_options import PackageOptionsScreen

_DASH = "—"


def details_text(package: Package, details: PackageDetails) -> str:
    return (
        f"{package.name}\n{package.id}\n{package.installed} → {package.available}\n\n"
        f"Publisher: {details.publisher or _DASH}\n"
        f"Homepage: {details.homepage or _DASH}\n\n"
        f"Release notes:\n{details.release_notes or _DASH}"
    )


class DetailsScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, package: Package) -> None:
        super().__init__()
        self.package = package
        self.pinned = package.pinned

    def compose(self) -> ComposeResult:
        with Vertical(id="details"):
            with VerticalScroll(id="details-scroll"):
                yield Static("Asking winget…", id="details-text", markup=False)
            with Horizontal(id="details-buttons"):
                yield Button(self._pin_label(), id="pin", classes="blue")
                yield Button("Ignore", id="ignore", classes="gray")
                yield Button("Options", id="options", classes="gray")
                yield Button("Close", id="close", classes="gray")

    def _pin_label(self) -> str:
        return "Unpin" if self.pinned else "Pin"

    def on_mount(self) -> None:
        self.load()

    @work(exclusive=True, group="details")
    async def load(self) -> None:
        app = self.app
        text = self.query_one("#details-text", Static)
        try:
            details = await app.backend.show(self.package.id)
        except Exception as e:  # shown here, the rest of this panel still works
            app.log_file.warn("winget show failed", package=self.package.id, error=repr(e))
            text.update(f"{details_text(self.package, PackageDetails())}\n\nCould not ask winget: {e}")
            return
        text.update(details_text(self.package, details))

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        match event.button.id:
            case "close":
                self.dismiss(None)
            case "options":
                self.app.push_screen(PackageOptionsScreen(self.package))
            case "ignore":
                store = self.app.store
                settings = store.load_settings()
                store.save_settings(replace(settings, ignored=settings.ignored | {self.package.id}))
                self.app.log_file.info("Package ignored", package=self.package.id)
                self.dismiss(None)
            case "pin":
                self.toggle_pin()

    @work(exclusive=True, group="pin")
    async def toggle_pin(self) -> None:
        app = self.app
        try:
            if self.pinned:
                await app.backend.pin_remove(self.package.id)
            else:
                await app.backend.pin_add(self.package.id)
        except Exception as e:  # say why the button did nothing
            app.log_file.error("Pin change failed", package=self.package.id, error=repr(e))
            self.query_one("#details-text", Static).update(f"Could not change the pin: {e}")
            return
        self.pinned = not self.pinned
        self.query_one("#pin", Button).label = self._pin_label()
        app.log_file.info("Pin changed", package=self.package.id, pinned=self.pinned)
