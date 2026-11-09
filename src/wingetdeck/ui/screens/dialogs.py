"""A question with buttons. Dismisses with the chosen text, or None for Cancel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmDialog(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        text: str,
        choices: tuple[str, ...],
        danger: tuple[str, ...] = (),
        cancel_label: str = "Cancel",
    ) -> None:
        super().__init__()
        self.dialog_title = title
        self.text = text
        self.choices = choices
        self.danger = danger
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.dialog_title, id="dialog-title", markup=False)
            yield Static(self.text, id="dialog-text", markup=False)
            with Horizontal(id="dialog-buttons"):
                for index, choice in enumerate(self.choices):
                    classes = "red" if choice in self.danger else "blue"
                    yield Button(choice, id=f"choice-{index}", classes=classes)
                yield Button(self.cancel_label, id="cancel", classes="gray")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self.dismiss(self.choices[int(event.button.id.split("-")[1])])

    def action_cancel(self) -> None:
        self.dismiss(None)
