"""Shown instead of a crash when winget cannot be used on this PC."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

HELP = """\
WingetDeck upgrades apps through winget, and winget could not be started on this PC.

To get winget:
  1. Open the Microsoft Store and install or update "App Installer".
  2. Or download it from https://aka.ms/getwinget

Winget runs on Windows 10 1809 or newer and Windows 11. It cannot run on Server Core.
Then press Check again. There is no need to restart this app."""


class NoWingetScreen(Screen):
    def __init__(self, reason: str | None = None) -> None:
        super().__init__()
        self.reason = reason

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="○")
        with Vertical(id="no-winget-body"):
            text = HELP if not self.reason else f"{HELP}\n\nWhat happened: {self.reason}"
            yield Static(text, id="help", markup=False)
            with Horizontal(id="no-winget-buttons"):
                yield Button("Check again", id="check-again")
                yield Button("Quit", id="quit", classes="red")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "check-again":
            self.app.check_winget_again()
        elif event.button.id == "quit":
            self.app.exit()
