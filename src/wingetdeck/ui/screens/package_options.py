"""Options for one package, overriding the defaults."""

from __future__ import annotations

from dataclasses import replace

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Static

from ...winget.models import Package
from ..widgets.options_form import OptionsForm
from .base import DeckScreen, TitleBar


class PackageOptionsScreen(DeckScreen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self, package: Package) -> None:
        super().__init__()
        self.package = package

    def compose(self) -> ComposeResult:
        settings = self.app.store.load_settings()
        options = settings.per_package.get(self.package.id, settings.defaults)
        yield TitleBar()
        with VerticalScroll(id="settings-body"):
            yield Static(f"Options for {self.package.name}", classes="form-title", markup=False)
            yield OptionsForm(options, id="package-form")
            with Horizontal(id="options-buttons"):
                yield Button("Save", id="save-options")
                yield Button("Use the defaults", id="clear-options", classes="gray")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        store = self.app.store
        settings = store.load_settings()
        chosen = dict(settings.per_package)
        if event.button.id == "save-options":
            chosen[self.package.id] = self.query_one(OptionsForm).value()
        elif event.button.id == "clear-options":
            chosen.pop(self.package.id, None)
        else:
            return
        store.save_settings(replace(settings, per_package=chosen))
        self.app.pop_screen()
