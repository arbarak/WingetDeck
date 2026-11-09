"""Read winget's text output. Tables are read by column position, never by header words,
because winget translates its headers on non-English Windows."""

from __future__ import annotations

import re
import unicodedata

from .models import ChangeKind, Package, Progress, ScanResult

_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_UNFINISHED_ESCAPE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*|\][^\x07\x1b]*\x1b?)?$")
_DASHES = re.compile(r"^-{5,}\s*$")
_TASKBAR = re.compile(r"\x1b\]9;4;(\d+);(\d+)")
_SIZES = re.compile(r"(\d+(?:\.\d+)?)\s*(KB|MB|GB)\s*/\s*(\d+(?:\.\d+)?)\s*(KB|MB|GB)")
_HIDDEN = re.compile(r"^(\d+) package\(s\) have version numbers that cannot be determined")
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)")
_TRUNCATED = "…"
_MB = {"KB": 1 / 1024, "MB": 1.0, "GB": 1024.0}


def strip_terminal_codes(text: str) -> str:
    return _ESCAPE.sub("", text)


def display_width(text: str) -> int:
    return sum(_char_width(c) for c in text)


def _char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    return 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1


def _cut(line: str, starts: list[int]) -> list[str] | None:
    """Split a line at display positions. None if a boundary lands inside other text."""
    cells: list[str] = []
    current: list[str] = []
    pos = 0
    boundaries = list(starts[1:])
    for char in line:
        if boundaries and pos >= boundaries[0]:
            cells.append("".join(current))
            current = []
            boundaries.pop(0)
        current.append(char)
        pos += _char_width(char)
    cells.append("".join(current))
    for cell in cells[:-1]:
        if cell and not cell.endswith(" ") and not cell.endswith(_TRUNCATED):
            return None
    cells.extend("" for _ in boundaries)
    return [c.strip() for c in cells]


def _column_starts(header: str) -> list[int]:
    starts: list[int] = []
    pos = 0
    previous_space = True
    for char in header:
        is_space = char.isspace()
        if previous_space and not is_space:
            starts.append(pos)
        previous_space = is_space
        pos += _char_width(char)
    return starts


def _version_parts(version: str) -> list[int] | None:
    match = _VERSION.match(version.strip())
    return [int(p) for p in match.group(1).split(".")] if match else None


def classify_change(installed: str, available: str) -> ChangeKind:
    old, new = _version_parts(installed), _version_parts(available)
    if old is None or new is None:
        return ChangeKind.UNKNOWN
    old, new = old + [0, 0], new + [0, 0]
    if old[0] != new[0]:
        return ChangeKind.MAJOR
    if old[1] != new[1]:
        return ChangeKind.MINOR
    return ChangeKind.PATCH


def _row(line: str, starts: list[int], explicit: bool) -> Package | None:
    if len(starts) < 4:
        return None
    cells = _cut(line, starts)
    if cells is None:
        return None
    name, package_id, installed, available = cells[:4]
    source = cells[4] if len(cells) > 4 else ""
    if not (name and package_id and installed and available) or " " in package_id or " " in source:
        return None
    return Package(
        name=name,
        id=package_id,
        installed=installed,
        available=available,
        source=source or None,
        change=classify_change(installed, available),
        explicit_only=explicit,
        truncated_id=package_id.endswith(_TRUNCATED),
    )


def _visible_lines(text: str) -> list[str]:
    # A carriage return redraws the line, so only the text after the last one is really there.
    lines = []
    for raw in strip_terminal_codes(text).replace("\r\n", "\n").split("\n"):
        lines.append(raw.rsplit("\r", 1)[-1].rstrip())
    return lines


def parse_upgrade_table(text: str) -> ScanResult:
    packages: list[Package] = []
    notes: list[str] = []
    hidden = 0
    lines = _visible_lines(text)
    tables_seen = 0
    starts: list[int] | None = None
    for index, line in enumerate(lines):
        if _DASHES.match(line) and index > 0:
            starts = _column_starts(lines[index - 1])
            tables_seen += 1
            if notes and notes[-1] == lines[index - 1].strip():
                notes.pop()  # the header was collected before we knew it was one
            continue
        if not line.strip():
            starts = None
            continue
        package = _row(line, starts, tables_seen > 1) if starts else None
        if package:
            packages.append(package)
            continue
        starts = None  # a line that is not a row ends the table
        notes.append(line.strip())
        match = _HIDDEN.match(line.strip())
        if match:
            hidden = int(match.group(1))
    return ScanResult(packages=packages, unknown_hidden=hidden, notes=notes)


class ProgressParser:
    """Turns a stream of terminal output into progress readings. Chunks may split anywhere."""

    def __init__(self) -> None:
        self._text = ""
        self._pending = ""

    def feed(self, chunk: str) -> list[Progress]:
        data = self._pending + chunk
        unfinished = _UNFINISHED_ESCAPE.search(data)
        self._pending = data[unfinished.start():] if unfinished else ""
        if unfinished:
            data = data[: unfinished.start()]
        found: list[tuple[int, Progress]] = []
        for match in _TASKBAR.finditer(data):
            if match.group(1) == "1":
                found.append((match.start(), Progress(percent=float(match.group(2)))))
        readings = [p for _, p in found]
        self._text += strip_terminal_codes(data)
        last_end = 0
        for match in _SIZES.finditer(self._text):
            received = float(match.group(1)) * _MB[match.group(2)]
            total = float(match.group(3)) * _MB[match.group(4)]
            percent = min(100.0, received / total * 100) if total else None
            readings.append(Progress(percent, received, total))
            last_end = match.end()
        self._text = self._text[last_end:][-200:]
        return readings


def parse_table_column(text: str, column: int) -> list[str]:
    """One column of any winget table, read by position."""
    lines = _visible_lines(text)
    values: list[str] = []
    for index, line in enumerate(lines):
        if not _DASHES.match(line) or index == 0:
            continue
        starts = _column_starts(lines[index - 1])
        for row in lines[index + 1:]:
            if not row.strip() or _DASHES.match(row):
                break
            cells = _cut(row, starts)
            if cells is None or column >= len(cells) or not cells[column]:
                break
            values.append(cells[column])
        break
    return values


def parse_show(text: str):
    """Details from `winget show`, whichever language winget speaks."""
    from .backend import PackageDetails
    from .message_table import HOMEPAGE, PUBLISHER, RELEASE_NOTES
    from .stages import plain

    def after(line: str, labels: tuple[str, ...]) -> str | None:
        """What follows the label on this line, or None when it is a different line."""
        text = plain(line)
        for label in labels:
            if text.startswith(plain(label)):
                return text[len(plain(label)):].strip()
        return None

    lines = _visible_lines(text)
    publisher = homepage = None
    notes: list[str] = []
    in_notes = False
    for line in lines:
        if in_notes:
            if line.startswith((" ", "\t")):
                notes.append(line.strip())
                continue
            in_notes = False
        if (value := after(line, PUBLISHER)) is not None:
            publisher = value or None
        elif (value := after(line, HOMEPAGE)) is not None:
            homepage = value or None
        elif (value := after(line, RELEASE_NOTES)) is not None:
            if value:
                notes.append(value)
            in_notes = True
    return PackageDetails(publisher, homepage, "\n".join(notes) or None)


def parse_versions(text: str) -> list[str]:
    lines = _visible_lines(text)
    for index, line in enumerate(lines):
        if _DASHES.match(line):
            return [ln.strip() for ln in lines[index + 1:] if ln.strip()]
    return []
