"""The parts of the progress screen that move. Every number comes from winget; when there is no
number the bar shows an animation and the elapsed time, never an invented percentage."""

from __future__ import annotations

from collections import deque

from rich.text import Text

from ...i18n import N_, t
from textual.widget import Widget

from ...winget.models import Progress, Stage

_BLOCKS = " ▁▂▃▄▅▆▇█"
_ASCII_BLOCKS = " ..--==##"
_STEPS = 8
_BAR_RUN = 4


def clock(seconds: float) -> str:
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"


def sparkline(samples: list[float], width: int, ascii_mode: bool) -> tuple[str, str]:
    """Two rows of bars, newest on the right, scaled to the highest value on show."""
    blocks = _ASCII_BLOCKS if ascii_mode else _BLOCKS
    recent = samples[-width:] if width > 0 else []
    peak = max(recent, default=0) or 1
    top: list[str] = []
    bottom: list[str] = []
    for value in recent:
        height = round(value / peak * _STEPS * 2)
        bottom.append(blocks[min(height, _STEPS)])
        top.append(blocks[max(height - _STEPS, 0)])
    pad = " " * (width - len(recent))
    return pad + "".join(top), pad + "".join(bottom)


class Meter(Widget):
    """A caption, a small history graph, and the latest value."""

    DEFAULT_CSS = "Meter { width: 1fr; height: 2; }"
    _CAPTION = 9
    _VALUE = 11

    def __init__(self, caption: str, ascii_mode: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.caption = caption
        self.ascii_mode = ascii_mode
        self.samples: deque[float] = deque(maxlen=300)
        self.value = "—" if not ascii_mode else "-"

    def show(self, value: str | None, sample: float | None = None) -> None:
        self.value = value if value is not None else ("-" if self.ascii_mode else "—")
        if sample is not None:
            self.samples.append(sample)
        self.refresh()

    def clear(self) -> None:
        self.samples.clear()
        self.show(None)

    def render(self) -> Text:
        room = max(self.size.width - self._CAPTION - self._VALUE, 1)
        top, bottom = sparkline(list(self.samples), room, self.ascii_mode)
        return Text(
            f"{'':<{self._CAPTION}}{top}\n{self.caption:<{self._CAPTION}}{bottom}{self.value:>{self._VALUE}}",
            no_wrap=True,
        )


class PercentBar(Widget):
    DEFAULT_CSS = "PercentBar { width: 1fr; height: 2; }"

    def __init__(self, ascii_mode: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ascii_mode = ascii_mode
        self.percent: float | None = None
        self.sizes = ""
        self.elapsed = 0.0
        self.caption = ""
        self.moving = False
        self._frame = 0

    def show(self, progress: Progress | None, elapsed: float, caption: str, moving: bool) -> None:
        self.percent = progress.percent if progress else None
        self.sizes = ""
        if progress and progress.received_mb is not None and progress.total_mb is not None:
            self.sizes = f"{progress.received_mb:.0f} MB / {progress.total_mb:.0f} MB"
        self.elapsed = elapsed
        self.caption = caption
        self.moving = moving
        self.refresh()

    def tick(self) -> None:
        if self.percent is None and self.moving:
            self._frame += 1
            self.refresh()

    def render(self) -> Text:
        width = max(self.size.width, 1)
        full, empty = ("#", ".") if self.ascii_mode else ("█", "░")
        if self.percent is not None:
            filled = round(width * min(self.percent, 100) / 100)
            line = full * filled + empty * (width - filled)
            below = f"{self.percent:.0f}%  {self.sizes}".rstrip()
            return Text(f"{line}\n{below}", no_wrap=True)
        line_cells = [empty] * width
        if self.moving:
            start = self._frame % width
            for offset in range(min(_BAR_RUN, width)):
                line_cells[(start + offset) % width] = full
        below = f"{self.caption}  {clock(self.elapsed)}".strip()
        return Text("".join(line_cells) + "\n" + below, no_wrap=True)


class StageList(Widget):
    DEFAULT_CSS = "StageList { width: 1fr; height: auto; }"
    _ORDER = [
        (Stage.DOWNLOADING, N_("Download")),
        (Stage.VERIFYING, N_("Verify hash")),
        (Stage.INSTALLING, N_("Install")),
    ]

    def __init__(self, ascii_mode: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.ascii_mode = ascii_mode
        self.stage: Stage | None = None
        self.all_done = False

    def show(self, stage: Stage | None, all_done: bool) -> None:
        self.stage = stage
        self.all_done = all_done
        self.refresh(layout=True)

    def _lines(self) -> list[tuple[str, str]]:
        done, now = ("x", ">") if self.ascii_mode else ("✓", "›")
        position = next((n for n, (s, _) in enumerate(self._ORDER) if s is self.stage), -1)
        lines = []
        for index, (_, english) in enumerate(self._ORDER):
            label = t(english)
            if self.all_done or index < position:
                lines.append((f"{done} {label}", "$wd-lime"))
            elif index == position:
                lines.append((f"{now} {label}", "bold $wd-cyan"))
            else:
                lines.append((f"  {label}", "$wd-dim"))
        lines.append((f"{done if self.all_done else ' '} {t('Done')}", "$wd-lime" if self.all_done else "$wd-dim"))
        if self.stage is Stage.WORKING:
            lines[0] = (f"{now} {t('Working…')}" if not self.ascii_mode else f"{now} {t('Working')}", "bold $wd-cyan")
        return lines

    def render(self) -> Text:
        colours = self.app.get_css_variables()
        text = Text(no_wrap=True)
        for index, (line, style) in enumerate(self._lines()):
            if index:
                text.append("\n")
            bold = style.startswith("bold ")
            name = style.removeprefix("bold ").removeprefix("$")
            text.append(line, style=f"{'bold ' if bold else ''}{colours[name]}")
        return text

    def get_content_height(self, container, viewport, width) -> int:
        return len(self._ORDER) + 1
