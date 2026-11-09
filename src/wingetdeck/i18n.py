"""The words on screen, in English or French.

Each text is looked up by its English wording, so the English is never kept twice and a text with no French yet
still shows, in English. Logs stay in English, so a report reads the same whoever sends it.

Arabic is not offered: the Windows console has no right-to-left support, so its words come out reversed.
"""

from __future__ import annotations

from .locales.fr import FR

LANGUAGES = {"en": "English", "fr": "Français"}
_TABLES: dict[str, dict[str, str]] = {"fr": FR}
_current = "en"


def N_(text: str) -> str:
    """Marks a text that is translated later, where it is shown. The catalogue test finds it by this name."""
    return text


def choose(setting: str, system: str) -> str:
    """The stored choice if there is one, otherwise the language Windows shows, otherwise English."""
    if setting in LANGUAGES:
        return setting
    code = system.split("-")[0].lower()
    return code if code in LANGUAGES else "en"


def set_language(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else "en"


def current() -> str:
    return _current


def t(text: str, **values: object) -> str:
    table = _TABLES.get(_current)
    found = table.get(text, text) if table else text
    return found.format(**values) if values else found
