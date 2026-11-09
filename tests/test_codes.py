import pytest

from wingetdeck.winget.codes import APP_IN_USE_CODE, Outcome, explain
from wingetdeck.winget.models import Stage
from wingetdeck.winget.stages import StageDetector


@pytest.mark.parametrize("code,outcome", [
    (0, "SUCCESS"), (0x8A150109, "SUCCESS_RESTART"), (0x8A15010B, "SUCCESS_RESTART"),
    (0x8A15002B, "SKIPPED"), (0x8A15010A, "FAILED_RESTART_FIRST"), (0x8A15002C, "FAILED"),
    (0x8A150101, "FAILED_IN_USE"), (0x8A150103, "FAILED_IN_USE"), (0x8A150111, "FAILED_IN_USE"),
])
def test_outcomes(code, outcome):
    assert explain(code).outcome.name == outcome


def test_app_in_use_code_from_docs():
    assert explain(APP_IN_USE_CODE).outcome is Outcome.FAILED_IN_USE


def test_negative_exit_code_same_as_unsigned():
    assert explain(0x8A150109 - 2**32).outcome is Outcome.SUCCESS_RESTART


def test_message_comes_from_documented_table():
    e = explain(0x8A150105)
    assert e.hex_code == "0x8A150105" and "space" in e.message


def test_unknown_code_is_failed_with_hex():
    e = explain(0x12345)
    assert e.outcome is Outcome.FAILED and "0x00012345" in e.message


def test_stage_english_lines():
    d = StageDetector()
    assert d.feed("Downloading https://x/y.exe") is Stage.DOWNLOADING
    assert d.feed("Successfully verified installer hash") is Stage.VERIFYING
    assert d.feed("Starting package install...") is Stage.INSTALLING


def test_stage_unknown_language_never_guesses():
    assert StageDetector().feed("Paket wird installiert...") is None


def test_stage_ignores_lines_about_something_else():
    assert StageDetector().feed("Found Git [Git.Git] Version 1.0") is None
