"""What has been upgraded, and going back to an earlier version."""

from __future__ import annotations

from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from ...core.queue import RunState
from ...core.safety import rollback_target
from ...core.store import HistoryEntry
from .dialogs import ConfirmDialog
from .logs import TranscriptScreen
from ...i18n import N_, t
from .base import DeckScreen, Footer, TitleBar

_ROLL_BACK = N_("Roll back")
# The history file keeps these words as they are. Only the screen shows them in the chosen language.
_OUTCOMES = {
    "done": N_("done"),
    "done_restart": N_("done, restart needed"),
    "skipped": N_("skipped"),
    "failed": N_("failed"),
    "stopped": N_("stopped"),
}


class HistoryScreen(DeckScreen):
    BINDINGS = [Binding("escape", "app.pop_screen", N_("Back"))]

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[HistoryEntry] = []

    def compose(self) -> ComposeResult:
        yield TitleBar()
        yield Static("", id="history-note", markup=False)
        yield OptionList(id="history-list", markup=False)
        with Horizontal(id="history-buttons"):
            yield Button(t("Roll back to the earlier version"), id="rollback", classes="blue")
            yield Button(t("See log"), id="see-log", classes="gray")
        yield Footer()

    def on_mount(self) -> None:
        self.entries = list(reversed(self.app.store.history()))
        listing = self.query_one(OptionList)
        listing.add_options(
            [
                Option(f"{e.when}  {e.name}  {e.from_version} → {e.to_version}  {t(_OUTCOMES.get(e.outcome, e.outcome))}  {e.code}")
                for e in self.entries
            ]
        )
        if self.entries:
            listing.highlighted = 0
        else:
            self._note(t("No upgrades have been recorded yet."))
        running = self.app.runner.view.state in (RunState.RUNNING, RunState.PAUSED)
        self.query_one("#rollback", Button).disabled = running or not self.entries
        self.query_one("#see-log", Button).disabled = not self.entries
        if running:
            self._note(t("Roll back is not available during an upgrade run."))

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
        self._note(t("Asking winget which versions of {name} it still has…", name=entry.name))
        try:
            versions = await app.backend.versions(entry.id)
        except Exception as e:  # said plainly here
            app.log_file.warn("Could not list versions", package=entry.id, error=repr(e))
            self._note(t("Could not ask winget for versions of {name}: {error}", name=entry.name, error=e))
            return
        target = rollback_target(entry, versions)
        if target is None:
            earlier = entry.from_version or t("the earlier version")
            self._note(
                t("{name} cannot be rolled back: {earlier} is no longer available from its source.", name=entry.name, earlier=earlier)
            )
            return
        self._note("")
        text = t(
            "This installs {name} {target} over {current}. "
            "Some apps do not support going backwards, and winget may offer the newer version again next time.",
            name=entry.name,
            target=target,
            current=entry.to_version,
        )

        def answered(choice: str | None) -> None:
            if choice == _ROLL_BACK:
                app.start_rollback(entry, target)

        app.push_screen(ConfirmDialog(N_("Roll back?"), text, (_ROLL_BACK,)), answered)
