"""Work out the stage from winget's English messages. Other languages stay unknown, never guessed."""

from __future__ import annotations

from .models import Stage


class StageDetector:
    _MARKERS = (
        ("Downloading ", Stage.DOWNLOADING),
        ("Successfully verified installer hash", Stage.VERIFYING),
        ("Starting package install", Stage.INSTALLING),
        ("Starting package uninstall", Stage.INSTALLING),
    )

    def feed(self, clean_line: str) -> Stage | None:
        text = clean_line.strip()
        for marker, stage in self._MARKERS:
            if text.startswith(marker):
                return stage
        return None
