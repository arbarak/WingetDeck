"""How the window's size and state are reflected: the width bands, the title, the taskbar."""

from __future__ import annotations

from typing import Literal

from ..core.queue import ItemState, RunState
from ..core.runner import RunView

WIDE = 120
MEDIUM = 80
MIN_WIDTH = 50
MIN_HEIGHT = 16
_APP = "WingetDeck"


def layout_band(width: int) -> Literal["wide", "medium", "narrow"]:
    if width >= WIDE:
        return "wide"
    return "medium" if width >= MEDIUM else "narrow"


def title_text(view: RunView | None) -> str:
    """What shows on the taskbar button while minimised. No number means no percent."""
    if view is None or view.state is RunState.IDLE:
        return _APP
    if view.state is RunState.FINISHED:
        return f"Done · {_APP}"
    finished = sum(1 for i in view.items if i.state not in (ItemState.WAITING, ItemState.ACTIVE))
    position = f"{min(finished + 1, len(view.items))}/{len(view.items)}"
    if view.state is RunState.PAUSED:
        return f"{position} · Paused · {_APP}"
    if view.progress is not None and view.progress.percent is not None:
        return f"{position} · {view.progress.percent:.0f}% · {_APP}"
    return f"{position} · {_APP}"


def taskbar_code(view: RunView | None) -> str:
    """Terminal progress: state 0 none, 1 percent, 3 busy with no number, 4 paused."""
    def code(state: int, value: int = 0) -> str:
        return f"\x1b]9;4;{state};{value}\x1b\\"

    if view is None or view.state in (RunState.IDLE, RunState.FINISHED):
        return code(0)
    percent = view.progress.percent if view.progress is not None else None
    value = round(percent) if percent is not None else 0
    if view.state is RunState.PAUSED:
        return code(4, value)
    return code(1, value) if percent is not None else code(3)
