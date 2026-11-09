"""Getting winget onto a PC: what gets offered, and everything that must stop a bad file being installed."""

import hashlib
import io
import json
import subprocess
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

from wingetdeck.winget import repair
from wingetdeck.winget.repair import Asset, Offer, RepairCancelled, RepairError, WingetRepair

BASE = "https://github.com/microsoft/winget-cli/releases/download"
NEEDED_FAMILY = "Windows.Universal"
PUBLISHER = "CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US"
MICROSOFT = "CN=Microsoft Corporation, O=Microsoft Corporation, L=Redmond, S=Washington, C=US"


def manifest(min_build=17763, architectures=("x64", "x86", "arm64"), name="Microsoft.DesktopAppInstaller"):
    packages = "".join(
        f'<Package Type="application" Version="1.0.0.0" Architecture="{a}" FileName="AppInstaller_{a}.msix">'
        f'<b4:Dependencies><b4:TargetDeviceFamily Name="{NEEDED_FAMILY}" MinVersion="10.0.{min_build}.0"/>'
        "</b4:Dependencies></Package>"
        for a in architectures
    )
    resource = (
        '<Package Type="resource" Version="1.0.0.0" ResourceId="split.language-bg" FileName="bg.msix">'
        '<b4:Dependencies><b4:TargetDeviceFamily Name="Windows.Universal" MinVersion="10.0.1.0"/></b4:Dependencies>'
        "</Package>"
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Bundle xmlns="http://schemas.microsoft.com/appx/2013/bundle" '
        'xmlns:b4="http://schemas.microsoft.com/appx/2018/bundle">'
        f'<Identity Name="{name}" Publisher="{PUBLISHER}" Version="2026.1.1.0"/>'
        f"<Packages>{resource}{packages}</Packages></Bundle>"
    ).encode()


def bundle_bytes(**kw):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("AppxMetadata/AppxBundleManifest.xml", manifest(**kw))
        z.writestr("AppInstaller_x64.msix", b"package")
    return out.getvalue()


def deps_bytes(names=("x64/VCLibs_x64.appx", "x64/Runtime_x64.appx", "x86/VCLibs_x86.appx", "arm64/VCLibs_arm64.appx")):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name in names:
            z.writestr(name, b"dependency " + name.encode())
    return out.getvalue()


def sha(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Response(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(data)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class Web:
    """A pretend GitHub. Honours Range requests, and records every address that was asked for."""

    def __init__(self):
        self.files = {}
        self.releases = []
        self.asked = []

    def add_release(self, tag, bundle=None, deps=None, prerelease=False, draft=False, digest=True):
        bundle = bundle_bytes() if bundle is None else bundle
        deps = deps_bytes() if deps is None else deps
        assets = []
        for name, data in ((repair.BUNDLE_NAME, bundle), (repair.DEPENDENCIES_NAME, deps)):
            url = f"{BASE}/{tag}/{name}"
            self.files[url] = data
            entry = {"name": name, "browser_download_url": url, "size": len(data)}
            if digest:
                entry["digest"] = sha(data)
            assets.append(entry)
        self.releases.append({"tag_name": tag, "prerelease": prerelease, "draft": draft, "assets": assets})

    def open(self, url, headers=None):
        self.asked.append(url)
        if url == repair.RELEASES_URL:
            return Response(json.dumps(self.releases).encode())
        data = self.files[url]
        wanted = (headers or {}).get("Range")
        if wanted:
            start, end = wanted.removeprefix("bytes=").split("-")
            return Response(data[int(start) : int(end) + 1], 206)
        return Response(data)


class Shell:
    """A pretend PowerShell. Each call is recorded, so a test can see what would have been installed."""

    def __init__(self, signer=MICROSOFT, status="Valid", fail=None, version=""):
        self.signer, self.status, self.fail, self.version = signer, status, fail, version
        self.calls = []
        self.checked = []

    def __call__(self, script, env=None, timeout=None):
        self.calls.append((script, dict(env or {})))
        if self.fail and self.fail in script:
            raise RepairError("Windows refused it")
        if "Get-AuthenticodeSignature" in script:
            self.checked.append(env["WINGETDECK_FILE"])
            return f"{self.status}|{self.signer}"
        if "Get-AppxPackage" in script:
            return self.version
        return ""

    def installs(self):
        return [env for script, env in self.calls if "Add-AppxPackage -Path" in script]


def make(web=None, shell=None, tmp_path=None):
    return WingetRepair(open_url=(web or Web()).open, powershell=shell or Shell(), work_root=tmp_path)


def offer_for(web, shell, tmp_path, build=19045, arch="x64"):
    return WingetRepair(open_url=web.open, powershell=shell, work_root=tmp_path).find_offer(build, arch)


# Finding a version


def test_the_newest_stable_version_is_offered(tmp_path):
    web = Web()
    web.add_release("v1.30.1-preview", prerelease=True)
    web.add_release("v1.29.380")
    web.add_release("v1.28.1")
    offer = offer_for(web, Shell(), tmp_path)
    assert offer.version == "v1.29.380"
    assert offer.total_size == offer.bundle.size + offer.dependencies.size
    assert offer.min_build == 17763


def test_a_version_needing_newer_windows_is_passed_over_for_one_that_fits(tmp_path):
    web = Web()
    web.add_release("v2.0.0", bundle=bundle_bytes(min_build=26100))
    web.add_release("v1.29.380", bundle=bundle_bytes(min_build=17763))
    assert offer_for(web, Shell(), tmp_path, build=19045).version == "v1.29.380"
    assert offer_for(web, Shell(), tmp_path, build=26100).version == "v2.0.0"


def test_a_version_without_this_cpu_is_passed_over(tmp_path):
    web = Web()
    web.add_release("v2.0.0", bundle=bundle_bytes(architectures=("x64",)))
    web.add_release("v1.29.380")
    assert offer_for(web, Shell(), tmp_path, arch="arm64").version == "v1.29.380"


def test_nothing_is_offered_when_no_version_fits(tmp_path):
    web = Web()
    web.add_release("v1.29.380", bundle=bundle_bytes(min_build=26100))
    assert offer_for(web, Shell(), tmp_path, build=17763) is None


@pytest.mark.parametrize("kw", [{"prerelease": True}, {"draft": True}, {"digest": False}])
def test_previews_drafts_and_files_without_a_checksum_are_never_offered(tmp_path, kw):
    web = Web()
    web.add_release("v1.29.380", **kw)
    assert offer_for(web, Shell(), tmp_path) is None


def test_a_release_on_another_address_is_never_offered(tmp_path):
    web = Web()
    web.add_release("v1.29.380")
    for asset in web.releases[0]["assets"]:
        asset["browser_download_url"] = "https://example.com/" + asset["name"]
    assert offer_for(web, Shell(), tmp_path) is None


@pytest.mark.parametrize(
    "start",
    [
        b'<!DOCTYPE a [<!ENTITY x "x">]>',
        b'<!ENTITY x "x">',
    ],
)
def test_a_manifest_that_defines_entities_is_refused_before_it_is_parsed(tmp_path, start):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("AppxMetadata/AppxBundleManifest.xml", start + manifest())
    web = Web()
    web.add_release("v1.29.380", bundle=out.getvalue())
    assert offer_for(web, Shell(), tmp_path) is None


def test_a_wide_character_manifest_is_refused(tmp_path):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("AppxMetadata/AppxBundleManifest.xml", manifest().decode().encode("utf-16"))
    web = Web()
    web.add_release("v1.29.380", bundle=out.getvalue())
    assert offer_for(web, Shell(), tmp_path) is None


def test_only_a_little_of_the_package_is_read_to_check_it(tmp_path):
    web = Web()
    big = io.BytesIO()
    with zipfile.ZipFile(big, "w", zipfile.ZIP_STORED) as z:
        z.writestr("AppxMetadata/AppxBundleManifest.xml", manifest())
        z.writestr("AppInstaller_x64.msix", b"x" * 3_000_000)
    web.add_release("v1.29.380", bundle=big.getvalue())
    read = []
    original = web.open

    def counting(url, headers=None):
        response = original(url, headers)
        read.append(len(response.getvalue()) if url != repair.RELEASES_URL else 0)
        return response

    assert WingetRepair(open_url=counting, powershell=Shell(), work_root=tmp_path).find_offer(19045, "x64")
    assert sum(read) < 500_000


def test_a_server_that_ignores_partial_requests_is_an_error_not_a_long_download(tmp_path):
    web = Web()
    web.add_release("v1.29.380")
    original = web.open

    def whole_file(url, headers=None):
        return original(url, None if url != repair.RELEASES_URL else headers)

    with pytest.raises(RepairError):
        WingetRepair(open_url=whole_file, powershell=Shell(), work_root=tmp_path).find_offer(19045, "x64")


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ({"PROCESSOR_ARCHITECTURE": "AMD64"}, "x64"),
        ({"PROCESSOR_ARCHITECTURE": "ARM64"}, "arm64"),
        ({"PROCESSOR_ARCHITECTURE": "x86"}, "x86"),
        ({"PROCESSOR_ARCHITECTURE": "x86", "PROCESSOR_ARCHITEW6432": "AMD64"}, "x64"),
        ({"PROCESSOR_ARCHITECTURE": "x86", "PROCESSOR_ARCHITEW6432": "ARM64"}, "arm64"),
        ({}, None),
    ],
)
def test_the_real_cpu_is_used_even_from_the_32_bit_exe(given, expected):
    assert repair.device_architecture(given) == expected


# Addresses


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/microsoft/winget-cli/releases/download/v1/x",
        "https://release-assets.githubusercontent.com/github-production-release-asset/1/x",
        "https://objects.githubusercontent.com/x",
        "https://api.github.com/repos/microsoft/winget-cli/releases",
    ],
)
def test_github_addresses_are_allowed(url):
    assert repair.address_allowed(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/microsoft/winget-cli/x",
        "https://github.com.example.com/x",
        "https://example.com/github.com/x",
        "file:///C:/Windows/System32/x",
        "ftp://github.com/x",
    ],
)
def test_other_addresses_are_refused(url):
    assert not repair.address_allowed(url)


def test_a_redirect_to_another_site_is_refused():
    request = urllib.request.Request("https://github.com/microsoft/winget-cli/releases/download/v1/x")
    with pytest.raises(RepairError):
        repair.CheckedRedirects().redirect_request(
            request, None, 302, "Found", {}, "https://example.com/evil.msixbundle"
        )


def test_a_redirect_within_github_is_followed():
    request = urllib.request.Request("https://github.com/microsoft/winget-cli/releases/download/v1/x")
    followed = repair.CheckedRedirects().redirect_request(
        request, None, 302, "Found", {}, "https://release-assets.githubusercontent.com/x"
    )
    assert followed.full_url == "https://release-assets.githubusercontent.com/x"


# Downloading and installing


def ready(tmp_path, shell=None, **release):
    web = Web()
    web.add_release("v1.29.380", **release)
    shell = shell or Shell()
    tool = WingetRepair(open_url=web.open, powershell=shell, work_root=tmp_path)
    return web, shell, tool, tool.find_offer(19045, "x64")


def go(tool, offer, progress=None, cancel=None, arch="x64"):
    tool.download_and_install(offer, arch, progress or (lambda text: None), cancel or threading.Event())


def test_a_good_download_is_installed_with_the_dependencies_for_this_cpu(tmp_path):
    _, shell, tool, offer = ready(tmp_path)
    go(tool, offer)
    [install] = shell.installs()
    assert install["WINGETDECK_BUNDLE"].endswith(repair.BUNDLE_NAME)
    dependencies = install["WINGETDECK_DEPENDENCIES"].split("|")
    assert sorted(d.rsplit("\\", 1)[-1] for d in dependencies) == ["Runtime_x64.appx", "VCLibs_x64.appx"]


def test_every_file_is_checked_for_a_signature_before_anything_is_installed(tmp_path):
    _, shell, tool, offer = ready(tmp_path)
    go(tool, offer)
    assert len(shell.checked) == 3
    kinds = ["install" if "Add-AppxPackage -Path" in s else "sign" for s, _ in shell.calls]
    assert kinds == ["sign", "sign", "sign", "install"]


def test_downloaded_files_are_cleaned_up_afterwards(tmp_path):
    _, _, tool, offer = ready(tmp_path)
    go(tool, offer)
    assert not list(tmp_path.iterdir())


def test_downloaded_files_are_cleaned_up_after_a_failure_too(tmp_path):
    _, _, tool, offer = ready(tmp_path, Shell(fail="Add-AppxPackage -Path"))
    with pytest.raises(RepairError):
        go(tool, offer)
    assert not list(tmp_path.iterdir())


def test_a_changed_file_is_never_installed(tmp_path):
    web, shell, tool, offer = ready(tmp_path)
    web.files[offer.bundle.url] = web.files[offer.bundle.url][:-1] + b"!"
    with pytest.raises(RepairError, match="checksum"):
        go(tool, offer)
    assert not shell.installs()


def test_a_short_download_is_never_installed(tmp_path):
    web, shell, tool, offer = ready(tmp_path)
    web.files[offer.bundle.url] = web.files[offer.bundle.url][:-10]
    with pytest.raises(RepairError):
        go(tool, offer)
    assert not shell.installs()


@pytest.mark.parametrize(
    ("status", "signer"),
    [
        ("NotSigned", ""),
        ("HashMismatch", MICROSOFT),
        ("Valid", "CN=Someone Else, O=Someone Else"),
        ("Valid", "CN=Fake, O=Not Microsoft Corporation Ltd"),
    ],
)
def test_a_file_not_signed_by_microsoft_is_never_installed(tmp_path, status, signer):
    _, shell, tool, offer = ready(tmp_path, Shell(status=status, signer=signer))
    with pytest.raises(RepairError, match="signature"):
        go(tool, offer)
    assert not shell.installs()


def test_a_signed_package_that_is_not_app_installer_is_never_installed(tmp_path):
    web = Web()
    web.add_release("v1.29.380", bundle=bundle_bytes(name="Microsoft.SomethingElse"))
    shell = Shell()
    tool = WingetRepair(open_url=web.open, powershell=shell, work_root=tmp_path)
    offer = tool.find_offer(19045, "x64")
    with pytest.raises(RepairError, match="not winget"):
        go(tool, offer)
    assert not shell.installs()


@pytest.mark.parametrize("name", ["x64/../../evil.appx", "x64/sub/evil.appx", "x64/evil.exe", "../x64/evil.appx"])
def test_odd_names_inside_the_dependency_zip_are_ignored(tmp_path, name):
    _, shell, tool, offer = ready(tmp_path, deps=deps_bytes(("x64/VCLibs_x64.appx", name)))
    go(tool, offer)
    assert shell.installs()[0]["WINGETDECK_DEPENDENCIES"].rsplit("\\", 1)[-1] == "VCLibs_x64.appx"
    assert not (tmp_path.parent / "evil.appx").exists()


def test_a_zip_without_dependencies_for_this_cpu_stops_the_install(tmp_path):
    _, shell, tool, offer = ready(tmp_path, deps=deps_bytes(("x86/VCLibs_x86.appx",)))
    with pytest.raises(RepairError, match="x64"):
        go(tool, offer)
    assert not shell.installs()


def test_cancel_stops_the_download_and_installs_nothing(tmp_path):
    _, shell, tool, offer = ready(tmp_path)
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(RepairCancelled):
        go(tool, offer, cancel=cancel)
    assert not shell.installs()
    assert not list(tmp_path.iterdir())


def test_a_full_disk_is_said_before_any_download(tmp_path, monkeypatch):
    web, shell, tool, offer = ready(tmp_path)
    monkeypatch.setattr(repair.shutil, "disk_usage", lambda p: type("U", (), {"free": 1000})())
    asked_before = list(web.asked)
    with pytest.raises(RepairError, match="free"):
        go(tool, offer)
    assert web.asked == asked_before
    assert not shell.installs()


def test_a_download_left_by_a_killed_run_is_removed_before_the_next_one(tmp_path):
    _, _, tool, offer = ready(tmp_path)
    left = tmp_path / "WingetDeck-winget-20260101-000000-000000"
    left.mkdir()
    (left / repair.BUNDLE_NAME).write_bytes(b"part of a download")
    go(tool, offer)
    assert not left.exists()


def test_the_space_from_a_killed_run_counts_towards_the_next_one(tmp_path, monkeypatch):
    _, _, tool, offer = ready(tmp_path)
    left = tmp_path / "WingetDeck-winget-20260101-000000-000000"
    left.mkdir()
    (left / repair.BUNDLE_NAME).write_bytes(b"part of a download")

    def free_once_cleared(path):
        return type("U", (), {"free": 1000 if left.exists() else offer.space_needed})()

    monkeypatch.setattr(repair.shutil, "disk_usage", free_once_cleared)
    go(tool, offer)


def test_clearing_leftovers_touches_nothing_else_in_the_temporary_folder(tmp_path):
    _, _, tool, offer = ready(tmp_path)
    other = tmp_path / "SomeoneElse-winget-1"
    other.mkdir()
    (other / "keep.txt").write_text("keep")
    named_alike = tmp_path / "WingetDeck-winget-notes.txt"
    named_alike.write_text("a file, not a work folder")
    go(tool, offer)
    assert (other / "keep.txt").exists()
    assert named_alike.exists()


def test_a_leftover_that_cannot_be_removed_does_not_stop_the_download(tmp_path, monkeypatch):
    _, shell, tool, offer = ready(tmp_path)
    (tmp_path / "WingetDeck-winget-20260101-000000-000000").mkdir()
    real = repair.shutil.rmtree

    def stubborn(path, *args, **kw):
        if "20260101" in str(path):
            if kw.get("ignore_errors"):
                return
            raise PermissionError(path)
        real(path, *args, **kw)

    monkeypatch.setattr(repair.shutil, "rmtree", stubborn)
    go(tool, offer)
    assert shell.installs()


def test_progress_is_reported_for_each_stage(tmp_path):
    _, _, tool, offer = ready(tmp_path)
    seen = []
    go(tool, offer, progress=seen.append)
    text = " ".join(seen)
    assert "Downloading" in text and "Checking" in text and "Installing" in text


def test_no_network_error_is_said_plainly(tmp_path):
    def offline(url, headers=None):
        raise urllib.error.URLError("no route to host")

    with pytest.raises(RepairError, match="GitHub"):
        WingetRepair(open_url=offline, powershell=Shell(), work_root=tmp_path).find_offer(19045, "x64")


def test_a_refused_or_broken_answer_is_said_plainly(tmp_path):
    def garbage(url, headers=None):
        return Response(b"<html>not json</html>")

    with pytest.raises(RepairError, match="GitHub"):
        WingetRepair(open_url=garbage, powershell=Shell(), work_root=tmp_path).find_offer(19045, "x64")


# Activating


def test_activating_registers_the_package_already_on_this_pc(tmp_path):
    shell = Shell()
    make(shell=shell, tmp_path=tmp_path).activate()
    script, _ = shell.calls[0]
    assert "-RegisterByFamilyName" in script and "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe" in script


def test_activating_downloads_nothing(tmp_path):
    web = Web()
    make(web, Shell(), tmp_path).activate()
    assert web.asked == []


def test_app_installer_version_is_read_or_none(tmp_path):
    assert make(shell=Shell(version="1.29.380.0\r\n"), tmp_path=tmp_path).app_installer_version() == "1.29.380.0"
    assert make(shell=Shell(version=""), tmp_path=tmp_path).app_installer_version() is None


# PowerShell


def test_powershell_is_the_windows_one_and_paths_never_enter_the_script(monkeypatch):
    seen = {}

    def fake_run(command, **kw):
        seen.update(command=command, kw=kw)
        return subprocess.CompletedProcess(command, 0, b"ok\r\n", b"")

    monkeypatch.setattr(repair.subprocess, "run", fake_run)
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    assert repair.run_powershell("Write-Output $env:WINGETDECK_FILE", {"WINGETDECK_FILE": "C:\\it's; evil"}) == "ok"
    assert seen["command"][0].lower() == r"c:\windows\system32\windowspowershell\v1.0\powershell.exe"
    assert "-NoProfile" in seen["command"] and "-NonInteractive" in seen["command"]
    assert "it's" not in " ".join(seen["command"])
    assert seen["kw"]["env"]["WINGETDECK_FILE"] == "C:\\it's; evil"
    assert seen["kw"]["stdin"] == subprocess.DEVNULL


def test_a_powershell_failure_gives_its_message(monkeypatch):
    monkeypatch.setattr(
        repair.subprocess,
        "run",
        lambda command, **kw: subprocess.CompletedProcess(command, 1, b"", b"Deployment failed 0x80073CF3\r\n"),
    )
    with pytest.raises(RepairError, match="0x80073CF3"):
        repair.run_powershell("x")


def test_powershell_missing_or_hung_is_a_plain_error(monkeypatch):
    def hang(command, **kw):
        raise subprocess.TimeoutExpired(command, 1)

    monkeypatch.setattr(repair.subprocess, "run", hang)
    with pytest.raises(RepairError):
        repair.run_powershell("x")

    def missing(command, **kw):
        raise FileNotFoundError(command[0])

    monkeypatch.setattr(repair.subprocess, "run", missing)
    with pytest.raises(RepairError):
        repair.run_powershell("x")


def test_offer_describes_the_size_in_megabytes():
    offer = Offer("v1", Asset("a", "u", 200 * 1024 * 1024, "x"), Asset("b", "u", 100 * 1024 * 1024, "y"), 17763)
    assert offer.total_megabytes == 300
