"""Runs a queue against a backend: the rules are in RunQueue, the doing is here. The screens only
read `view` and call the control methods."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

from ..i18n import N_, t
from ..winget.backend import (
    FinishedEvent,
    OutputEvent,
    ProgressEvent,
    StageEvent,
    UpgradeHandle,
    UpgradeOptions,
    WingetBackend,
)
from ..winget.codes import Outcome, explain
from ..winget.models import Package, Progress, Stage
from ..winget.proc import KillResult
from .logs import SessionLog
from .queue import Controls, Effect, ItemState, RunItem, RunQueue, RunState, Summary
from .store import HistoryEntry, Store

_LOST_EXIT = 1
_SPEED_SAMPLES = 8
_SHUTDOWN_WAIT_SECONDS = 5
_OUTPUT_KEPT = 300
_FAILURES = {Outcome.FAILED, Outcome.FAILED_IN_USE, Outcome.FAILED_RESTART_FIRST}
_DENIED_MESSAGE = N_(
    "Windows would not let this app stop the installer, because it is running as administrator. "
    "It will carry on until it finishes."
)


@dataclass(frozen=True)
class RunView:
    state: RunState = RunState.IDLE
    items: tuple[RunItem, ...] = ()
    active_name: str | None = None
    stage: Stage | None = None
    progress: Progress | None = None
    speed_mb_s: float | None = None
    elapsed_s: float = 0.0
    stalled: bool = False
    controls: Controls = Controls("Pause", False, ())
    last_error: str | None = None
    summary: Summary | None = None
    output: tuple[tuple[str, str], ...] = ()
    output_total: int = 0
    direct_downloader: bool = False


class Runner:
    def __init__(
        self,
        backend: WingetBackend,
        store: Store,
        log: SessionLog,
        on_change: Callable[[RunView], None],
        stall_minutes: float = 10,
        tick_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._backend = backend
        self._store = store
        self._log = log
        self.on_change = on_change
        self._stall_seconds = stall_minutes * 60
        self._tick = tick_seconds
        self._clock = clock
        self._queue: RunQueue | None = None
        self._options_for: Callable[[Package], UpgradeOptions] | None = None
        self._starter: Callable[[Package, UpgradeOptions], UpgradeHandle] = backend.start_upgrade
        self._handle: UpgradeHandle | None = None
        self._driver: asyncio.Task | None = None
        self._ticker: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._progress: Progress | None = None
        self._samples: deque[tuple[float, float]] = deque(maxlen=_SPEED_SAMPLES)
        self._started_at = 0.0
        self._finished_at: float | None = None
        self._last_activity = 0.0
        self._stalled = False
        self._last_error: str | None = None
        self._was_frozen = False
        self._retried = False
        self._kill_sent = False
        self._closing = False
        self._output: deque[tuple[str, str]] = deque(maxlen=_OUTPUT_KEPT)
        self._output_total = 0

    # What the screens read

    @property
    def view(self) -> RunView:
        q = self._queue
        if q is None:
            return RunView(progress=self._progress, speed_mb_s=self._speed(), stalled=self._stalled,
                           last_error=self._last_error)
        frozen = q.state is RunState.PAUSED
        return RunView(
            state=q.state,
            items=tuple(replace(i) for i in q.items),
            active_name=q.active.package.name if q.active else None,
            stage=q.stage,
            progress=self._progress,
            speed_mb_s=None if frozen else self._speed(),
            elapsed_s=(self._finished_at or self._clock()) - self._started_at,
            stalled=self._stalled,
            controls=q.controls(),
            last_error=self._last_error,
            summary=q.summary(),
            output=tuple(self._output),
            output_total=self._output_total,
            direct_downloader=q.direct_downloader,
        )

    def _line(self, text: str) -> None:
        self._output.append((datetime.now().strftime("%H:%M:%S"), text))
        self._output_total += 1

    def _speed(self) -> float | None:
        """Measured from the megabytes winget reports. No numbers means no speed, never a guess."""
        if len(self._samples) < 2:
            return None
        (t0, mb0), (t1, mb1) = self._samples[0], self._samples[-1]
        return (mb1 - mb0) / (t1 - t0) if t1 > t0 else None

    def _notify(self) -> None:
        try:
            self.on_change(self.view)
        except Exception as e:  # a bug in a screen must never stop an upgrade run
            self._log.error("Screen update failed", error=repr(e))

    def _save(self) -> None:
        if self._closing or self._queue is None:
            return
        try:
            if self._queue.state is RunState.FINISHED:
                self._store.clear_queue()
            else:
                self._store.save_queue(self._queue.snapshot())
        except OSError as e:
            self._last_error = t("Could not save the queue: {error}", error=e)
            self._log.error("Could not save the queue", error=repr(e))

    def _changed(self) -> None:
        self._save()
        self._notify()

    # Starting and driving

    async def start(
        self,
        packages: list[Package],
        options_for: Callable[[Package], UpgradeOptions],
        starter: Callable[[Package, UpgradeOptions], UpgradeHandle] | None = None,
    ) -> None:
        """`starter` runs something other than an upgrade for each package, such as a roll back."""
        if self._driver is not None and not self._driver.done():
            raise RuntimeError("A run is already in progress")
        caps = self._backend.capabilities()
        self._queue = RunQueue(packages, direct_downloader=bool(caps and caps.direct_downloader))
        self._options_for = options_for
        self._starter = starter or self._backend.start_upgrade
        self._started_at = self._clock()
        self._finished_at = None
        self._last_error = None
        self._closing = False
        self._log.info("Run started", packages=[p.id for p in packages])
        self._queue.start()
        self._changed()
        self._driver = asyncio.create_task(self._drive())
        self._ticker = asyncio.create_task(self._watch())

    async def wait(self) -> None:
        if self._driver is not None:
            await self._driver

    async def _drive(self) -> None:
        q = self._queue
        try:
            while q.state is not RunState.FINISHED and not self._closing:
                if q.active is None:
                    self._wake.clear()
                    await self._wake.wait()
                    continue
                await self._run_active(q.active)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self._last_error = t("The run stopped unexpectedly: {error}", error=e)
            self._log.error("Run stopped unexpectedly", error=repr(e))
            self._notify()
        else:
            self._log.info("Run finished", summary=repr(q.summary()))
        finally:
            if self._ticker is not None:
                self._ticker.cancel()

    def _reset_for_package(self) -> None:
        self._handle = None
        self._progress = None
        self._samples.clear()
        self._stalled = False
        self._kill_sent = False
        self._last_activity = self._clock()

    async def _run_active(self, item: RunItem) -> None:
        self._reset_for_package()
        self._was_frozen = False
        self._retried = False
        self._line(t("Upgrading {name}", name=item.package.name))
        while True:
            code = await self._one_attempt(item)
            if self._closing:
                return
            if self._should_retry(code):
                self._retried = True
                self._log.warn("Download failed after a pause, retrying once", package=item.package.id,
                               code=explain(code).hex_code)
                self._reset_for_package()
                self._queue.restart_active()
                self._line(t("{name}: the download failed after the pause, trying once more", name=item.package.name))
                self._notify()
                continue
            break
        self._finish_item(item, code)

    def _should_retry(self, code: int) -> bool:
        return (
            self._was_frozen
            and not self._retried
            and not self._kill_sent
            and explain(code).outcome in _FAILURES
        )

    async def _one_attempt(self, item: RunItem) -> int:
        try:
            self._handle = self._starter(item.package, self._options_for(item.package))
        except Exception as e:  # pywinpty raises its own error types
            self._log.error("Could not start winget", package=item.package.id, error=repr(e))
            item.message = t("Could not start winget: {error}", error=e)
            return _LOST_EXIT
        self._notify()
        code = _LOST_EXIT
        try:
            async for event in self._handle.events():
                if isinstance(event, ProgressEvent):
                    self._on_progress(event.progress)
                elif isinstance(event, StageEvent):
                    self._on_activity()
                    self._queue.on_stage(event.stage)
                    if event.stage is not Stage.DOWNLOADING:
                        self._samples.clear()
                    self._notify()
                elif isinstance(event, OutputEvent):
                    self._on_activity()
                    self._line(event.line)
                    self._notify()
                elif isinstance(event, FinishedEvent):
                    code = event.exit_code
        except Exception as e:  # without an answer from winget the run must still move on
            self._log.error("Lost contact with winget", package=item.package.id, error=repr(e))
            item.message = t("Lost contact with winget: {error}", error=e)
            try:
                self._handle.kill()
            except Exception as kill_error:
                self._log.error("Could not stop winget", package=item.package.id, error=repr(kill_error))
            return _LOST_EXIT
        return code

    def _on_activity(self) -> None:
        self._last_activity = self._clock()
        if self._stalled:
            self._stalled = False
            self._log.info("Output resumed")

    def _on_progress(self, progress: Progress) -> None:
        self._on_activity()
        self._progress = progress
        mb = progress.received_mb
        if mb is None:
            self._samples.clear()
        else:
            if self._samples and mb < self._samples[-1][1]:
                self._samples.clear()  # a new bar started, such as a second download
            self._samples.append((self._clock(), mb))
        self._notify()

    def _finish_item(self, item: RunItem, code: int) -> None:
        start_error = item.message
        self._handle = None
        q = self._queue
        q.on_finished(code)
        if q.state is RunState.FINISHED:
            self._finished_at = self._clock()
        elif q.state is RunState.PAUSED:
            self._log.info("Paused before the next package")
        if start_error and item.state is ItemState.FAILED:
            item.message = start_error
        self._progress = None
        self._samples.clear()
        self._stalled = False
        self._history(item)
        said = t(item.message) if item.message else item.state.value
        ok = item.state is ItemState.DONE
        self._line(f"{item.package.name}: {said}" if ok else f"{item.package.name}: {said} ({item.code})")
        self._changed()

    def _history(self, item: RunItem) -> None:
        transcript = self._log.transcript_for(item.package.id)
        entry = HistoryEntry(
            when=datetime.now().isoformat(timespec="seconds"),
            id=item.package.id,
            name=item.package.name,
            from_version=item.package.installed,
            to_version=item.package.available,
            outcome=item.state.value,
            code=item.code,
            log_path=str(transcript) if transcript else "",
        )
        try:
            self._store.append_history(entry)
        except OSError as e:
            self._log.error("Could not write history", error=repr(e))

    async def _watch(self) -> None:
        """Keeps elapsed time moving and warns about silence. It never stops anything by itself:
        a quiet installer may simply be slow."""
        while True:
            await asyncio.sleep(self._tick)
            q = self._queue
            if q.active is not None and q.state is RunState.RUNNING and not self._stalled:
                quiet = self._clock() - self._last_activity
                if quiet >= self._stall_seconds:
                    self._stalled = True
                    self._log.warn("No output from winget for a while", package=q.active.package.id,
                                   seconds=round(quiet))
            self._notify()

    # The controls

    def pause(self) -> None:
        if self._queue is None:
            return
        effect = self._queue.pause()
        if effect is Effect.FREEZE:
            frozen = False
            try:
                frozen = self._handle is not None and self._handle.freeze()
            except OSError as e:
                self._log.warn("Freeze failed", error=repr(e))
            if frozen:
                self._was_frozen = True
                self._samples.clear()
            else:
                self._queue.freeze_refused()
        now = self._queue.state is RunState.PAUSED
        self._log.info("Pause pressed", state=self._queue.state.value, applies="now" if now else "after this package")
        self._changed()

    def resume(self) -> None:
        if self._queue is None:
            return
        effect = self._queue.resume()
        if effect is Effect.THAW:
            self._thaw()
        elif effect is Effect.START_NEXT:
            self._wake.set()
        self._log.info("Resume pressed", effect=effect.value)
        self._changed()

    def move_item(self, package_id: str, delta: int) -> bool:
        moved = self._queue is not None and self._queue.move(package_id, delta)
        if moved:
            self._changed()
        return moved

    def remove_item(self, package_id: str) -> bool:
        removed = self._queue is not None and self._queue.remove(package_id)
        if removed:
            self._changed()
        return removed

    def set_direct_downloader(self, value: bool) -> None:
        if self._queue is not None:
            self._queue.set_direct_downloader(value)

    def _thaw(self) -> None:
        self._last_activity = self._clock()
        if self._handle is not None:
            self._handle.thaw()

    def stop_after(self) -> None:
        if self._queue is None:
            return
        if self._queue.stop_after() is Effect.THAW:
            self._thaw()
        self._wake.set()
        self._log.info("Stop after this one pressed")
        self._changed()

    def _kill(self, effect: Effect) -> KillResult | None:
        if effect not in (Effect.KILL, Effect.THAW_AND_KILL) or self._handle is None:
            return None
        if effect is Effect.THAW_AND_KILL:
            self._handle.thaw()
        self._kill_sent = True
        result = self._handle.kill()
        if result.access_denied or not result.killed:
            self._kill_sent = False
            self._queue.kill_refused()
            self._last_error = t(_DENIED_MESSAGE)
            self._log.warn("Windows refused to stop the process", denied=result.access_denied)
        self._changed()
        return result

    def stop_now(self) -> KillResult | None:
        if self._queue is None:
            return None
        self._log.info("Stop now pressed")
        if self._queue.active is not None and self._handle is not None and self._handle.installer_running():
            # Stop now is only for a download. The stage came from reading winget's words, so check what is really running.
            self._log.warn("Stop now refused, an installer is running", package=self._queue.active.package.id)
            self._queue.on_stage(Stage.INSTALLING)
            self._changed()
            return None
        return self._kill(self._queue.stop_now())

    def force_stop(self) -> KillResult | None:
        if self._queue is None:
            return None
        self._log.warn("Force stop pressed")
        return self._kill(self._queue.force_stop())

    def set_stall_minutes(self, minutes: float) -> None:
        self._stall_seconds = minutes * 60

    def emergency_stop(self) -> bool:
        """The console is closing and Windows is about to end this process, so no event loop can be
        relied on. A frozen winget would otherwise stay suspended for ever. Returns True when a
        process was told to stop and may still be finishing."""
        q = self._queue
        if q is None or self._closing or self._driver is None or self._driver.done():
            return False
        try:
            self._store.save_queue(q.snapshot())
        except OSError as e:
            self._log.error("Could not save the queue while closing", error=repr(e))
        self._closing = True
        if q.active is None or self._handle is None:
            return False
        frozen = q.state is RunState.PAUSED
        if not frozen and q.stage is not Stage.DOWNLOADING:
            self._log.warn("Closed while installing: winget ends with this app, the installer may carry on by itself",
                           package=q.active.package.id)
            return False
        if frozen:
            self._handle.thaw()
        result = self._handle.kill()
        self._log.warn("Closed during a download, winget stopped", package=q.active.package.id,
                       killed=result.killed)
        return result.killed

    async def shutdown(self) -> None:
        """The window is closing. Nothing may stay frozen, an installer is not killed on purpose, and what
        was not finished is saved so it can be resumed next time."""
        if self._queue is None or self._driver is None or self._driver.done():
            return
        if self.emergency_stop():
            await asyncio.wait({self._driver}, timeout=_SHUTDOWN_WAIT_SECONDS)
        self._wake.set()
        for task in (self._driver, self._ticker):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(self._driver, self._ticker, return_exceptions=True)
