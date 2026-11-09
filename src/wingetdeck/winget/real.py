"""The real winget. Questions run piped. Upgrades run in a pseudo console when possible, because a
piped winget shows no progress at all."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import threading
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

from ..core.logs import SessionLog
from .backend import (
    Capabilities,
    Event,
    FinishedEvent,
    PackageDetails,
    UpgradeOptions,
)
from .capabilities import detect_capabilities
from .codes import explain
from .models import Package, ScanResult
from .parse import parse_show, parse_table_column, parse_upgrade_table, parse_versions
from .proc import KillResult, freeze_tree, kill_tree, thaw_tree, tree_names
from .stream import UpgradeStream

_QUERY_TIMEOUT = 600
_PTY_SIZE = (30, 200)
_CONSOLE_HOSTS = {"conhost.exe", "openconsole.exe"}
_NOTHING_TO_UPGRADE = {0x8A150014, 0x8A15002B}
_KILLED_EXIT = 1
_TRUNCATED = "…"


class WingetError(Exception):
    pass


def build_upgrade_args(package: Package, options: UpgradeOptions, caps: Capabilities) -> list[str]:
    args = ["upgrade", "--id", package.id, "-e"]
    if package.source:
        args += ["-s", package.source]
    return args + _option_args(options, caps)


def _option_args(options: UpgradeOptions, caps: Capabilities) -> list[str]:
    wanted: list[tuple[str, str | None]] = []
    if options.interactive:
        wanted.append(("--interactive", None))
    elif options.silent:
        wanted.append(("--silent", None))
    if options.scope:
        wanted.append(("--scope", options.scope))
    if options.architecture:
        wanted.append(("--architecture", options.architecture))
    if options.force:
        wanted.append(("--force", None))
    if options.uninstall_previous:
        wanted.append(("--uninstall-previous", None))
    if options.skip_dependencies:
        wanted.append(("--skip-dependencies", None))
    if options.include_pinned:
        wanted.append(("--include-pinned", None))
    if options.include_unknown:
        wanted.append(("--include-unknown", None))
    if options.accept_agreements:
        wanted.append(("--accept-package-agreements", None))
        wanted.append(("--accept-source-agreements", None))
    if options.custom:
        wanted.append(("--custom", options.custom))
    if options.override:
        wanted.append(("--override", options.override))
    if not options.interactive:
        wanted.append(("--disable-interactivity", None))
    args: list[str] = []
    for flag, value in wanted:
        if flag in caps.flags:
            args.append(flag)
            if value is not None:
                args.append(value)
    return args


def resolve_truncated(packages: list[Package], known_ids: set[str]) -> list[Package]:
    """Older winget versions cut long ids. Fill them in when exactly one known id fits."""
    resolved = []
    for package in packages:
        if package.truncated_id:
            prefix = package.id.rstrip(_TRUNCATED)
            matches = [i for i in known_ids if i.startswith(prefix)]
            if len(matches) == 1:
                package = replace(package, id=matches[0], truncated_id=False)
        resolved.append(package)
    return resolved


class RealHandle:
    """One running winget command, in a pseudo console or piped."""

    def __init__(self, log: SessionLog, package_id: str, argv: list[str], use_pty: bool) -> None:
        self._log = log
        self._package_id = package_id
        self._stream = UpgradeStream()
        self._transcript = log.package_transcript(package_id)
        self._queue: asyncio.Queue[Event | None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._killed = False
        log.info("Starting winget", package=package_id, command=" ".join(argv[1:]))
        if use_pty:
            from winpty import PtyProcess

            self._pty = PtyProcess.spawn(argv, dimensions=_PTY_SIZE)
            self._proc = None
            self.pid = self._pty.pid
        else:
            self._pty = None
            self._proc = subprocess.Popen(
                argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            self.pid = self._proc.pid

    def _emit(self, events: list[Event | None]) -> None:
        try:
            for event in events:
                self._loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except RuntimeError:  # the window has closed and winget outlived it
            pass

    def _chunk(self, chunk: str) -> None:
        self._transcript.write(chunk)
        self._log.debug("winget output", package=self._package_id, raw=repr(chunk))
        self._emit(self._stream.feed(chunk))

    def _read_pty(self) -> int | None:
        while True:
            try:
                self._chunk(self._pty.read(4096))
            except (EOFError, OSError, ConnectionError):
                break
        try:
            return self._pty.wait()
        except Exception as e:  # pywinpty raises its own error types on a dead process
            self._log.warn("Could not read exit code", package=self._package_id, error=repr(e))
            return self._pty.exitstatus

    def _read_pipe(self) -> int | None:
        while True:
            data = self._proc.stdout.read1(4096)
            if not data:
                break
            self._chunk(data.decode("utf-8", errors="replace"))
        return self._proc.wait()

    def _worker(self) -> None:
        code: int | None = None
        try:
            code = self._read_pty() if self._pty else self._read_pipe()
        except Exception as e:
            self._log.error("Lost contact with winget", package=self._package_id, error=repr(e))
        self._emit(self._stream.finish())
        if code is None:
            code = _KILLED_EXIT
        info = explain(code)
        self._log.info("winget finished", package=self._package_id, code=info.hex_code, meaning=info.message)
        self._transcript.close()
        self._emit([FinishedEvent(code)])
        self._emit([None])

    async def events(self) -> AsyncIterator[Event]:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event

    def freeze(self) -> bool:
        """Refused when an installer is running under winget: installers are never frozen."""
        children = [n for n in tree_names(self.pid) if n.lower() not in _CONSOLE_HOSTS]
        if children:
            self._log.warn("Freeze refused, child process present", package=self._package_id, children=children)
            return False
        freeze_tree(self.pid)
        self._log.info("Frozen", package=self._package_id)
        return True

    def thaw(self) -> None:
        thaw_tree(self.pid)
        self._log.info("Thawed", package=self._package_id)

    def kill(self) -> KillResult:
        thaw_tree(self.pid)
        result = kill_tree(self.pid)
        self._log.warn("Kill requested", package=self._package_id, killed=result.killed, denied=result.access_denied)
        return result


class RealBackend:
    def __init__(self, log: SessionLog, winget_path: str | None = None, force_piped: bool = False) -> None:
        self._log = log
        self.winget = winget_path or shutil.which("winget")
        self._force_piped = force_piped
        self.accept_source_agreements = False
        self._caps: Capabilities | None = None

    def _run_sync(self, args: list[str]) -> subprocess.CompletedProcess:
        if not self.winget:
            raise FileNotFoundError("winget")
        return subprocess.run(
            [self.winget, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=_QUERY_TIMEOUT,
        )

    def _text_sync(self, args: list[str]) -> str:
        return self._run_sync(args).stdout.decode("utf-8", errors="replace")

    async def _query(self, args: list[str], check: bool = True) -> str:
        full = list(args)
        if self.capabilities() is None:
            raise WingetError("winget is not available on this PC")
        if "--disable-interactivity" in self.capabilities().flags:
            full.append("--disable-interactivity")
        if self.accept_source_agreements and "--accept-source-agreements" in self.capabilities().flags:
            full.append("--accept-source-agreements")
        self._log.info("winget query", command=" ".join(full))
        try:
            done = await asyncio.to_thread(self._run_sync, full)
        except subprocess.TimeoutExpired as e:
            raise WingetError(f"winget did not answer within {_QUERY_TIMEOUT} seconds") from e
        except OSError as e:
            raise WingetError(f"winget could not start: {e}") from e
        text = done.stdout.decode("utf-8", errors="replace")
        code = done.returncode & 0xFFFFFFFF
        self._log.debug("winget query output", code=hex(code), text=text)
        if check and code and code not in _NOTHING_TO_UPGRADE:
            info = explain(code)
            self._log.error("winget query failed", code=info.hex_code, meaning=info.message)
            raise WingetError(f"{info.message} ({info.hex_code})")
        return text

    def capabilities(self) -> Capabilities | None:
        if self._caps is None:
            self._caps = detect_capabilities(self._text_sync)
            if self._caps is None:
                return None
            if self._force_piped:
                self._caps = replace(self._caps, live_progress=False)
        return self._caps

    def refresh_capabilities(self) -> None:
        self._caps = None

    async def sources(self) -> list[str]:
        return parse_table_column(await self._query(["source", "list"]), 0)

    async def update_sources(self) -> None:
        await self._query(["source", "update"])

    async def scan(self, source: str | None, include_pinned: bool = False) -> ScanResult:
        args = ["upgrade", "--include-unknown"]
        if source:
            args += ["-s", source]
        if include_pinned and "--include-pinned" in self.capabilities().flags:
            args.append("--include-pinned")
        result = parse_upgrade_table(await self._query(args))
        for note in result.notes:
            self._log.debug("Scan note", note=note)
        packages = result.packages
        if any(p.truncated_id for p in packages):
            packages = resolve_truncated(packages, await self._known_ids())
        pinned = set(await self.pins())
        packages = [replace(p, pinned=p.id in pinned) for p in packages]
        return ScanResult(packages, result.unknown_hidden, result.notes)

    async def _known_ids(self) -> set[str]:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "export.json"
            await self.export_snapshot(path)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                self._log.warn("Could not read exported ids", error=repr(e))
                return set()
        ids: set[str] = set()
        for source in data.get("Sources", []):
            ids.update(p.get("PackageIdentifier", "") for p in source.get("Packages", []))
        return ids

    async def show(self, package_id: str) -> PackageDetails:
        return parse_show(await self._query(["show", "--id", package_id, "-e"]))

    async def versions(self, package_id: str) -> list[str]:
        return parse_versions(await self._query(["show", "--id", package_id, "-e", "--versions"]))

    def _use_pty(self) -> bool:
        return self.capabilities().live_progress

    def start_upgrade(self, package: Package, options: UpgradeOptions) -> RealHandle:
        args = build_upgrade_args(package, options, self.capabilities())
        return RealHandle(self._log, package.id, [self.winget, *args], self._use_pty())

    def start_install_version(self, package_id: str, version: str, options: UpgradeOptions) -> RealHandle:
        args = ["install", "--id", package_id, "-e", "-v", version]
        args += _option_args(replace(options, include_unknown=False, include_pinned=False), self.capabilities())
        if "--force" not in args:
            args.append("--force")
        return RealHandle(self._log, package_id, [self.winget, *args], self._use_pty())

    async def export_snapshot(self, path) -> None:
        await self._query(["export", "-o", str(path), "--include-versions"], check=False)

    async def pins(self) -> list[str]:
        if not self.capabilities():
            return []
        return parse_table_column(await self._query(["pin", "list"], check=False), 1)

    async def pin_add(self, package_id: str) -> None:
        await self._query(["pin", "add", "--id", package_id, "-e"])

    async def pin_remove(self, package_id: str) -> None:
        await self._query(["pin", "remove", "--id", package_id, "-e"])

    async def info_text(self) -> str:
        return await asyncio.to_thread(self._text_sync, ["--info"])
