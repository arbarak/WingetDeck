"""The package table."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header


class PackagesScreen(Screen):
    def __init__(self, source: str | None) -> None:
        super().__init__()
        self.source = source

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="○")
        yield Footer()
