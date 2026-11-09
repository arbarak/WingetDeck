"""Getting winget onto a PC that lacks it. This is the only network code in the app, and it runs only when asked.

What gets installed must pass every check here first: it comes from Microsoft's releases on GitHub over HTTPS, it matches
the checksum GitHub lists, each file carries a valid Microsoft signature, and the package really is App Installer.
Windows checks the signature again when it installs.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
import zipfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

PACKAGE_FAMILY = "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe"
PACKAGE_NAME = "Microsoft.DesktopAppInstaller"
BUNDLE_NAME = f"{PACKAGE_FAMILY}.msixbundle"
DEPENDENCIES_NAME = "DesktopAppInstaller_Dependencies.zip"
RELEASES_URL = "https://api.github.com/repos/microsoft/winget-cli/releases?per_page=30"
STORE_LINK = "ms-windows-store://pdp/?productid=9NBLGGH4NNS1"  # App Installer

_ALLOWED_HOSTS = {
    "api.github.com",
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
_DOWNLOADS_FROM = "https://github.com/microsoft/winget-cli/releases/download/"
_STABLE_TAG = re.compile(r"v\d+\.\d+(\.\d+)*")
_MANIFEST = "AppxMetadata/AppxBundleManifest.xml"
_DESKTOP_FAMILIES = {"Windows.Universal", "Windows.Desktop"}
_MICROSOFT_SIGNER = re.compile(r"(^|,\s*)O=Microsoft Corporation\s*(,|$)")
_MICROSOFT_PUBLISHER = "CN=Microsoft Corporation,"
_ARCHITECTURES = {"amd64": "x64", "x86": "x86", "arm64": "arm64"}
_MAX_STABLE_CHECKED = 6
_MAX_MANIFEST_BYTES = 5 * 1024 * 1024
_READ_AHEAD = 64 * 1024
_CHUNK = 1024 * 1024
_WORK_FOLDER = "WingetDeck-winget-"
_MEGABYTE = 1024 * 1024
_SPARE_BYTES = 200 * _MEGABYTE
_TIMEOUT = 30
_SIGNATURE_TIMEOUT = 120
_INSTALL_TIMEOUT = 900
_MANAGE_TIMEOUT = 300

_NETWORK_ERRORS = (OSError, http.client.HTTPException)


class RepairError(Exception):
    """Something the user should read. The message says what went wrong in plain words."""


class RepairCancelled(Exception):
    pass


@dataclass(frozen=True)
class Asset:
    name: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Offer:
    version: str
    bundle: Asset
    dependencies: Asset
    min_build: int

    @property
    def total_size(self) -> int:
        return self.bundle.size + self.dependencies.size

    @property
    def total_megabytes(self) -> int:
        return round(self.total_size / _MEGABYTE)

    @property
    def space_needed(self) -> int:
        return 2 * self.total_size + _SPARE_BYTES


def device_architecture(environ: Mapping[str, str] | None = None) -> str | None:
    """The PC's real processor. A 32-bit exe on 64-bit Windows sees x86 in the first variable, and the truth in the other."""
    env = os.environ if environ is None else environ
    name = env.get("PROCESSOR_ARCHITEW6432") or env.get("PROCESSOR_ARCHITECTURE") or ""
    return _ARCHITECTURES.get(name.lower())


def address_allowed(url: str) -> bool:
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname in _ALLOWED_HOSTS and not parts.username


class CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """GitHub sends downloads on to another of its own hosts. Anywhere else is refused."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not address_allowed(newurl):
            raise RepairError(f"The download tried to go to an address outside GitHub: {urlsplit(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(CheckedRedirects)


def open_checked(url: str, headers: Mapping[str, str] | None = None):
    if not address_allowed(url):
        raise RepairError(f"Refused to open an address outside GitHub: {urlsplit(url).hostname}")
    request = urllib.request.Request(url, headers={"User-Agent": "WingetDeck", **(headers or {})})
    return _opener.open(request, timeout=_TIMEOUT)


def run_powershell(script: str, env: Mapping[str, str] | None = None, timeout: int = _MANAGE_TIMEOUT) -> str:
    """Runs Windows' own PowerShell by its full path. File names go in through variables, so they can never become code."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    program = os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    wrapped = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $ErrorActionPreference = 'Stop'; "
        f"try {{ {script} }} catch {{ [Console]::Error.WriteLine($_.Exception.Message); exit 1 }}"
    )
    try:
        done = subprocess.run(
            [program, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", wrapped],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            env={**os.environ, **(env or {})},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as e:
        raise RepairError(f"Windows did not finish within {timeout} seconds.") from e
    except OSError as e:
        raise RepairError(f"Windows PowerShell could not start: {e}") from e
    if done.returncode:
        message = done.stderr.decode("utf-8", errors="replace").strip()
        raise RepairError(" ".join(message.split())[:400] or f"Windows reported an error ({done.returncode}).")
    return done.stdout.decode("utf-8", errors="replace").strip()


def open_store() -> None:
    try:
        os.startfile(STORE_LINK)
    except (OSError, AttributeError) as e:
        raise RepairError("The Microsoft Store could not be opened on this PC.") from e


class _RemoteFile:
    """Lets zipfile read the index of a package on the web, without downloading the package."""

    def __init__(self, url: str, size: int, open_url: Callable) -> None:
        self._url, self._size, self._open = url, size, open_url
        self._position = 0
        self._start = 0
        self._buffer = b""

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._position

    def seek(self, offset: int, whence: int = 0) -> int:
        base = {0: 0, 1: self._position, 2: self._size}[whence]
        self._position = base + offset
        return self._position

    def read(self, count: int = -1) -> bytes:
        remaining = self._size - self._position
        count = remaining if count < 0 else min(count, remaining)
        if count <= 0:
            return b""
        if not (self._start <= self._position and self._position + count <= self._start + len(self._buffer)):
            self._fetch(max(count, _READ_AHEAD))
        offset = self._position - self._start
        data = self._buffer[offset : offset + count]
        self._position += len(data)
        return data

    def _fetch(self, count: int) -> None:
        end = min(self._position + count, self._size) - 1
        with self._open(self._url, {"Range": f"bytes={self._position}-{end}"}) as response:
            if response.status != 206:
                raise RepairError("GitHub did not allow reading part of the file, so it could not be checked first.")
            self._buffer = response.read()
        self._start = self._position


@dataclass(frozen=True)
class _BundleInfo:
    name: str
    publisher: str
    min_builds: dict[str, int]


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read_bundle_info(package: zipfile.ZipFile) -> _BundleInfo:
    if package.getinfo(_MANIFEST).file_size > _MAX_MANIFEST_BYTES:
        raise ValueError("manifest is too large")
    text = package.read(_MANIFEST)
    # This is read before the signature can be checked. A real manifest is plain UTF-8 and never defines entities.
    if b"\x00" in text or b"<!DOCTYPE" in text or b"<!ENTITY" in text:
        raise ValueError("manifest has a form that is not allowed")
    root = ElementTree.fromstring(text)
    identity = next(e for e in root if _local_name(e.tag) == "Identity")
    builds: dict[str, int] = {}
    for element in root.iter():
        if _local_name(element.tag) != "Package" or element.get("Type") != "application":
            continue
        for family in element.iter():
            if _local_name(family.tag) == "TargetDeviceFamily" and family.get("Name") in _DESKTOP_FAMILIES:
                build = int(family.get("MinVersion", "").split(".")[2])
                architecture = element.get("Architecture", "")
                builds[architecture] = min(build, builds.get(architecture, build))
    return _BundleInfo(identity.get("Name", ""), identity.get("Publisher", ""), builds)


def _asset(release: Mapping, name: str) -> Asset | None:
    for entry in release.get("assets", []):
        if entry.get("name") != name:
            continue
        url, digest = entry.get("browser_download_url", ""), entry.get("digest", "")
        if not url.startswith(_DOWNLOADS_FROM) or not digest.startswith("sha256:"):
            return None
        return Asset(name, url, int(entry["size"]), digest.removeprefix("sha256:").lower())
    return None


class WingetRepair:
    def __init__(
        self,
        open_url: Callable = open_checked,
        powershell: Callable[..., str] = run_powershell,
        work_root: Path | None = None,
    ) -> None:
        self._open = open_url
        self._powershell = powershell
        self._work_root = work_root

    def activate(self) -> None:
        """Asks Windows to set up an App Installer it already has for this user. Nothing is downloaded."""
        self._powershell(f"Add-AppxPackage -RegisterByFamilyName -MainPackage {PACKAGE_FAMILY}")

    def app_installer_version(self) -> str | None:
        output = self._powershell(f"(Get-AppxPackage -Name {PACKAGE_NAME}).Version")
        return output.strip() or None

    def find_offer(self, build: int, architecture: str | None) -> Offer | None:
        """The newest stable winget that says it runs on this Windows build and processor."""
        if architecture is None:
            raise RepairError("Could not tell what kind of processor this PC has.")
        checked = 0
        for release in self._releases():
            if release.get("prerelease") or release.get("draft"):
                continue
            tag = release.get("tag_name", "")
            bundle, dependencies = _asset(release, BUNDLE_NAME), _asset(release, DEPENDENCIES_NAME)
            if not _STABLE_TAG.fullmatch(tag) or not bundle or not dependencies:
                continue
            checked += 1
            if checked > _MAX_STABLE_CHECKED:
                return None
            minimum = self._minimum_build(bundle, architecture)
            if minimum is not None and minimum <= build:
                return Offer(tag, bundle, dependencies, minimum)
        return None

    def _releases(self) -> list:
        try:
            with self._open(RELEASES_URL, {"Accept": "application/vnd.github+json"}) as response:
                releases = json.loads(response.read())
        except _NETWORK_ERRORS as e:
            raise RepairError(f"Could not reach GitHub to look for winget: {e}") from e
        except ValueError as e:
            raise RepairError("GitHub sent an answer that could not be read.") from e
        if not isinstance(releases, list):
            raise RepairError("GitHub sent an answer that could not be read.")
        return releases

    def _minimum_build(self, bundle: Asset, architecture: str) -> int | None:
        try:
            with zipfile.ZipFile(_RemoteFile(bundle.url, bundle.size, self._open)) as package:
                return _read_bundle_info(package).min_builds.get(architecture)
        except _NETWORK_ERRORS as e:
            raise RepairError(f"Could not reach GitHub to check winget: {e}") from e
        except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, ValueError, IndexError, StopIteration):
            return None

    def download_and_install(
        self, offer: Offer, architecture: str, progress: Callable[[str], None], cancel: threading.Event
    ) -> None:
        root = self._work_root or Path(os.environ.get("TEMP") or Path.home())
        for left in root.glob(f"{_WORK_FOLDER}*"):  # from a run that was killed, so its own clean-up never ran
            if left.is_dir() and not left.is_symlink():
                shutil.rmtree(left, ignore_errors=True)
        try:
            free = shutil.disk_usage(root).free
        except OSError as e:
            raise RepairError(f"Could not use the temporary folder: {e}") from e
        if free < offer.space_needed:
            need = round(offer.space_needed / _MEGABYTE)
            raise RepairError(f"Installing winget needs about {need} MB free on this drive, and only {free // _MEGABYTE} MB is free.")
        folder = root / f"{_WORK_FOLDER}{datetime.now():%Y%m%d-%H%M%S-%f}"
        try:
            folder.mkdir()
        except OSError as e:
            raise RepairError(f"Could not use the temporary folder: {e}") from e
        try:
            self._download_check_install(offer, architecture, folder, progress, cancel)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def _download_check_install(
        self, offer: Offer, architecture: str, folder: Path, progress: Callable[[str], None], cancel: threading.Event
    ) -> None:
        done = [0, -1]
        bundle = self._download(offer.bundle, folder, offer, done, progress, cancel)
        archive = self._download(offer.dependencies, folder, offer, done, progress, cancel)

        progress("Checking Microsoft's signature…")
        self._check_signature(bundle)
        self._check_identity(bundle)
        dependencies = self._unpack_dependencies(archive, architecture, folder)
        for dependency in dependencies:
            self._check_signature(dependency)
        if cancel.is_set():
            raise RepairCancelled

        progress("Installing winget. This can take a few minutes…")
        self._powershell(
            "Add-AppxPackage -Path $env:WINGETDECK_BUNDLE -DependencyPath ($env:WINGETDECK_DEPENDENCIES -split '\\|')",
            {"WINGETDECK_BUNDLE": str(bundle), "WINGETDECK_DEPENDENCIES": "|".join(str(d) for d in dependencies)},
            timeout=_INSTALL_TIMEOUT,
        )

    def _download(
        self,
        asset: Asset,
        folder: Path,
        offer: Offer,
        done: list[int],
        progress: Callable[[str], None],
        cancel: threading.Event,
    ) -> Path:
        path = folder / asset.name
        digest = hashlib.sha256()
        received = 0
        try:
            with self._open(asset.url) as response, open(path, "wb") as out:
                while True:
                    if cancel.is_set():
                        raise RepairCancelled
                    chunk = response.read(_CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    done[0] += len(chunk)
                    percent = done[0] * 100 // max(offer.total_size, 1)
                    if percent != done[1]:
                        done[1] = percent
                        progress(f"Downloading winget: {percent}% of {offer.total_megabytes} MB")
        except _NETWORK_ERRORS as e:
            raise RepairError(f"The download stopped: {e}") from e
        if cancel.is_set():
            raise RepairCancelled
        if received != asset.size or digest.hexdigest() != asset.sha256:
            raise RepairError(f"{asset.name} does not match the checksum GitHub lists, so it was not installed.")
        return path

    def _check_signature(self, path: Path) -> None:
        output = self._powershell(
            "$s = Get-AuthenticodeSignature -LiteralPath $env:WINGETDECK_FILE; "
            "Write-Output ('' + $s.Status + '|' + $s.SignerCertificate.Subject)",
            {"WINGETDECK_FILE": str(path)},
            timeout=_SIGNATURE_TIMEOUT,
        )
        status, _, signer = output.partition("|")
        if status.strip() != "Valid" or not _MICROSOFT_SIGNER.search(signer.strip()):
            raise RepairError(f"{path.name} has no valid Microsoft signature, so it was not installed.")

    def _check_identity(self, bundle: Path) -> None:
        try:
            with zipfile.ZipFile(bundle) as package:
                info = _read_bundle_info(package)
        except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, ValueError, IndexError, StopIteration, OSError) as e:
            raise RepairError("The downloaded package could not be read, so it was not installed.") from e
        if info.name != PACKAGE_NAME or not info.publisher.startswith(_MICROSOFT_PUBLISHER):
            raise RepairError("The downloaded package is not winget, so it was not installed.")

    def _unpack_dependencies(self, archive: Path, architecture: str, folder: Path) -> list[Path]:
        wanted = re.compile(re.escape(architecture) + r"/([A-Za-z0-9][A-Za-z0-9._-]*\.(?:appx|msix))")
        unpacked = []
        try:
            with zipfile.ZipFile(archive) as package:
                for name in package.namelist():
                    found = wanted.fullmatch(name)
                    if found:
                        target = folder / found[1]  # only the plain file name, so nothing lands outside this folder
                        with package.open(name) as source, open(target, "wb") as out:
                            shutil.copyfileobj(source, out, _CHUNK)
                        unpacked.append(target)
        except (zipfile.BadZipFile, OSError) as e:
            raise RepairError("The downloaded parts winget needs could not be unpacked.") from e
        if not unpacked:
            raise RepairError(f"This release has none of the parts winget needs on an {architecture} PC.")
        return unpacked
