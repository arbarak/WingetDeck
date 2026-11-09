"""What has been upgraded, and going back to an earlier version."""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, OptionList, Static
from textual.widgets.option_list import Option

from ...core.queue import RunState
from ...core.safety import rollback_target
from ...core.store import HistoryEntry
from .dialogs import ConfirmDialog
from .logs import TranscriptScreen

_ROLL_BACK = "Roll back"


class HistoryScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[HistoryEntry] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True, icon="○")
        yield Static("", id="history-note", markup=False)
        yield OptionList(id="history-list", markup=False)
        with Horizontal(id="history-buttons"):
            yield Button("Roll back to the earlier version", id="rollback", classes="blue")
            yield Button("See log", id="see-log", classes="gray")
        yield Footer()

    def on_mount(self) -> None:
        self.entries = list(reversed(self.app.store.history()))
        listing = self.query_one(OptionList)
        listing.add_options(
            [
                Option(f"{e.when}  {e.name}  {e.from_version} → {e.to_version}  {e.outcome}  {e.code}")
                for e in self.entries
            ]
        )
        if self.entries:
            listing.highlighted = 0
        else:
            self._note("No upgrades have been recorded yet.")
        running = self.app.runner.view.state in (RunState.RUNNING, RunState.PAUSED)
        self.query_one("#rollback", Button).disabled = running or not self.entries
        self.query_one("#see-log", Button).disabled = not self.entries
        if running:
            self._note("Roll back is not available during an upgrade run.")

    def _note(self, text: str) -> None:
        self.query_one("#history-note", Static).update(text)

    def _selected(self) -> HistoryEntry | None:
        index = self.query_one(OptionList).highlighted
        return self.entries[index] if index is not None and index < len(self.entries) else None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        entry = self._selected()
        if entry is None:
            return
        if event.button.id == "rollback":
            self.check_rollback(entry)
        elif event.button.id == "see-log":
            path = Path(entry.log_path) if entry.log_path else None
            self.app.push_screen(TranscriptScreen(entry.id, path))

    @work(exclusive=True, group="rollback")
    async def check_rollback(self, entry: HistoryEntry) -> None:
        app = self.app
        self._note(f"Asking winget which versions of {entry.name} it still has…")
        try:
            versions = await app.backend.versions(entry.id)
        except Exception as e:  # said plainly here
            app.log_file.warn("Could not list versions", package=entry.id, error=repr(e))
            self._note(f"Could not ask winget for versions of {entry.name}: {e}")
            return
        target = rollback_target(entry, versions)
        if target is None:
            earlier = entry.from_version or "the earlier version"
            self._note(
                f"{entry.name} cannot be rolled back: {earlier} is no longer available from its source."
            )
            return
        self._note("")
        text = (
            f"This installs {entry.name} {target} over {entry.to_version}. "
            "Some apps do not support going backwards, and winget may offer the newer version again next time."
        )

        def answered(choice: str | None) -> None:
            if choice == _ROLL_BACK:
                app.start_rollback(entry, target)

        app.push_screen(ConfirmDialog("Roll back?", text, (_ROLL_BACK,)), answered)
