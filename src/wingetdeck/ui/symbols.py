"""Plain-character output, for consoles whose font cannot draw symbols.

Everything the app and Textual's own widgets draw passes through to_ascii on its way to the terminal, so
no widget has to remember. Every character keeps its width, or the columns would stop lining up.
"""

from __future__ import annotations

import unicodedata

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
