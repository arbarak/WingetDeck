"""Runs a queue against a backend: the rules are in RunQueue, the doing is here. The screens only
read `view` and call the control methods."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime

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
from .queue import Controls, Effect, ItemState, RunItem, RunQueue, RunState
from .store import HistoryEntry, Store

_LOST_EXIT = 1
_SPEED_SAMPLES = 8
_SHUTDOWN_WAIT_SECONDS = 5
_FAILURES = {Outcome.FAILED, Outcome.FAILED_IN_USE, Outcome.FAILED_RESTART_FIRST}
_DENIED_MESSAGE = (
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
        )

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
            self._last_error = f"Could not save the queue: {e}"
            self._log.error("Could not save the queue", error=repr(e))

    def _changed(self) -> None:
        self._save()
        self._notify()

    # Starting and driving

    async def start(self, packages: list[Package], options_for: Callable[[Package], UpgradeOptions]) -> None:
        if self._driver is not None and not self._driver.done():
            raise RuntimeError("A run is already in progress")
        caps = self._backend.capabilities()
        self._queue = RunQueue(packages, direct_downloader=bool(caps and caps.direct_downloader))
        self._options_for = options_for
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
            self._last_error = f"The run stopped unexpectedly: {e}"
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
            self._handle = self._backend.start_upgrade(item.package, self._options_for(item.package))
        except OSError as e:
            self._log.error("Could not start winget", package=item.package.id, error=repr(e))
            item.message = f"Could not start winget: {e}"
            return _LOST_EXIT
        self._notify()
        code = _LOST_EXIT
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
            elif isinstance(event, FinishedEvent):
                code = event.exit_code
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
        if start_error and item.state is ItemState.FAILED:
            item.message = start_error
        self._progress = None
        self._samples.clear()
        self._stalled = False
        self._history(item)
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
        self._log.info("Pause pressed", state=self._queue.state.value)
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
            self._last_error = _DENIED_MESSAGE
            self._log.warn("Windows refused to stop the process", denied=result.access_denied)
        self._changed()
        return result

    def stop_now(self) -> KillResult | None:
        if self._queue is None:
            return None
        self._log.info("Stop now pressed")
        return self._kill(self._queue.stop_now())

    def force_stop(self) -> KillResult | None:
        if self._queue is None:
            return None
        self._log.warn("Force stop pressed")
        return self._kill(self._queue.force_stop())

    async def shutdown(self) -> None:
        """The window is closing. Nothing may stay frozen, an installer is left to finish, and what
        was not finished is saved so it can be resumed next time."""
        q = self._queue
        if q is None or self._driver is None or self._driver.done():
            return
        try:
            self._store.save_queue(q.snapshot())
        except OSError as e:
            self._log.error("Could not save the queue while closing", error=repr(e))
        self._closing = True
        wait_for_it = False
        if q.active is not None and self._handle is not None:
            frozen = q.state is RunState.PAUSED
            if frozen or q.stage is Stage.DOWNLOADING:
                if frozen:
                    self._handle.thaw()
                result = self._handle.kill()
                wait_for_it = result.killed
                self._log.warn("Closed during a download, winget stopped", package=q.active.package.id,
                               killed=result.killed)
            else:
                self._log.warn("Closed while an installer was running, it was left to finish",
                               package=q.active.package.id)
        self._wake.set()
        if wait_for_it:
            await asyncio.wait({self._driver}, timeout=_SHUTDOWN_WAIT_SECONDS)
        for task in (self._driver, self._ticker):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(self._driver, self._ticker, return_exceptions=True)
