"""Find out what this PC's winget can do, rather than assuming a version."""

from __future__ import annotations

import re
from collections.abc import Callable

from .backend import Capabilities
from .settings_file import (
    DIRECT,
    SettingsUnreadable,
    default_settings_path,
    is_policy_locked,
    read_downloader,
)

_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z-]+")


def parse_flags(help_text: str) -> frozenset[str]:
    return frozenset(_FLAG.findall(help_text))


def pty_available() -> bool:
    try:
        import winpty  # noqa: F401
    except ImportError:
        return False
    return True


def _direct_downloader_on() -> bool:
    try:
        return read_downloader(default_settings_path()) == DIRECT
    except (SettingsUnreadable, OSError):
        return False


def detect_capabilities(run: Callable[[list[str]], str]) -> Capabilities | None:
    """run(args) returns winget's output. None means winget is missing or cannot start."""
    try:
        version = run(["--version"]).strip()
        help_text = run(["upgrade", "--help"])
    except (FileNotFoundError, OSError):
        return None
    if not version:
        return None
    return Capabilities(
        version=version,
        flags=parse_flags(help_text),
        live_progress=pty_available(),
        direct_downloader=_direct_downloader_on(),
        settings_locked=is_policy_locked(),
    )
