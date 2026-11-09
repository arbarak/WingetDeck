"""Winget's own settings file, for the opt-in direct downloader.

The file is JSON with comments and belongs to the user, so it is edited as text and backed up first.
"""

from __future__ import annotations

import json
import os
import winreg
from dataclasses import dataclass
from pathlib import Path

from ..paths import stamp

DIRECT = "wininet"
_POLICY_KEY = r"SOFTWARE\Policies\Microsoft\Windows\AppInstaller"


class SettingsUnreadable(Exception):
    pass


@dataclass(frozen=True)
class DownloaderChange:
    previous_existed: bool
    previous_value: str | None
    backup: Path | None


def default_settings_path() -> Path:
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return local / "Packages" / "Microsoft.DesktopAppInstaller_8wekyb3d8bbwe" / "LocalState" / "settings.json"


def is_policy_locked() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _POLICY_KEY):
            return True
    except OSError:
        return False


def _blank_comments(text: str) -> str:
    """Replace comments with spaces, keeping every position, so offsets match the original text."""
    out = list(text)
    i, n = 0, len(text)
    in_string = False
    while i < n:
        c = text[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            in_string = c != '"'
        elif c == '"':
            in_string = True
        elif text.startswith("//", i):
            while i < n and text[i] not in "\r\n":
                out[i] = " "
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            for j in range(i, end):
                if text[j] not in "\r\n":
                    out[j] = " "
            i = end
            continue
        i += 1
    return "".join(out)


def _parse(text: str) -> dict:
    try:
        data = json.loads(_blank_comments(text)) if text.strip() else {}
    except ValueError as e:
        raise SettingsUnreadable(str(e)) from e
    if not isinstance(data, dict):
        raise SettingsUnreadable("settings file is not an object")
    return data


def read_downloader(path: Path) -> str | None:
    if not path.exists():
        return None
    network = _parse(path.read_text(encoding="utf-8-sig")).get("network")
    return network.get("downloader") if isinstance(network, dict) else None


def _find_key(blank: str, key: str, start: int, end: int) -> int:
    """Offset of the value of a direct member "key" of the object whose inside is [start, end)."""
    depth = 0
    i = start
    in_string = False
    while i < end:
        c = blank[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_string = False
        elif c == '"':
            if depth == 0 and blank.startswith(f'"{key}"', i):
                i = blank.index(":", i) + 1
                while blank[i].isspace():
                    i += 1
                return i
            in_string = True
        elif c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        i += 1
    return -1


def _value_end(blank: str, start: int) -> int:
    """Offset just past the JSON value starting at start."""
    _, end = json.JSONDecoder().raw_decode(blank, start)
    return end


def _insert_member(text: str, blank: str, brace: int, member: str) -> str:
    """Add a member right after an object's opening brace."""
    closing = _value_end(blank, brace) - 1
    empty = not blank[brace + 1 : closing].strip()
    return text[: brace + 1] + f" {member}" + ("" if empty else ",") + text[brace + 1 :]


def _with_downloader(text: str) -> str:
    if not text.strip():
        return json.dumps({"network": {"downloader": DIRECT}}, indent=2) + "\n"
    blank = _blank_comments(text)
    root = next(i for i, c in enumerate(blank) if not c.isspace())
    root_end = _value_end(blank, root)
    network = _find_key(blank, "network", root + 1, root_end - 1)
    if network < 0 or blank[network] != "{":
        return _insert_member(text, blank, root, f'"network": {{"downloader": "{DIRECT}"}}')
    network_end = _value_end(blank, network)
    existing = _find_key(blank, "downloader", network + 1, network_end - 1)
    if existing < 0:
        return _insert_member(text, blank, network, f'"downloader": "{DIRECT}"')
    return text[:existing] + f'"{DIRECT}"' + text[_value_end(blank, existing) :]


def enable_direct(path: Path, backups: Path) -> DownloaderChange:
    existed = path.exists()
    original = path.read_bytes() if existed else b""
    text = original.decode("utf-8-sig") if existed else ""
    previous = read_downloader(path) if existed else None
    updated = _with_downloader(text)
    backup = None
    if existed:
        backups.mkdir(parents=True, exist_ok=True)
        backup = backups / f"winget_settings_{stamp()}.json"
        backup.write_bytes(original)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".wingetdeck.tmp")
    temp.write_text(updated, encoding="utf-8")
    os.replace(temp, path)
    return DownloaderChange(existed, previous, backup)


def undo(path: Path, change: DownloaderChange) -> None:
    if change.previous_existed and change.backup:
        temp = path.with_name(path.name + ".wingetdeck.tmp")
        temp.write_bytes(change.backup.read_bytes())
        os.replace(temp, path)
    elif path.exists():
        path.unlink()
