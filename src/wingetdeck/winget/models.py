"""Plain data shared by the winget layer and everything above it."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ChangeKind(Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"
    UNKNOWN = "unknown"


class Stage(Enum):
    DOWNLOADING = "downloading"
    VERIFYING = "verifying"
    INSTALLING = "installing"
    WORKING = "working"


@dataclass(frozen=True)
class Package:
    name: str
    id: str
    installed: str
    available: str
    source: str | None
    change: ChangeKind
    pinned: bool = False
    explicit_only: bool = False
    truncated_id: bool = False


@dataclass(frozen=True)
class ScanResult:
    packages: list[Package] = field(default_factory=list)
    unknown_hidden: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Progress:
    percent: float | None = None
    received_mb: float | None = None
    total_mb: float | None = None
