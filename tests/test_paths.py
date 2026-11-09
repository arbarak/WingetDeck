import subprocess

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


def test_elevated_run_never_trusts_the_folder_beside_the_exe(tmp_path):
    d = resolve_data_dir(tmp_path / "app", tmp_path / "local", elevated=True)
    assert not d.portable and d.root == tmp_path / "local" / "WingetDeck"


def test_data_folder_that_is_a_link_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_is_redirected", lambda p: p.name == paths.PORTABLE_FOLDER)
    d = resolve_data_dir(tmp_path / "app", tmp_path / "local")
    assert not d.portable


def test_real_directory_link_is_detected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)
    assert paths._is_redirected(link) and not paths._is_redirected(target)


def test_a_folder_denied_by_permissions_is_refused_quickly(tmp_path):
    """Windows calls this folder writable, and Python's tempfile then retries for ever. It must answer."""
    import os
    import subprocess
    import sys

    folder = tmp_path / "locked"
    folder.mkdir()
    user = os.environ["USERNAME"]
    subprocess.run(["icacls", str(folder), "/deny", f"{user}:(OI)(CI)(WD,AD)"], check=True, capture_output=True)
    code = "import sys, pathlib; from wingetdeck.paths import _is_writable; print(_is_writable(pathlib.Path(sys.argv[1])))"
    try:
        done = subprocess.run([sys.executable, "-c", code, str(folder)], capture_output=True, text=True, timeout=20)
    finally:
        subprocess.run(["icacls", str(folder), "/remove:d", user], check=True, capture_output=True)
    assert done.stdout.strip() == "False"
