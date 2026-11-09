"""The rules of a run: what Pause and Stop may do at each stage. No I/O and no UI.

The rules exist because of what was measured: with winget's default downloader the transfer runs in
a Windows service, so freezing winget would only freeze the progress display. Only a download under
the direct downloader can truly be frozen, and an installer is never frozen.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..winget.codes import Outcome, explain
from ..winget.models import ChangeKind, Package, Stage
from .store import QueueItem, QueueSnapshot

RUG_PULL_IDS = {"Microsoft.AppInstaller", "Microsoft.WindowsTerminal", "Microsoft.WindowsTerminal.Preview"}


class ItemState(Enum):
    WAITING = "waiting"
    ACTIVE = "active"
    DONE = "done"
    DONE_RESTART = "done_restart"
    SKIPPED = "skipped"
    FAILED = "failed"
    STOPPED = "stopped"


class RunState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


class Effect(Enum):
    NONE = "none"
    START_NEXT = "start_next"
    FREEZE = "freeze"
    THAW = "thaw"
    KILL = "kill"
    THAW_AND_KILL = "thaw_and_kill"


@dataclass(frozen=True)
class Controls:
    pause_label: str
    pause_enabled: bool
    stop_choices: tuple[str, ...]


@dataclass(frozen=True)
class Summary:
    done: int
    restart_needed: int
    skipped: int
    failed: int
    stopped: int


@dataclass
class RunItem:
    package: Package
    state: ItemState = ItemState.WAITING
    message: str = ""
    code: str = ""
    in_use: bool = False


STOP_AFTER = "Stop after this one"
STOP_NOW = "Stop now"
FORCE_STOP = "Force stop"
STOP_PLAIN = "Stop"


class RunQueue:
    def __init__(self, packages: list[Package], direct_downloader: bool) -> None:
        ordered = sorted(packages, key=lambda p: p.id in RUG_PULL_IDS)
        self.items = [RunItem(p) for p in ordered]
        self.direct_downloader = direct_downloader
        self._next_direct = direct_downloader
        self.state = RunState.IDLE
        self.active: RunItem | None = None
        self.stage: Stage | None = None
        self._pause_after = False
        self._stop_after = False
        self._killing_as: ItemState | None = None
        self._kill_message = ""

    def _waiting(self) -> list[RunItem]:
        return [i for i in self.items if i.state is ItemState.WAITING]

    def _begin_next(self) -> Effect:
        waiting = self._waiting()
        if not waiting:
            self.state = RunState.FINISHED
            self.active = None
            return Effect.NONE
        self.direct_downloader = self._next_direct
        self.active = waiting[0]
        self.active.state = ItemState.ACTIVE
        self.stage = None
        self.state = RunState.RUNNING
        return Effect.START_NEXT

    def _finish_rest(self) -> None:
        for item in self._waiting():
            item.state = ItemState.STOPPED
        self.active = None
        self.state = RunState.FINISHED

    def start(self) -> Effect:
        return self._begin_next()

    def on_stage(self, stage: Stage) -> None:
        self.stage = stage

    def _can_freeze(self) -> bool:
        return self.active is not None and self.direct_downloader and self.stage is Stage.DOWNLOADING

    def pause(self) -> Effect:
        if self.state is not RunState.RUNNING or self._pause_after:
            return Effect.NONE
        if self._can_freeze():
            self.state = RunState.PAUSED
            return Effect.FREEZE
        self._pause_after = True
        return Effect.NONE

    def freeze_refused(self) -> None:
        """The process could not be frozen, so wait for the package to finish instead."""
        self.state = RunState.RUNNING
        self._pause_after = True

    def resume(self) -> Effect:
        if self.state is not RunState.PAUSED:
            return Effect.NONE
        if self.active is not None:
            self.state = RunState.RUNNING
            return Effect.THAW
        return self._begin_next()

    def stop_after(self) -> Effect:
        if self.active is None:
            self._finish_rest()
            return Effect.NONE
        self._stop_after = True
        if self.state is RunState.PAUSED:
            # A frozen package would otherwise never finish, so "after this one" would never come.
            self.state = RunState.RUNNING
            return Effect.THAW
        return Effect.NONE

    def stop_now(self) -> Effect:
        """Allowed only while downloading: a running installer needs force_stop and a warning."""
        if self.active is None or self.stage is not Stage.DOWNLOADING:
            return Effect.NONE
        self._killing_as = ItemState.STOPPED
        self._kill_message = "Stopped during download"
        self._stop_after = True
        frozen = self.state is RunState.PAUSED
        self.state = RunState.RUNNING
        return Effect.THAW_AND_KILL if frozen else Effect.KILL

    def force_stop(self) -> Effect:
        if self.active is None:
            return Effect.NONE
        self._killing_as = ItemState.FAILED
        self._kill_message = "Force stopped during install. This app may need reinstalling."
        self._stop_after = True
        return Effect.KILL

    def on_finished(self, exit_code: int) -> Effect:
        item = self.active
        if item is None:
            return Effect.NONE
        info = explain(exit_code)
        item.code = info.hex_code
        item.message = info.message
        if self._killing_as is not None:
            item.state = self._killing_as
            item.message = self._kill_message
            self._killing_as = None
        elif info.outcome is Outcome.SUCCESS:
            item.state = ItemState.DONE
        elif info.outcome is Outcome.SUCCESS_RESTART:
            item.state = ItemState.DONE_RESTART
        elif info.outcome is Outcome.SKIPPED:
            item.state = ItemState.SKIPPED
        else:
            item.state = ItemState.FAILED
            item.in_use = info.outcome is Outcome.FAILED_IN_USE
        self.active = None
        self.stage = None
        if self._stop_after:
            self._finish_rest()
            return Effect.NONE
        if not self._waiting():
            self.state = RunState.FINISHED
            return Effect.NONE
        if self._pause_after:
            self._pause_after = False
            self.state = RunState.PAUSED
            return Effect.NONE
        return self._begin_next()

    def set_direct_downloader(self, value: bool) -> None:
        """Takes effect from the next package: the running one started under the old setting."""
        self._next_direct = value

    def controls(self) -> Controls:
        if self.state is RunState.FINISHED or self.state is RunState.IDLE:
            return Controls("Pause", False, ())
        if self.state is RunState.PAUSED:
            choices = (STOP_PLAIN,) if self.active is None else (STOP_AFTER, STOP_NOW)
            return Controls("Resume", True, choices)
        stop = (STOP_AFTER, STOP_NOW) if self.stage is Stage.DOWNLOADING else (STOP_AFTER, FORCE_STOP)
        if self._pause_after:
            if self.stage is Stage.INSTALLING:
                label = "Pausing after this install…"
            else:
                label = "Pausing after this package…"
            return Controls(label, False, stop)
        if self._can_freeze():
            return Controls("Pause", True, stop)
        if self.stage is Stage.INSTALLING:
            return Controls("Pause after this install", True, stop)
        return Controls("Pause after this package", True, stop)

    def _movable(self, item: RunItem) -> bool:
        return item.state is ItemState.WAITING and item.package.id not in RUG_PULL_IDS

    def move(self, package_id: str, delta: int) -> bool:
        index = next((n for n, i in enumerate(self.items) if i.package.id == package_id), None)
        if index is None or not self._movable(self.items[index]):
            return False
        target = index + delta
        if not 0 <= target < len(self.items) or not self._movable(self.items[target]):
            return False
        self.items[index], self.items[target] = self.items[target], self.items[index]
        return True

    def remove(self, package_id: str) -> bool:
        for item in self.items:
            if item.package.id == package_id and item.state is ItemState.WAITING:
                self.items.remove(item)
                return True
        return False

    def retry_failed(self) -> RunQueue:
        return RunQueue([i.package for i in self.items if i.state is ItemState.FAILED], self._next_direct)

    def summary(self) -> Summary:
        def count(*states: ItemState) -> int:
            return sum(1 for i in self.items if i.state in states)

        return Summary(
            done=count(ItemState.DONE, ItemState.DONE_RESTART),
            restart_needed=count(ItemState.DONE_RESTART),
            skipped=count(ItemState.SKIPPED),
            failed=count(ItemState.FAILED),
            stopped=count(ItemState.STOPPED),
        )

    def snapshot(self) -> QueueSnapshot:
        """What is left to do. An interrupted package goes back to waiting and starts again."""
        left = [i for i in self.items if i.state in (ItemState.WAITING, ItemState.ACTIVE)]
        return QueueSnapshot(
            items=[
                QueueItem(i.package.name, i.package.id, i.package.installed, i.package.available,
                          i.package.source, ItemState.WAITING.value)
                for i in left
            ],
            direct_downloader=self._next_direct,
        )

    @classmethod
    def restore(cls, snapshot: QueueSnapshot) -> RunQueue:
        packages = [
            Package(i.name, i.id, i.installed, i.available, i.source, ChangeKind.UNKNOWN)
            for i in snapshot.items
        ]
        return cls(packages, snapshot.direct_downloader)
