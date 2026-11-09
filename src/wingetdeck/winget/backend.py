"""The boundary between the app and winget. The UI and the queue only ever see this."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from .models import Package, Progress, ScanResult, Stage
from .proc import KillResult


@dataclass(frozen=True)
class ProgressEvent:
    progress: Progress


@dataclass(frozen=True)
class StageEvent:
    stage: Stage


@dataclass(frozen=True)
class OutputEvent:
    line: str


@dataclass(frozen=True)
class FinishedEvent:
    exit_code: int


Event = ProgressEvent | StageEvent | OutputEvent | FinishedEvent


@dataclass(frozen=True)
class UpgradeOptions:
    silent: bool = True
    interactive: bool = False
    scope: str | None = None
    architecture: str | None = None
    force: bool = False
    uninstall_previous: bool = False
    skip_dependencies: bool = False
    include_pinned: bool = False
    include_unknown: bool = True
    accept_agreements: bool = False
    custom: str | None = None
    override: str | None = None


@dataclass(frozen=True)
class Capabilities:
    version: str
    flags: frozenset[str]
    live_progress: bool
    direct_downloader: bool
    settings_locked: bool


@dataclass(frozen=True)
class PackageDetails:
    publisher: str | None = None
    homepage: str | None = None
    release_notes: str | None = None


class UpgradeHandle(Protocol):
    pid: int

    def events(self) -> AsyncIterator[Event]: ...

    def freeze(self) -> bool: ...

    def thaw(self) -> None: ...

    def kill(self) -> KillResult: ...


class WingetBackend(Protocol):
    def capabilities(self) -> Capabilities: ...

    async def sources(self) -> list[str]: ...

    async def update_sources(self) -> None: ...

    async def scan(self, source: str | None, include_pinned: bool = False) -> ScanResult: ...

    async def show(self, package_id: str) -> PackageDetails: ...

    def start_upgrade(self, package: Package, options: UpgradeOptions) -> UpgradeHandle: ...

    def start_install_version(
        self, package_id: str, version: str, options: UpgradeOptions
    ) -> UpgradeHandle: ...

    async def versions(self, package_id: str) -> list[str]: ...

    async def export_snapshot(self, path) -> None: ...

    async def pins(self) -> list[str]: ...

    async def pin_add(self, package_id: str) -> None: ...

    async def pin_remove(self, package_id: str) -> None: ...

    async def info_text(self) -> str: ...
