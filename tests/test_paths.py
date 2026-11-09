from wingetdeck import paths
from wingetdeck.paths import resolve_data_dir, stamp


def test_portable_when_exe_dir_writable(tmp_path):
    d = resolve_data_dir(tmp_path / "app", tmp_path / "local")
    assert d.portable and d.root == tmp_path / "app" / "WingetDeck-data"


def test_falls_back_when_exe_dir_not_writable(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_is_writable", lambda p: False)
    d = resolve_data_dir(tmp_path / "app", tmp_path / "local")
    assert not d.portable and d.root == tmp_path / "local" / "WingetDeck"


def test_non_ascii_path_with_spaces_works(tmp_path):
    d = resolve_data_dir(tmp_path / "Dossier é 日本", tmp_path / "local")
    (d.logs / "x.log").write_text("ok", encoding="utf-8")
    assert (d.logs / "x.log").exists()


def test_folders_created_on_access(tmp_path):
    d = resolve_data_dir(tmp_path / "app", tmp_path / "local")
    assert d.state.is_dir() and d.snapshots.is_dir()


def test_stamps_never_repeat():
    assert len({stamp() for _ in range(50)}) == 50
