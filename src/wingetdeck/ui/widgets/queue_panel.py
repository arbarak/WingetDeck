"""The queue, with up, down and remove for packages that have not started."""

from __future__ import annotations

from textual import on
from textual.containers import Horizontal, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Static

from ...core.queue import ItemState, RunItem

_MARKS = {
    ItemState.WAITING: (" ", " "),
    ItemState.ACTIVE: ("›", ">"),
    ItemState.DONE: ("✓", "x"),
    ItemState.DONE_RESTART: ("✓", "x"),
    ItemState.SKIPPED: ("–", "-"),
    ItemState.FAILED: ("✗", "!"),
    ItemState.STOPPED: ("■", "#"),
}
_NOTES = {
    ItemState.DONE_RESTART: "restart needed",
    ItemState.SKIPPED: "skipped",
    ItemState.FAILED: "failed",
    ItemState.STOPPED: "stopped",
}


def safe_id(package_id: str) -> str:
    """Widget ids allow fewer characters than package ids do."""
    return "".join(c if c.isascii() and (c.isalnum() or c in "_-") else "_" for c in package_id)


class QueuePanel(VerticalScroll):
    class Move(Message):
        def __init__(self, package_id: str, delta: int) -> None:
            super().__init__()
            self.package_id = package_id
            self.delta = delta

    class Remove(Message):
        def __init__(self, package_id: str) -> None:
            super().__init__()
            self.package_id = package_id

    def __init__(self, ascii_mode: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ascii_mode = ascii_mode
        self._signature: tuple = ()
        self._actions: dict[str, tuple[str, str]] = {}

    def show(self, items: tuple[RunItem, ...]) -> None:
        """Rebuilt only when something changed, so clicks are not lost during a fast download."""
        signature = tuple((i.package.id, i.state) for i in items)
        if signature == self._signature:
            return
        self._signature = signature
        self._actions = {}
        self.remove_children()
        self.mount(*[self._row(item) for item in items])

    def _row(self, item: RunItem) -> Horizontal:
        mark = _MARKS[item.state][1 if self.ascii_mode else 0]
        note = _NOTES.get(item.state)
        text = f"{mark} {item.package.name}" + (f" ({note})" if note else "")
        label = Static(text, classes=f"queue-name state-{item.state.value}", markup=False)
        if item.state is not ItemState.WAITING:
            return Horizontal(label, classes="queue-row")
        key = safe_id(item.package.id)
        up, down, remove = ("^", "v", "x") if self.ascii_mode else ("↑", "↓", "✕")
        self._actions[f"up-{key}"] = ("up", item.package.id)
        self._actions[f"down-{key}"] = ("down", item.package.id)
        self._actions[f"remove-{key}"] = ("remove", item.package.id)
        return Horizontal(
            label,
            Button(up, id=f"up-{key}", classes="queue-button", compact=True),
            Button(down, id=f"down-{key}", classes="queue-button", compact=True),
            Button(remove, id=f"remove-{key}", classes="queue-button queue-remove", compact=True),
            classes="queue-row",
        )

    @on(Button.Pressed, ".queue-button")
    def _pressed(self, event: Button.Pressed) -> None:
        event.stop()
        action = self._actions.get(event.button.id or "")
        if action is None:
            return
        kind, package_id = action
        if kind == "remove":
            self.post_message(self.Remove(package_id))
        else:
            self.post_message(self.Move(package_id, -1 if kind == "up" else 1))
