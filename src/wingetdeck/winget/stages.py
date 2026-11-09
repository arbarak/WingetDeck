"""Work out the stage from winget's messages, in any language it ships. A line it does not know stays unknown."""

from __future__ import annotations

from .message_table import DOWNLOADING, INSTALLING, UNINSTALLING, VERIFIED
from .models import Stage


def plain(text: str) -> str:
    """Spelling differences that are not worth missing a message over."""
    return text.replace("\u2019", "'").replace("\u00a0", " ").strip()


def _start_of(message: str) -> str:
    """Some languages carry on after the dots, such as "... Merci de patienter." """
    return plain(message.replace("\u2026", "...").split("...")[0])


_DOWNLOADS = tuple(plain(m) + " " for m in DOWNLOADING)  # the address follows, so a line of just the word is not this
_MARKERS = (
    (_DOWNLOADS, Stage.DOWNLOADING),
    (tuple(plain(m) for m in VERIFIED), Stage.VERIFYING),
    (tuple(_start_of(m) for m in INSTALLING + UNINSTALLING), Stage.INSTALLING),
)


class StageDetector:
    def feed(self, clean_line: str) -> Stage | None:
        text = plain(clean_line)
        for markers, stage in _MARKERS:
            if text.startswith(markers):
                return stage
        return None
