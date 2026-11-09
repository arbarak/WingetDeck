"""Output for consoles whose font cannot draw every symbol.

Everything the app and Textual's own widgets draw passes through one of these on its way to the terminal, so
no widget has to remember. Every character keeps its width, or the columns would stop lining up.

to_ascii is for fonts that have almost nothing. basic_symbols is for the classic console's usual fonts, which
draw box lines and half blocks but show an empty box for anything they lack, such as the edges of a button.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable

from rich.cells import cell_len

_GROUPS = {
    "-": "─━═▔—–−‐",
    "_": "▁▂▃",
    "=": "▄▅▆",
    "#": "▀▇█▉▊■□▪▓▒",
    ".": "░·•∙",
    "|": "│┃║▏▎▍▌▋▐▕",
    "+": "┌┐└┘╭╮╰╯├┤┬┴┼╔╗╚╝┏┓┗┛",
    "~": "…",
    "*": "●◉↻⟳★",
    "o": "○◌",
    "x": "✓✔✕✖×",
    "!": "✗✘⚠",
    ">": "→›»▶▸",
    "<": "←‹«◀◂",
    "^": "↑▲▴",
    "v": "↓▼▾",
    "'": "‘’",
    '"': "“”",
    " ": "  ",
}


class _Table(dict):
    def __missing__(self, code: int) -> str:
        char = chr(code)
        if code < 128:
            value = char
        else:
            width = cell_len(char)
            plain = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode()
            value = plain if plain and len(plain) == width else "?" * width
        self[code] = value
        return value


_TABLE = _Table({ord(char): plain for plain, chars in _GROUPS.items() for char in chars})


def to_ascii(text: str) -> str:
    return text.translate(_TABLE)


# The nearest characters to try, best first. A character that fits nothing here falls back to to_ascii.
_STAND_INS: dict[str, tuple[str, ...]] = {
    "▔": (" ",),
    "▁": (" ",),
    "▂": ("▄",),
    "▃": ("▄",),
    "▅": ("▄",),
    "▆": ("█",),
    "▇": ("█",),
    "▀": ("█",),
    "▄": ("█",),
    "▉": ("█",),
    "▊": ("█",),
    "▋": ("█", "▌"),
    "▌": ("█",),
    "▍": ("▌",),
    "▎": ("▌",),
    "▏": ("▌", "│"),
    "▐": ("█",),
    "▕": ("▐", "│"),
    "▖": ("▄",),
    "▗": ("▄",),
    "▘": ("▀",),
    "▝": ("▀",),
    "▙": ("█",),
    "▛": ("█",),
    "▜": ("█",),
    "▟": ("█",),
    "░": ("▒", "▓"),
    "━": ("─", "═"),
    "┃": ("│", "║"),
    "┏": ("┌", "╔"),
    "┓": ("┐", "╗"),
    "┗": ("└", "╚"),
    "┛": ("┘", "╝"),
    "╭": ("┌",),
    "╮": ("┐",),
    "╰": ("└",),
    "╯": ("┘",),
    "╍": ("─",),
    "╏": ("│",),
    "✓": ("√",),
    "✔": ("√",),
    "✕": ("×",),
    "✖": ("×",),
    "✗": ("×",),
    "✘": ("×",),
    "●": ("•",),
    "↻": (" ",),
    "⟳": (" ",),
    "🔎": ("  ",),
}


def stand_ins() -> list[str]:
    return list(_STAND_INS)


class _FontTable(dict):
    def __init__(self, has_glyph: Callable[[str], bool]) -> None:
        super().__init__()
        self._has = has_glyph

    def __missing__(self, code: int) -> str:
        char = chr(code)
        value = char if code < 128 or self._has(char) else self._nearest(char)
        self[code] = value
        return value

    def _nearest(self, char: str) -> str:
        for option in _STAND_INS.get(char, ()):
            if all(ord(c) < 128 or self._has(c) for c in option):
                return option
        return to_ascii(char)


def basic_symbols(has_glyph: Callable[[str], bool]) -> Callable[[str], str]:
    """Replace only what this font cannot draw."""
    table = _FontTable(has_glyph)
    return lambda text: text.translate(table)


def lacks_any_stand_in(char: str) -> bool:
    """For when the font cannot be read: treat everything with a stand-in as missing."""
    return char not in _STAND_INS
