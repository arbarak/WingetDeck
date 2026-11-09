import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from wingetdeck.core.logs import SessionLog
from wingetdeck.winget import real
from wingetdeck.winget.backend import (
    Capabilities,
    FinishedEvent,
    OutputEvent,
    ProgressEvent,
    StageEvent,
    UpgradeOptions,
)
from wingetdeck.winget.capabilities import detect_capabilities, parse_flags
from wingetdeck.winget.models import ChangeKind, Package, Stage
from wingetdeck.winget.parse import parse_show, parse_table_column, parse_versions
from wingetdeck.winget.real import RealBackend, WingetError, build_upgrade_args, find_winget, resolve_truncated
from wingetdeck.winget.stream import UpgradeStream

FIX = Path(__file__).parent / "fixtures"
ALL_FLAGS = frozenset({
    "--silent", "--interactive", "--scope", "--architecture", "--force", "--uninstall-previous",
    "--skip-dependencies", "--include-pinned", "--include-unknown", "--accept-package-agreements",
    "--accept-source-agreements", "--custom", "--override", "--disable-interactivity",
})


def raw(name):
    with (FIX / name).open(encoding="utf-8", newline="") as f:
        return f.read()


def caps(flags=ALL_FLAGS):
    return Capabilities("v1.29.380", frozenset(flags), True, False, False)


def pkg(i="Git.Git", source="winget"):
    return Package("Git", i, "1.0", "1.1", source, ChangeKind.MINOR)


def test_args_exact_id_and_source():
    a = build_upgrade_args(pkg(), UpgradeOptions(), caps())
    assert a[:6] == ["upgrade", "--id", "Git.Git", "-e", "-s", "winget"]
    assert "--disable-interactivity" in a and "--silent" in a


def test_args_without_source_has_no_source_flag():
    assert "-s" not in build_upgrade_args(pkg(source=None), UpgradeOptions(), caps())


def test_agreement_flags_only_with_consent():
    assert "--accept-package-agreements" not in build_upgrade_args(pkg(), UpgradeOptions(), caps())
    a = build_upgrade_args(pkg(), UpgradeOptions(accept_agreements=True), caps())
    assert "--accept-package-agreements" in a and "--accept-source-agreements" in a


def test_flags_missing_from_old_winget_are_dropped():
    a = build_upgrade_args(pkg(), UpgradeOptions(include_pinned=True), caps(flags={"--silent"}))
    assert "--include-pinned" not in a and "--disable-interactivity" not in a


def test_options_map_to_flags():
    o = UpgradeOptions(silent=False, interactive=True, scope="user", architecture="x64", force=True,
                       uninstall_previous=True, skip_dependencies=True, custom="/a b", override="/c")
    a = build_upgrade_args(pkg(), o, caps())
    assert "--interactive" in a and "--silent" not in a and "--force" in a
    assert a[a.index("--scope") + 1] == "user" and a[a.index("--architecture") + 1] == "x64"
    assert a[a.index("--custom") + 1] == "/a b" and a[a.index("--override") + 1] == "/c"
    assert "--uninstall-previous" in a and "--skip-dependencies" in a


def test_interactive_run_does_not_disable_interactivity():
    a = build_upgrade_args(pkg(), UpgradeOptions(silent=False, interactive=True), caps())
    assert "--disable-interactivity" not in a


def test_parse_flags_from_real_help():
    flags = parse_flags((FIX / "en_upgrade_help.txt").read_text(encoding="utf-8"))
    assert {"--silent", "--include-pinned", "--disable-interactivity", "--uninstall-previous"} <= flags


def test_detect_missing_winget_returns_none():
    def run(args):
        raise FileNotFoundError

    assert detect_capabilities(run) is None


def test_detect_reads_version_and_flags(monkeypatch):
    monkeypatch.setattr("wingetdeck.winget.capabilities.pty_available", lambda: True)

    def run(args):
        return "v1.29.380\n" if args == ["--version"] else "--silent  x\n --force y"

    c = detect_capabilities(run)
    assert c.version == "v1.29.380" and c.flags == {"--silent", "--force"} and c.live_progress


def test_live_progress_false_without_pty(monkeypatch):
    monkeypatch.setattr("wingetdeck.winget.capabilities.pty_available", lambda: False)
    assert not detect_capabilities(lambda a: "v1.0").live_progress


def test_parse_sources_from_real_list():
    assert parse_table_column((FIX / "en_source_list.txt").read_text(encoding="utf-8"), 0) == [
        "msstore", "winget", "winget-font"]


def test_parse_no_pins_is_empty():
    assert parse_table_column((FIX / "en_pin_list.txt").read_text(encoding="utf-8"), 1) == []


def test_parse_show_real_output():
    d = parse_show((FIX / "en_show_git.txt").read_text(encoding="utf-8"))
    assert d.publisher == "The Git Development Community"
    assert d.homepage == "https://gitforwindows.org/"
    assert "urgent security" in d.release_notes and "Release Notes Url" not in d.release_notes


def test_parse_show_missing_fields_are_none():
    d = parse_show("Found X [Y]\nVersion: 1\n")
    assert d.publisher is None and d.release_notes is None


def test_parse_versions():
    assert parse_versions("Found X [Y]\nVersion\n-------\n2.0\n1.0\n") == ["2.0", "1.0"]


def test_resolve_truncated_uses_exported_ids():
    p = Package("Long", "Some.Very.Long.Appl…", "1", "2", "winget", ChangeKind.MINOR, truncated_id=True)
    fixed = resolve_truncated([p, pkg()], {"Some.Very.Long.Application", "Git.Git"})
    assert fixed[0].id == "Some.Very.Long.Application" and not fixed[0].truncated_id and fixed[1] == pkg()


def test_resolve_truncated_ambiguous_stays_flagged():
    p = Package("Long", "Some.…", "1", "2", "winget", ChangeKind.MINOR, truncated_id=True)
    assert resolve_truncated([p], {"Some.A", "Some.B"})[0].truncated_id


def feed_all(text, step=41):
    s, out = UpgradeStream(), []
    for i in range(0, len(text), step):
        out += s.feed(text[i:i + step])
    return out + s.finish()


@pytest.mark.parametrize("name", ["pty_install_nullsoft.txt", "pty_install_msi.txt", "pty_install_portable.txt"])
def test_stream_real_install_ends_in_installing(name):
    stages = [e.stage for e in feed_all(raw(name)) if isinstance(e, StageEvent)]
    assert stages[0] is Stage.DOWNLOADING and stages[-1] is Stage.INSTALLING
    assert Stage.VERIFYING in stages and len(stages) == len(set(stages))


def test_stream_real_install_has_progress_only_inside_download():
    events = feed_all(raw("pty_install_nullsoft.txt"))
    index_dl = next(i for i, e in enumerate(events) if isinstance(e, StageEvent) and e.stage is Stage.DOWNLOADING)
    index_v = next(i for i, e in enumerate(events) if isinstance(e, StageEvent) and e.stage is Stage.VERIFYING)
    progress = [i for i, e in enumerate(events) if isinstance(e, ProgressEvent)]
    assert progress and all(index_dl < i < index_v for i in progress)


def test_stream_ignores_source_update_bars_before_download():
    bars = "  ██  1024 KB / 3.73 MB\r  ███  3 MB / 3.73 MB\r"
    events = feed_all(bars)
    assert not [e for e in events if isinstance(e, ProgressEvent)]


def test_stream_output_lines_skip_spinner():
    lines = [e.line for e in feed_all(raw("pty_install_portable.txt")) if isinstance(e, OutputEvent)]
    assert any("Found jq" in x for x in lines) and "Successfully installed" in lines
    assert not any(x.strip() in ("-", "\\", "|", "/") for x in lines)


def test_stream_other_language_url_means_downloading_then_text_ends_it():
    s = UpgradeStream()
    events = s.feed("Gefunden Git [Git.Git]\r\nHerunterladen https://x/y.exe\r\n")
    assert [e.stage for e in events if isinstance(e, StageEvent)] == [Stage.DOWNLOADING]
    events = s.feed("Installer-Hash erfolgreich verifiziert\r\n")
    assert [e.stage for e in events if isinstance(e, StageEvent)] == [Stage.WORKING]


def test_stream_full_bar_leaves_downloading():
    s = UpgradeStream()
    s.feed("Downloading https://x/y.exe\r\n")
    stages = [e.stage for e in s.feed("  ███  7.54 MB / 7.54 MB\r") if isinstance(e, StageEvent)]
    assert stages == [Stage.WORKING]


@pytest.mark.real
async def test_scan_against_real_winget_returns_packages(tmp_data):
    b = RealBackend(SessionLog(tmp_data, False, {}))
    assert (await b.scan(None)).packages is not None
    assert "winget" in await b.sources()
    assert (await b.show("Git.Git")).publisher


@pytest.mark.asyncio
async def test_piped_fallback_streams_and_finishes(tmp_data, monkeypatch):
    if not shutil.which("winget"):
        pytest.skip("winget not installed")
    b = RealBackend(SessionLog(tmp_data, False, {}), force_piped=True)
    h = real.RealHandle(b._log, "probe", [b.winget, "--version"], use_pty=False)
    events = [e async for e in h.events()]
    assert isinstance(events[-1], FinishedEvent) and events[-1].exit_code == 0
    assert any(isinstance(e, OutputEvent) and e.line.startswith("v") for e in events)


@pytest.mark.asyncio
async def test_pty_streams_and_finishes(tmp_data):
    if not shutil.which("winget"):
        pytest.skip("winget not installed")
    b = RealBackend(SessionLog(tmp_data, False, {}))
    h = real.RealHandle(b._log, "probe", [b.winget, "--version"], use_pty=True)
    events = [e async for e in h.events()]
    assert isinstance(events[-1], FinishedEvent) and events[-1].exit_code == 0


@pytest.mark.real_download
async def test_pty_download_streams_progress_events(tmp_data):
    b = RealBackend(SessionLog(tmp_data, False, {}))
    target = tempfile.mkdtemp()
    h = real.RealHandle(b._log, "wk", [b.winget, "download", "--id", "wkhtmltopdf.wkhtmltox", "-e", "-d", target,
                                       "--disable-interactivity"], use_pty=True)
    events = [e async for e in h.events()]
    assert any(isinstance(e, ProgressEvent) for e in events) and events[-1].exit_code == 0
    shutil.rmtree(target, ignore_errors=True)


def test_output_after_the_app_loop_closed_is_ignored(tmp_data):
    """winget can outlive the window when an installer is left to finish."""
    import asyncio
    import sys

    log = SessionLog(tmp_data, False, {})
    handle = real.RealHandle(log, "A", [sys.executable, "-c", "pass"], use_pty=False)
    loop = asyncio.new_event_loop()
    handle._loop = loop
    handle._queue = asyncio.Queue()
    loop.close()
    handle._worker()


def _winget_in(folder):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "winget.exe").write_bytes(b"")
    return str(folder / "winget.exe")


def test_winget_is_found_on_the_path(tmp_path):
    found = _winget_in(tmp_path / "tools")
    assert find_winget({"PATH": str(tmp_path / "tools")}) == found


def test_winget_off_the_path_is_found_where_windows_keeps_it(tmp_path):
    found = _winget_in(tmp_path / "Microsoft" / "WindowsApps")
    assert find_winget({"PATH": str(tmp_path / "empty"), "LOCALAPPDATA": str(tmp_path)}) == found


def test_no_winget_anywhere_finds_nothing(tmp_path):
    assert find_winget({"PATH": str(tmp_path), "LOCALAPPDATA": str(tmp_path)}) is None


def test_a_winget_exe_in_the_current_folder_is_never_run(tmp_path, monkeypatch):
    """Double-clicking the exe in Downloads makes that the current folder, and anything can land in Downloads."""
    _winget_in(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert find_winget({"PATH": ".;", "LOCALAPPDATA": str(tmp_path / "none")}) is None


def test_check_again_finds_winget_installed_after_the_app_started(tmp_data, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    backend = RealBackend(SessionLog(tmp_data, False, {}))
    assert backend.winget is None

    found = _winget_in(tmp_path / "local" / "Microsoft" / "WindowsApps")
    backend.refresh_capabilities()
    assert backend.winget == found


def test_a_path_given_by_the_caller_survives_check_again(tmp_data):
    backend = RealBackend(SessionLog(tmp_data, False, {}), winget_path="C:/chosen/winget.exe")
    backend.refresh_capabilities()
    assert backend.winget == "C:/chosen/winget.exe"


def test_a_hung_winget_gives_up_soon_and_says_so(tmp_data, monkeypatch):
    backend = RealBackend(SessionLog(tmp_data, False, {}), winget_path="winget")
    waited = []

    def hang(command, **kw):
        waited.append(kw["timeout"])
        raise subprocess.TimeoutExpired(command, kw["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(WingetError, match="did not answer"):
        backend.capabilities()
    assert waited == [real._PROBE_TIMEOUT]
    assert real._PROBE_TIMEOUT <= 60
