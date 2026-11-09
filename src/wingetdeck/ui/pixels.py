"""Pixel art drawn with half blocks. The logo is our own: a box with an arrow above it, and the word
Winget in our own letters."""

from __future__ import annotations

from math import ceil

from rich.style import Style
from rich.text import Text
from textual.widget import Widget

BOX = [
    ".......##.......",
    "......####......",
    ".....######.....",
    "....########....",
    ".......##.......",
    ".......##.......",
    "................",
    "..############..",
    ".#++++++++++++#.",
    "################",
    "#++++++##++++++#",
    "#++++++##++++++#",
    "#++++++##++++++#",
    "#++++++++++++++#",
    "################",
]

_LETTERS = {
    "W": ["#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"],
    "i": [".#.", "...", "##.", ".#.", ".#.", ".#.", "###"],
    "n": [".....", ".....", "####.", "#...#", "#...#", "#...#", "#...#"],
    "g": [".....", ".####", "#...#", "#...#", ".####", "....#", "####."],
    "e": [".....", ".....", ".###.", "#...#", "#####", "#....", ".###."],
    "t": [".#...", ".#...", "####.", ".#...", ".#...", ".#..#", "..##."],
}


def _word(word: str) -> list[str]:
    rows = ["" for _ in range(7)]
    for index, letter in enumerate(word):
        for row, pixels in enumerate(_LETTERS[letter]):
            gap = "." if index else ""
            rows[row] += gap + pixels.replace("#", "T")
    return rows


def _centred(rows: list[str], width: int) -> list[str]:
    return [row.center(width, ".") for row in rows]


WORD = _word("Winget")
LOGO = _centred(BOX, len(WORD[0])) + ["." * len(WORD[0])] + WORD
PALETTE = {"#": "#00ff22", "+": "#008f22", "T": "#ffffff"}


class PixelArt(Widget):
    """Two pixels per character cell, so the pixels come out square."""

    DEFAULT_CSS = "PixelArt { width: auto; height: auto; }"

    def __init__(
        self,
        art: list[str],
        palette: dict[str, str],
        ascii_mode: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.art = art
        self.palette = palette
        self.ascii_mode = ascii_mode

    def _cell(self, top: str, bottom: str) -> tuple[str, Style]:
        top_colour = self.palette.get(top)
        bottom_colour = self.palette.get(bottom)
        if self.ascii_mode:
            colour = top_colour or bottom_colour
            return ("#", Style(color=colour)) if colour else (" ", Style())
        if top_colour and bottom_colour:
            return "▀", Style(color=top_colour, bgcolor=bottom_colour)
        if top_colour:
            return "▀", Style(color=top_colour)
        if bottom_colour:
            return "▄", Style(color=bottom_colour)
        return " ", Style()

    def _lines(self) -> list[list[tuple[str, Style]]]:
        width = max(len(row) for row in self.art)
        rows = [row.ljust(width, ".") for row in self.art]
        if len(rows) % 2:
            rows.append("." * width)
        return [
            [self._cell(top, bottom) for top, bottom in zip(rows[y], rows[y + 1])]
            for y in range(0, len(rows), 2)
        ]

    def to_plain(self) -> list[str]:
        return ["".join(char for char, _ in line) for line in self._lines()]

    def render(self) -> Text:
        text = Text(no_wrap=True)
        for index, line in enumerate(self._lines()):
            if index:
                text.append("\n")
            for char, style in line:
                text.append(char, style=style)
        return text

    def get_content_width(self, container, viewport) -> int:
        return max(len(row) for row in self.art)

    def get_content_height(self, container, viewport, width) -> int:
        return ceil(len(self.art) / 2)
