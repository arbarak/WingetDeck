import pytest

from wingetdeck.winget.settings_file import (
    SettingsUnreadable,
    enable_direct,
    read_downloader,
    undo,
)


def test_missing_file_created_with_only_network_key(tmp_path):
    p = tmp_path / "settings.json"
    change = enable_direct(p, tmp_path / "bak")
    assert read_downloader(p) == "wininet"
    assert not change.previous_existed and change.backup is None


def test_read_missing_file_is_none(tmp_path):
    assert read_downloader(tmp_path / "nope.json") is None


def test_comments_and_other_keys_preserved(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('// my comment\n{ "visual": {"progressBar":"accent"} }', encoding="utf-8")
    enable_direct(p, tmp_path / "bak")
    t = p.read_text(encoding="utf-8")
    assert "my comment" in t and "progressBar" in t and read_downloader(p) == "wininet"


def test_replaces_existing_downloader_value(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"network": {"downloader": "do", "other": 1}}', encoding="utf-8")
    change = enable_direct(p, tmp_path / "bak")
    assert read_downloader(p) == "wininet" and change.previous_value == "do"
    assert '"other"' in p.read_text(encoding="utf-8")


def test_adds_downloader_inside_existing_network_block(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('{"network": {"other": 1}}', encoding="utf-8")
    enable_direct(p, tmp_path / "bak")
    assert read_downloader(p) == "wininet" and '"other"' in p.read_text(encoding="utf-8")


def test_comment_containing_braces_is_not_confused(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text('// { not "network": this }\n{ "a": "// not a comment" }', encoding="utf-8")
    enable_direct(p, tmp_path / "bak")
    assert read_downloader(p) == "wininet" and "// not a comment" in p.read_text(encoding="utf-8")


def test_backup_written_with_dated_name(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{}", encoding="utf-8")
    change = enable_direct(p, tmp_path / "bak")
    assert change.backup.name.startswith("winget_settings_")
    assert change.backup.read_text(encoding="utf-8") == "{}"


def test_undo_restores_exact_bytes(tmp_path):
    p = tmp_path / "settings.json"
    original = '// keep\n{\n  "visual": {}\n}\n'
    p.write_text(original, encoding="utf-8")
    change = enable_direct(p, tmp_path / "bak")
    undo(p, change)
    assert p.read_text(encoding="utf-8") == original


def test_undo_when_no_file_existed_removes_it(tmp_path):
    p = tmp_path / "settings.json"
    change = enable_direct(p, tmp_path / "bak")
    undo(p, change)
    assert not p.exists()


def test_unparseable_file_is_not_touched(tmp_path):
    p = tmp_path / "settings.json"
    p.write_text("{ broken", encoding="utf-8")
    with pytest.raises(SettingsUnreadable):
        enable_direct(p, tmp_path / "bak")
    assert p.read_text(encoding="utf-8") == "{ broken"
