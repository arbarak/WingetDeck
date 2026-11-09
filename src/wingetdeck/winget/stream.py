"""Turn winget's terminal output into events. Pure: chunks in, events out.

Measured behaviour this relies on:
- winget also draws progress bars while updating its sources, before the package's download starts,
  so progress only counts once the download line has been seen.
- The download line holds a URL in every language. The later messages are translated, so any other
  finished line, or a full bar, ends the download stage. That matters: only the download may be frozen.
"""

from __future__ import annotations

import re

from .backend import Event, OutputEvent, ProgressEvent, StageEvent
from .models import Stage
from .parse import ProgressParser, strip_terminal_codes
from .stages import StageDetector

_URL = re.compile(r"https?://")
_SPINNER = {"-", "\\", "|", "/"}
_UNFINISHED_ESCAPE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*|\][^\x07\x1b]*\x1b?)?$")


class UpgradeStream:
    def __init__(self) -> None:
        self._progress = ProgressParser()
        self._stages = StageDetector()
        self._stage: Stage | None = None
        self._buffer = ""
        self._pending = ""
        self._download_over = False  # a bar was seen, or a later stage: no link can restart it

    def _set_stage(self, stage: Stage, out: list[Event]) -> None:
        if stage is not self._stage:
            self._stage = stage
            out.append(StageEvent(stage))

    def _on_line(self, text: str, out: list[Event]) -> None:
        line = text.rsplit("\r", 1)[-1].strip()
        if not line or line in _SPINNER:
            return
        stage = self._stages.feed(line)
        # Winget prints a package's agreement links first, so a link means the download has begun only
        # until a bar has been seen. In a language the detector cannot read, a link is all there is.
        if stage is None and self._stage is not Stage.DOWNLOADING and _URL.search(line):
            stage = Stage.DOWNLOADING
        if stage is None and self._stage is Stage.DOWNLOADING:
            stage = Stage.WORKING
        if stage is Stage.DOWNLOADING and self._download_over:
            stage = None
        if stage not in (None, Stage.DOWNLOADING, Stage.WORKING):
            self._download_over = True
        if stage is not None:
            self._set_stage(stage, out)
        out.append(OutputEvent(line))

    def feed(self, chunk: str) -> list[Event]:
        out: list[Event] = []
        data = self._pending + chunk
        unfinished = _UNFINISHED_ESCAPE.search(data)
        self._pending = data[unfinished.start() :] if unfinished else ""
        if unfinished:
            data = data[: unfinished.start()]
        readings = self._progress.feed(data)
        self._buffer += strip_terminal_codes(data).replace("\r\n", "\n")
        *lines, self._buffer = self._buffer.split("\n")

        # A chunk may hold the download line, the bar and the next message together. Bars seen before
        # the download line are winget updating its sources, and do not count.
        for line in lines:
            was_downloading = self._stage is Stage.DOWNLOADING
            self._on_line(line, out)
            if was_downloading and self._stage is not Stage.DOWNLOADING:
                self._note_bars(readings)
                self._add_progress(readings, out, before=self._last_stage_index(out))
                readings = []
        if self._stage is Stage.DOWNLOADING:
            self._note_bars(readings)
            self._add_progress(readings, out)
            if any(r.total_mb and r.percent == 100 for r in readings):
                self._set_stage(Stage.WORKING, out)
        return out

    def _note_bars(self, readings) -> None:
        if any(r.total_mb is not None or r.percent is not None for r in readings):
            self._download_over = True

    @staticmethod
    def _last_stage_index(out: list[Event]) -> int:
        for index in range(len(out) - 1, -1, -1):
            if isinstance(out[index], StageEvent):
                return index
        return len(out)

    @staticmethod
    def _add_progress(readings, out: list[Event], before: int | None = None) -> None:
        events = [ProgressEvent(r) for r in readings if r.total_mb is not None or r.percent is not None]
        if before is None:
            out.extend(events)
        else:
            out[before:before] = events

    def finish(self) -> list[Event]:
        out: list[Event] = []
        if self._buffer.strip():
            self._on_line(self._buffer, out)
        self._buffer = ""
        return out
