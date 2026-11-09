"""A pretend winget for tests and for `--demo`. It never touches the real one."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from .backend import (
    Capabilities,
    Event,
    FinishedEvent,
    OutputEvent,
    PackageDetails,
    ProgressEvent,
    StageEvent,
    UpgradeOptions,
)
from .models import ChangeKind, Package, Progress, ScanResult, Stage
from .proc import KillResult
from .settings_file import DownloaderChange

_KILLED = 1
_DOWNLOAD_STEPS = 20
_TOTAL_MB = 80.0
_STEP_SECONDS = 0.15


class FakeHandle:
    def __init__(self, backend: FakeBackend, package: Package, exit_code: int) -> None:
        self.pid = 0
        self._backend = backend
        self._package = package
        self._exit_code = exit_code
        self._running = asyncio.Event()
        self._running.set()
        self._killed = False

    def freeze(self) -> bool:
        if self._backend.refuse_freeze:
            return False
        self._running.clear()
        return True

    def thaw(self) -> None:
        self._running.set()

    def kill(self) -> KillResult:
        self._killed = True
        self._running.set()
        return KillResult(killed=True)

    async def _pause(self, steps: float = 1) -> None:
        await asyncio.sleep(_STEP_SECONDS * steps / self._backend.speed)
        await self._running.wait()

    async def events(self) -> AsyncIterator[Event]:
        await self._running.wait()
        yield OutputEvent(f"Found {self._package.name} [{self._package.id}]")
        yield StageEvent(Stage.DOWNLOADING)
        for step in range(1, _DOWNLOAD_STEPS + 1):
            await self._pause()
            if self._killed:
                yield FinishedEvent(_KILLED)
                return
            received = _TOTAL_MB * step / _DOWNLOAD_STEPS
            yield ProgressEvent(Progress(received / _TOTAL_MB * 100, received, _TOTAL_MB))
        yield OutputEvent("Successfully verified installer hash")
        yield StageEvent(Stage.VERIFYING)
        await self._pause(3)
        yield OutputEvent("Starting package install...")
        yield StageEvent(Stage.INSTALLING)
        await self._pause(8)
        if self._killed:
            yield FinishedEvent(_KILLED)
            return
        if self._exit_code == 0:
            self._backend.mark_upgraded(self._package.id)
            yield OutputEvent("Successfully installed")
        yield FinishedEvent(self._exit_code)


class FakeBackend:
    def __init__(
        self,
        packages: list[Package],
        speed: float = 1.0,
        script: dict[str, int | list[int]] | None = None,
        direct_downloader: bool = True,
        live_progress: bool = True,
        scan_error: Exception | None = None,
    ) -> None:
        self.packages = list(packages)
        self.speed = speed
        self.script = dict(script or {})
        self.direct_downloader = direct_downloader
        self.live_progress = live_progress
        self.scan_error = scan_error
        self.source_updates = 0
        self.calls: list[str] = []
        self.pin_ids: list[str] = []
        self.options_seen: dict[str, UpgradeOptions] = {}
        self.old_versions: dict[str, list[str]] = {}
        self.refuse_freeze = False
        self.accept_source_agreements = False

    def capabilities(self) -> Capabilities:
        return Capabilities(
            version="v0.0.0-demo",
            flags=frozenset(),
            live_progress=self.live_progress,
            direct_downloader=self.direct_downloader,
            settings_locked=False,
        )

    def refresh_capabilities(self) -> None:
        pass

    def enable_direct_downloader(self, backups) -> DownloaderChange:
        self.direct_downloader = True
        return DownloaderChange(False, None, None)

    def undo_direct_downloader(self, change: DownloaderChange) -> None:
        self.direct_downloader = False

    def add_package(self, package: Package) -> None:
        self.packages.append(package)

    def mark_upgraded(self, package_id: str) -> None:
        self.packages = [p for p in self.packages if p.id != package_id]

    async def sources(self) -> list[str]:
        return sorted({p.source for p in self.packages if p.source} | {"winget", "msstore"})

    async def update_sources(self) -> None:
        self.calls.append("update_sources")
        self.source_updates += 1
        await asyncio.sleep(0.2 / self.speed)

    async def scan(self, source: str | None, include_pinned: bool = False) -> ScanResult:
        self.calls.append("scan")
        await asyncio.sleep(0.2 / self.speed)
        if self.scan_error:
            raise self.scan_error
        rows = [p for p in self.packages if source is None or p.source == source]
        return ScanResult(packages=rows)

    async def show(self, package_id: str) -> PackageDetails:
        return PackageDetails("Example Publisher", "https://example.com", "Bug fixes and improvements.")

    def _exit_code(self, package_id: str) -> int:
        code = self.script.get(package_id, 0)
        if isinstance(code, list):
            return code.pop(0) if code else 0
        return code

    def start_upgrade(self, package: Package, options: UpgradeOptions) -> FakeHandle:
        self.calls.append(f"upgrade:{package.id}")
        self.options_seen[package.id] = options
        return FakeHandle(self, package, self._exit_code(package.id))

    def start_install_version(self, package_id: str, version: str, options: UpgradeOptions) -> FakeHandle:
        self.calls.append(f"install:{package_id}:{version}")
        package = Package(package_id, package_id, "", version, None, ChangeKind.UNKNOWN)
        return FakeHandle(self, package, self._exit_code(package_id))

    async def versions(self, package_id: str) -> list[str]:
        return list(self.old_versions.get(package_id, []))

    async def export_snapshot(self, path) -> None:
        self.calls.append("export_snapshot")
        Path(path).write_text('{"demo": true}', encoding="utf-8")

    async def pins(self) -> list[str]:
        return list(self.pin_ids)

    async def pin_add(self, package_id: str) -> None:
        self.pin_ids.append(package_id)

    async def pin_remove(self, package_id: str) -> None:
        self.pin_ids.remove(package_id)

    async def info_text(self) -> str:
        return "Demo mode: no real winget is used."


def demo_packages() -> list[Package]:
    rows = [
        ("Windows Subsystem for Linux", "Microsoft.WSL", "2.7.3.0", "2.7.14", "winget", ChangeKind.PATCH),
        ("wkhtmltox 0.12.6-1", "wkhtmltopdf.wkhtmltox", "Unknown", "0.12.6-1", "winget", ChangeKind.UNKNOWN),
        ("Git", "Git.Git", "2.50.0", "2.51.1", "winget", ChangeKind.MINOR),
        ("Node.js LTS", "OpenJS.NodeJS.LTS", "20.19.2", "22.23.4", "winget", ChangeKind.MAJOR),
        ("Microsoft Visual Studio Code", "Microsoft.VisualStudioCode", "1.102.0", "1.105.1", "winget", ChangeKind.MINOR),
        ("7-Zip", "7zip.7zip", "25.00", "25.01", "winget", ChangeKind.MINOR),
        ("Windows Notepad", "9MSMLRH6LZF3", "11.2507.0", "11.2508.1", "msstore", ChangeKind.MINOR),
    ]
    return [Package(*row) for row in rows]
