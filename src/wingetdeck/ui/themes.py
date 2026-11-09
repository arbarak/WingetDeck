"""Colours. The green dark theme is the one in the approved mock."""

from __future__ import annotations

from textual.theme import Theme

DEFAULT_THEME = "wingetdeck-green"

# Extra colours the screens use. Built-in Textual themes get these too.
DEFAULT_VARIABLES = {
    "wd-key": "#ff9a1f",
    "wd-lime": "#66dd00",
    "wd-cyan": "#00c8e8",
    "wd-dim": "#8a8a8a",
    "wd-major": "#ff5a5a",
    "wd-minor": "#ffd75f",
    "wd-green": "#00b956",
    "wd-green-top": "#39e888",
    "wd-green-low": "#007a38",
    "wd-green-text": "#04140a",
    "wd-blue": "#0a6fdc",
    "wd-blue-top": "#4a9dee",
    "wd-blue-low": "#063f7f",
    "wd-red": "#c0144c",
    "wd-red-top": "#ee4b7d",
    "wd-red-low": "#7c0a30",
    "wd-gray": "#2c2c2c",
    "wd-gray-top": "#444444",
    "wd-gray-low": "#111111",
    "wd-off": "#262626",
    "wd-off-text": "#777777",
    "wd-list": "#111111",
}

THEMES = [
    Theme(
        name=DEFAULT_THEME,
        primary="#0a6fdc",
        secondary="#a855f7",
        warning="#ffd75f",
        error="#ff5a5a",
        success="#66dd00",
        accent="#00c8e8",
        foreground="#dcdcdc",
        background="#050505",
        surface="#101010",
        panel="#0c1a22",
        dark=True,
    ),
    Theme(
        name="wingetdeck-amber",
        primary="#b86e00",
        secondary="#d9a441",
        warning="#ffd75f",
        error="#ff5a5a",
        success="#9ccf3a",
        accent="#ffb000",
        foreground="#f0dcc0",
        background="#0d0905",
        surface="#17110a",
        panel="#241a0e",
        dark=True,
        variables={"wd-cyan": "#ffb000", "wd-blue": "#b86e00", "wd-blue-top": "#e09a2e", "wd-blue-low": "#6e4100"},
    ),
    Theme(
        name="wingetdeck-light",
        primary="#0a6fdc",
        secondary="#7c3aed",
        warning="#a86a00",
        error="#c0144c",
        success="#1a7f37",
        accent="#00708a",
        foreground="#1b1b1b",
        background="#f7f7f7",
        surface="#ffffff",
        panel="#dde7ee",
        dark=False,
        variables={
            "wd-key": "#b35900",
            "wd-lime": "#1a7f37",
            "wd-cyan": "#00708a",
            "wd-dim": "#5f5f5f",
            "wd-major": "#c0144c",
            "wd-minor": "#8a5a00",
            "wd-list": "#e9e9e9",
            "wd-gray": "#d5d5d5",
            "wd-gray-top": "#eeeeee",
            "wd-gray-low": "#aaaaaa",
            "wd-off": "#e0e0e0",
            "wd-off-text": "#8a8a8a",
        },
    ),
]
