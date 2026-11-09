"""Faults found by running the app on another PC: Windows 10 in French, with the agreements accepted."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from wingetdeck import cli
from wingetdeck.core.logs import SessionLog
from wingetdeck.winget.backend import ProgressEvent, StageEvent
from wingetdeck.winget.models import Stage
from wingetdeck.winget.parse import parse_show
from wingetdeck.winget.real import RealBackend, RealHandle
from wingetdeck.winget.stages import StageDetector
from wingetdeck.winget.stream import UpgradeStream


def backend_with_agreements(tmp_data, monkeypatch):
    backend = RealBackend(SessionLog(tmp_data, False, {}), winget_path="winget")
    backend.accept_source_agreements = True
    flags = {"--disable-interactivity", "--accept-source-agreements"}
    monkeypatch.setattr(backend, "capabilities", lambda: SimpleNamespace(flags=flags))
    sent = []

    def run(args, timeout=0):
        sent.append(args)
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr(backend, "_run_sync", run)
    return backend, sent


async def test_updating_sources_works_after_the_agreements_were_accepted(tmp_data, monkeypatch):
    backend, sent = backend_with_agreements(tmp_data, monkeypatch)
    await backend.update_sources()
    assert "--accept-source-agreements" not in sent[0], "winget rejects this as invalid arguments, 0x8A150002"
    assert "--disable-interactivity" in sent[0]


async def test_listing_sources_works_after_the_agreements_were_accepted(tmp_data, monkeypatch):
    backend, sent = backend_with_agreements(tmp_data, monkeypatch)
    await backend.sources()
    assert "--accept-source-agreements" not in sent[0]


async def test_commands_that_need_the_agreements_still_get_them(tmp_data, monkeypatch):
    backend, sent = backend_with_agreements(tmp_data, monkeypatch)
    await backend.show("A.B")
    await backend.pins()
    await backend.export_snapshot("x.json")
    assert all("--accept-source-agreements" in args for args in sent)


# The exact lines from the French transcripts
FRENCH = (
    ("Téléchargement en cours https://github.com/ip7z/7zip/releases/download/26.06/7z2606-x64.exe", Stage.DOWNLOADING),
    ("Le code de hachage de l’installation a été vérifié avec succès", Stage.VERIFYING),
    ("Démarrage du package d’installation... Merci de patienter.", Stage.INSTALLING),
)


@pytest.mark.parametrize("line,stage", FRENCH)
def test_french_stages_are_understood(line, stage):
    assert StageDetector().feed(line) is stage


def test_a_straight_apostrophe_counts_the_same_as_a_curly_one():
    assert StageDetector().feed("Démarrage du package d'installation... Merci de patienter.") is Stage.INSTALLING


@pytest.mark.parametrize(
    "line,stage",
    [
        ("Download läuft https://x/y.exe", Stage.DOWNLOADING),
        ("ダウンロード中 https://x/y.exe", Stage.DOWNLOADING),
        ("パッケージのインストールを開始しています...", Stage.INSTALLING),
    ],
)
def test_other_languages_winget_speaks_are_understood(line, stage):
    assert StageDetector().feed(line) is stage


@pytest.mark.parametrize(
    "line",
    [
        "Trouvé 7-Zip [7zip.7zip] Version 26.06",
        "Installé correctement",
        "La licence d’utilisation de cette application vous est octroyée par son propriétaire.",
        "Téléchargement en cours",  # no address follows, so it is not the download starting
        "Downloading",
    ],
)
def test_other_lines_are_not_mistaken_for_a_stage(line):
    assert StageDetector().feed(line) is None


def test_details_are_read_in_french():
    text = (
        "Trouvé 7-Zip [7zip.7zip]\n"
        "Version : 26.06\n"
        "Publisher : Igor Pavlov\n"
        "Page d’accueil : https://www.7-zip.org\n"
        "Notes de publication :\n"
        "  Corrections\n"
        "Installateur :\n"
    )
    details = parse_show(text)
    assert details.publisher == "Igor Pavlov"
    assert details.homepage == "https://www.7-zip.org"
    assert details.release_notes == "Corrections"


def test_the_log_records_that_the_app_was_closed(tmp_data, monkeypatch):
    log = SessionLog(tmp_data, False, {})
    said = []
    monkeypatch.setattr(log, "info", lambda message, **kw: said.append(message))
    monkeypatch.setattr(cli, "install_close_handler", lambda stop: None)
    app = SimpleNamespace(run=lambda: None, _exception=None, return_code=0)
    assert cli._run(app, log, SimpleNamespace(emergency_stop=lambda: None)) == 0
    assert said == ["Session closed"]


def test_a_real_french_upgrade_goes_through_every_stage():
    stream = UpgradeStream()
    raw = (Path(__file__).parent / "fixtures" / "pty_install_fr.txt").read_bytes().decode("utf-8")
    events = stream.feed(raw) + stream.finish()
    assert [e.stage for e in events if isinstance(e, StageEvent)] == [
        Stage.DOWNLOADING,
        Stage.WORKING,
        Stage.VERIFYING,
        Stage.INSTALLING,
    ]
    assert any(isinstance(e, ProgressEvent) for e in events)


def idle_handle(tmp_data):
    """A handle with no winget behind it: only its list of processes is looked at."""
    handle = RealHandle.__new__(RealHandle)
    handle._log = SessionLog(tmp_data, False, {})
    handle._package_id = "A"
    handle.pid = 1
    return handle


def test_a_handle_can_tell_when_an_installer_is_running(tmp_data, monkeypatch):
    handle = idle_handle(tmp_data)
    monkeypatch.setattr("wingetdeck.winget.real.tree_names", lambda pid: ["conhost.exe"])
    assert not handle.installer_running()
    monkeypatch.setattr("wingetdeck.winget.real.tree_names", lambda pid: ["conhost.exe", "setup.exe"])
    assert handle.installer_running()


def test_when_the_process_list_cannot_be_read_an_installer_is_assumed(tmp_data, monkeypatch):
    handle = idle_handle(tmp_data)

    def denied(pid):
        raise OSError("denied")

    monkeypatch.setattr("wingetdeck.winget.real.tree_names", denied)
    assert handle.installer_running()


def test_closing_the_window_with_the_x_is_logged_before_anything_is_stopped(tmp_data, monkeypatch):
    """Windows ends the process soon after, so the log is written first."""
    log = SessionLog(tmp_data, False, {})
    order = []
    monkeypatch.setattr(log, "info", lambda message, **kw: order.append(message))
    handlers = []
    monkeypatch.setattr(cli, "install_close_handler", handlers.append)
    app = SimpleNamespace(run=lambda: None, _exception=None, return_code=0)
    cli._run(app, log, SimpleNamespace(emergency_stop=lambda: order.append("stop")))
    order.clear()
    handlers[0]()
    assert order == ["Window closed", "stop"]
