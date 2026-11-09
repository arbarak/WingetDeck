"""The words on screen in English or French."""

import ast
import json
import string
from pathlib import Path

import pytest

from wingetdeck import i18n
from wingetdeck.core.logs import SessionLog
from wingetdeck.core.store import Settings, Store
from wingetdeck.locales.fr import FR

SRC = Path(__file__).resolve().parents[1] / "src" / "wingetdeck"


@pytest.fixture(autouse=True)
def english_after():
    yield
    i18n.set_language("en")


def test_english_is_the_text_itself():
    i18n.set_language("en")
    assert i18n.t("Refresh") == "Refresh"


def test_french_comes_from_the_catalogue():
    i18n.set_language("fr")
    assert i18n.t("Refresh") == FR["Refresh"]
    assert i18n.current() == "fr"


def test_text_without_a_translation_stays_english():
    i18n.set_language("fr")
    assert i18n.t("Some text nobody wrote down") == "Some text nobody wrote down"


def test_values_are_filled_in_after_translating():
    i18n.set_language("fr")
    text = i18n.t("{count} upgrade(s) available", count=3)
    assert "3" in text and text != "3 upgrade(s) available"
    i18n.set_language("en")
    assert i18n.t("{count} upgrade(s) available", count=3) == "3 upgrade(s) available"


def test_a_value_with_braces_is_not_read_as_a_placeholder():
    i18n.set_language("fr")
    assert "{x}" in i18n.t("Could not check for upgrades: {error}", error="{x}")


def test_mark_returns_the_text_unchanged():
    i18n.set_language("fr")
    assert i18n.N_("Refresh") == "Refresh"


@pytest.mark.parametrize(
    "setting,system,expected",
    [
        ("en", "fr-FR", "en"),
        ("fr", "en-US", "fr"),
        ("", "fr-FR", "fr"),
        ("", "fr-CA", "fr"),
        ("", "en-GB", "en"),
        ("", "ar-MA", "en"),
        ("", "", "en"),
        ("de", "fr-BE", "fr"),  # an unknown stored value is treated as automatic
    ],
)
def test_choose(setting, system, expected):
    assert i18n.choose(setting, system) == expected


def test_unknown_language_falls_back_to_english():
    i18n.set_language("xx")
    assert i18n.current() == "en"


# The catalogue must cover every text the code marks, with the same placeholders.


def _texts_in(node: ast.expr) -> list[str]:
    """The texts a call can be given: plain text, or either side of `a if x else b`. A name is a text marked
    with N_ where it was defined, so it is found there."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):
        return _texts_in(node.body) + _texts_in(node.orelse)
    return []


def _marked_texts() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in SRC.rglob("*.py"):
        if "locales" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("t", "N_")
                and node.args
            ):
                first = node.args[0]
                if node.func.id == "N_":
                    assert isinstance(first, ast.Constant), f"{path.name}:{node.lineno} N_ needs plain text"
                assert not isinstance(first, ast.JoinedStr), (
                    f"{path.name}:{node.lineno}: an f-string cannot be looked up. Use {{placeholders}} and values."
                )
                for text in _texts_in(first):
                    found[text] = f"{path.relative_to(SRC)}:{node.lineno}"
    return found


def _fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def test_there_are_marked_texts():
    assert len(_marked_texts()) > 150


def test_every_marked_text_has_a_french_version():
    missing = {text: where for text, where in _marked_texts().items() if text not in FR}
    assert not missing, "\n".join(f"{where}: {text!r}" for text, where in sorted(missing.items(), key=lambda x: x[1]))


def test_french_keeps_the_same_placeholders():
    wrong = [key for key, value in FR.items() if _fields(key) != _fields(value)]
    assert not wrong, wrong


def test_french_has_no_stale_entries():
    marked = _marked_texts()
    stale = [key for key in FR if key not in marked]
    assert not stale, stale


def test_french_avoids_characters_the_console_fonts_may_lack():
    # A curly apostrophe or a narrow no-break space is missing from some console fonts. The plain no-break space
    # is in every one, and keeps a colon or question mark from starting a line.
    bad = [value for value in FR.values() if any(c in value for c in "’ ")]
    assert not bad, bad


def test_french_signs_never_start_a_line():
    assert FR["Roll back?"].endswith(" ?")
    assert not [value for value in FR.values() if any(f" {sign}" in value for sign in ":?!;")]


def test_french_is_not_left_in_english():
    same = [key for key, value in FR.items() if key == value and len(key) > 12]
    assert not same, same


# The setting


def test_language_setting_is_saved_and_read(tmp_data):
    store = Store(tmp_data, SessionLog(tmp_data, False, {}))
    assert store.load_settings().language == ""
    store.save_settings(Settings(language="fr"))
    assert store.load_settings().language == "fr"


def test_a_language_of_the_wrong_type_is_refused(tmp_data):
    store = Store(tmp_data, SessionLog(tmp_data, False, {}))
    store.settings_path.write_text(json.dumps({"language": 3}), encoding="utf-8")
    assert store.load_settings().language == ""
    assert store.corruption_notes
