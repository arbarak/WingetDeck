import asyncio

import pytest

from wingetdeck.core.logs import SessionLog
from wingetdeck.core.queue import ItemState, RunState
from wingetdeck.core.runner import Runner
from wingetdeck.core.store import Store
from wingetdeck.winget.backend import (
    FinishedEvent,
    OutputEvent,
    ProgressEvent,
    StageEvent,
    UpgradeOptions,
)
from wingetdeck.winget.fake import FakeBackend
from wingetdeck.winget.models import ChangeKind, Package, Progress, Stage
from wingetdeck.winget.proc import KillResult

IN_USE = 0x8A150101


def pkg(i):
    return Package(i, i, "1.0", "1.1", "winget", ChangeKind.MINOR)


def options(_package):
    return UpgradeOptions()


class Harness:
    def __init__(self, tmp_data, backend, **kw):
        self.backend = backend
        self.log = SessionLog(tmp_data, False, {})
        self.store = Store(tmp_data, self.log)
        self.views = []
        self.runner = Runner(backend, self.store, self.log, self.views.append, **kw)

    async def until(self, check, seconds=5.0):
        async def poll():
            while not check():
                await asyncio.sleep(0.005)

        await asyncio.wait_for(poll(), seconds)

    async def until_stage(self, stage):
        await self.until(lambda: self.runner.view.stage is stage)


@pytest.fixture
def make(tmp_data):
    return lambda backend, **kw: Harness(tmp_data, backend, **kw)


class Recording(FakeBackend):
    """Keeps the handles it creates and the order of calls made on them."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.handles = []
        self.actions = []

    def start_upgrade(self, package, options_):
        handle = super().start_upgrade(package, options_)
        self.handles.append(handle)
        for name in ("freeze", "thaw", "kill"):
            original = getattr(handle, name)

            def wrapped(original=original, name=name):
                self.actions.append(name)
                return original()

            setattr(handle, name, wrapped)
        return handle


class ScriptedHandle:
    pid = 0

    def __init__(self, events, kill_result=KillResult(True)):
        self._events = events
        self._kill_result = kill_result
        self.release = asyncio.Event()

    def freeze(self):
        return True

    def thaw(self):
        pass

    def kill(self):
        self.release.set()
        return self._kill_result

    async def events(self):
        for event in self._events:
            if event == "wait":
                await self.release.wait()
            elif isinstance(event, tuple):
                await asyncio.sleep(event[0])
            else:
                yield event


class Scripted(FakeBackend):
    def __init__(self, handles):
        super().__init__([])
        self.handles = list(handles)

    def start_upgrade(self, package, options_):
        return self.handles.pop(0)


async def test_runs_queue_in_order_and_writes_history(make):
    h = make(FakeBackend([], speed=200, script={"B": IN_USE}))
    await h.runner.start([pkg("A"), pkg("B"), pkg("C")], options)
    await h.runner.wait()
    assert h.backend.calls == ["upgrade:A", "upgrade:B", "upgrade:C"]
    assert h.runner.view.state is RunState.FINISHED
    rows = h.store.history()
    assert [(r.id, r.outcome) for r in rows] == [("A", "done"), ("B", "failed"), ("C", "done")]
    assert rows[1].code == "0x8A150101" and (rows[0].from_version, rows[0].to_version) == ("1.0", "1.1")


async def test_history_points_to_the_package_transcript(tmp_data):
    from wingetdeck.winget.real import RealHandle  # the transcript belongs to the real handle
    import sys

    log = SessionLog(tmp_data, False, {})
    store = Store(tmp_data, log)

    class OneReal(FakeBackend):
        def start_upgrade(self, package, options_):
            return RealHandle(log, package.id, [sys.executable, "-c", "print('hello')"], use_pty=False)

    runner = Runner(OneReal([]), store, log, lambda view: None)
    await runner.start([pkg("A")], options)
    await runner.wait()
    entry = store.history()[0]
    assert entry.outcome == "done" and entry.log_path.endswith("_A.log")
    with open(entry.log_path, encoding="utf-8") as f:
        assert "hello" in f.read()


async def test_queue_saved_after_every_change(make):
    h = make(FakeBackend([], speed=200))
    left = []
    h.runner.on_change = lambda view: left.append(
        None if (s := h.store.load_queue()) is None else [i.id for i in s.items]
    )
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.runner.wait()
    assert left[0] == ["A", "B"], "saved before the first package starts"
    assert ["B"] in left
    assert h.store.load_queue() is None, "nothing left to resume after a finished run"


async def test_freeze_called_on_real_handle_when_paused(make):
    h = make(Recording([], speed=5))
    await h.runner.start([pkg("A")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.pause()
    assert h.backend.actions == ["freeze"] and h.runner.view.state is RunState.PAUSED
    assert h.runner.view.speed_mb_s is None, "a frozen download has no speed"
    h.runner.resume()
    assert h.backend.actions == ["freeze", "thaw"] and h.runner.view.state is RunState.RUNNING
    await h.runner.shutdown()


async def test_pause_refused_by_handle_waits_for_the_package(make):
    backend = Recording([], speed=50)
    backend.refuse_freeze = True
    h = make(backend)
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.pause()
    assert h.runner.view.state is RunState.RUNNING
    assert h.runner.view.controls.pause_label == "Pausing after this package…"
    await h.until(lambda: h.runner.view.state is RunState.PAUSED)
    assert h.backend.calls == ["upgrade:A"], "B must not start while paused"
    await h.runner.shutdown()


async def test_no_freeze_without_direct_downloader(make):
    h = make(Recording([], speed=5, direct_downloader=False))
    await h.runner.start([pkg("A")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.pause()
    assert h.backend.actions == []
    await h.runner.shutdown()


async def test_resume_between_packages_starts_the_next(make):
    h = make(Recording([], speed=100))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.until_stage(Stage.INSTALLING)
    h.runner.pause()
    await h.until(lambda: h.runner.view.state is RunState.PAUSED)
    h.runner.resume()
    await h.runner.wait()
    assert h.backend.calls == ["upgrade:A", "upgrade:B"] and h.runner.view.state is RunState.FINISHED


async def test_stop_between_packages_ends_the_run(make):
    h = make(FakeBackend([], speed=100))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.until_stage(Stage.INSTALLING)
    h.runner.pause()
    await h.until(lambda: h.runner.view.state is RunState.PAUSED)
    h.runner.stop_after()
    await h.runner.wait()
    assert h.backend.calls == ["upgrade:A"]
    assert [i.state for i in h.runner.view.items] == [ItemState.DONE, ItemState.STOPPED]


async def test_speed_comes_from_received_numbers_never_invented(make):
    handle = ScriptedHandle([
        StageEvent(Stage.DOWNLOADING),
        ProgressEvent(Progress(10.0, None, None)),
        (0.02,),
        ProgressEvent(Progress(20.0, None, None)),
        "wait",
        FinishedEvent(0),
    ])
    h = make(Scripted([handle]))
    await h.runner.start([pkg("A")], options)
    await h.until(lambda: h.runner.view.progress and h.runner.view.progress.percent == 20.0)
    assert h.runner.view.speed_mb_s is None
    handle.release.set()
    await h.runner.wait()


async def test_speed_is_measured_from_megabytes(make):
    clock = {"now": 100.0}
    handle = ScriptedHandle([
        StageEvent(Stage.DOWNLOADING),
        ProgressEvent(Progress(10.0, 10.0, 100.0)),
        "wait",
        FinishedEvent(0),
    ])
    h = make(Scripted([handle]), clock=lambda: clock["now"])
    await h.runner.start([pkg("A")], options)
    await h.until(lambda: h.runner.view.progress is not None)
    assert h.runner.view.speed_mb_s is None, "one sample gives no speed"
    clock["now"] = 102.0
    h.runner._on_progress(Progress(30.0, 30.0, 100.0))
    assert h.runner.view.speed_mb_s == pytest.approx(10.0)
    handle.release.set()
    await h.runner.wait()


async def test_speed_restarts_when_a_new_bar_starts(make):
    clock = {"now": 0.0}
    h = make(Scripted([]), clock=lambda: clock["now"])
    h.runner._on_progress(Progress(90.0, 90.0, 100.0))
    clock["now"] = 1.0
    h.runner._on_progress(Progress(1.0, 1.0, 100.0))
    assert h.runner.view.speed_mb_s is None


async def test_stall_warning_only_never_kills(make):
    h = make(Recording([], speed=0.05), stall_minutes=0.0005, tick_seconds=0.005)
    await h.runner.start([pkg("A")], options)
    await h.until(lambda: h.runner.view.stalled)
    assert "kill" not in h.backend.actions and h.runner.view.state is RunState.RUNNING
    assert any("No output" in e.message for e in h.log.events())
    h.runner._on_progress(Progress(1.0, 1.0, 10.0))
    assert not h.runner.view.stalled, "new activity clears the warning"
    await h.runner.shutdown()


async def test_paused_download_is_not_reported_as_stalled(make):
    h = make(Recording([], speed=5), stall_minutes=0.0005, tick_seconds=0.005)
    await h.runner.start([pkg("A")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.pause()
    await asyncio.sleep(0.08)
    assert not h.runner.view.stalled
    await h.runner.shutdown()


async def test_stop_now_kills_and_the_run_finishes(make):
    h = make(Recording([], speed=5))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.until_stage(Stage.DOWNLOADING)
    result = h.runner.stop_now()
    assert result.killed
    await h.runner.wait()
    assert [i.state for i in h.runner.view.items] == [ItemState.STOPPED, ItemState.STOPPED]
    assert h.backend.calls == ["upgrade:A"]


async def test_access_denied_kill_is_reported(make):
    handle = ScriptedHandle(
        [StageEvent(Stage.INSTALLING), "wait", FinishedEvent(0)],
        kill_result=KillResult(False, access_denied=True),
    )
    h = make(Scripted([handle]))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.until_stage(Stage.INSTALLING)
    result = h.runner.force_stop()
    assert result.access_denied
    assert "administrator" in h.runner.view.last_error.lower()
    await h.runner.wait()
    item = h.runner.view.items[0]
    assert item.state is ItemState.DONE, "the installer went on and finished, so report what happened"
    assert h.runner.view.items[1].state is ItemState.STOPPED


async def test_shutdown_while_frozen_thaws_then_kills_and_saves_queue(make):
    h = make(Recording([], speed=5))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.pause()
    await h.runner.shutdown()
    assert h.backend.actions == ["freeze", "thaw", "kill"]
    assert [i.id for i in h.store.load_queue().items] == ["A", "B"]
    assert h.store.history() == [], "an interrupted package is not a result"


async def test_shutdown_while_downloading_kills_and_saves_queue(make):
    h = make(Recording([], speed=5))
    await h.runner.start([pkg("A")], options)
    await h.until_stage(Stage.DOWNLOADING)
    await h.runner.shutdown()
    assert h.backend.actions == ["kill"]
    assert [i.id for i in h.store.load_queue().items] == ["A"]


async def test_shutdown_while_installing_does_not_kill_and_logs_warning(make):
    h = make(Recording([], speed=20))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.until_stage(Stage.INSTALLING)
    await h.runner.shutdown()
    assert "kill" not in h.backend.actions
    assert any("installer" in e.message.lower() for e in h.log.events("WARN"))
    assert [i.id for i in h.store.load_queue().items] == ["A", "B"]


async def test_shutdown_before_any_run_is_harmless(make):
    h = make(FakeBackend([]))
    await h.runner.shutdown()


async def test_frozen_download_fails_after_resume_retries_once(make):
    h = make(Recording([], speed=5, script={"A": [1, 0]}))
    await h.runner.start([pkg("A")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.pause()
    h.runner.resume()
    h.backend.handles[0]._backend.speed = 500
    await h.until(lambda: len(h.backend.handles) == 2)
    h.backend.handles[1]._backend.speed = 500
    await h.runner.wait()
    assert h.backend.calls == ["upgrade:A", "upgrade:A"]
    assert h.runner.view.items[0].state is ItemState.DONE
    assert any("retry" in e.message.lower() for e in h.log.events())


async def test_retry_happens_only_once(make):
    h = make(Recording([], speed=500, script={"A": [1, 1]}))
    await h.runner.start([pkg("A")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.pause()
    h.runner.resume()
    await h.until(lambda: len(h.backend.handles) == 2)
    await h.runner.wait()
    assert h.backend.calls == ["upgrade:A", "upgrade:A"]
    assert h.runner.view.items[0].state is ItemState.FAILED


async def test_no_retry_when_never_frozen(make):
    h = make(FakeBackend([], speed=200, script={"A": 1}))
    await h.runner.start([pkg("A")], options)
    await h.runner.wait()
    assert h.backend.calls == ["upgrade:A"]


async def test_no_retry_after_stop_now_on_frozen_download(make):
    h = make(Recording([], speed=5, script={"A": 1}))
    await h.runner.start([pkg("A")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.pause()
    h.runner.stop_now()
    await h.runner.wait()
    assert h.backend.calls == ["upgrade:A"]
    assert h.backend.actions == ["freeze", "thaw", "kill"]


async def test_start_failure_marks_item_failed_and_continues(make):
    class Broken(FakeBackend):
        def start_upgrade(self, package, options_):
            if package.id == "A":
                raise OSError("no pseudo console")
            return super().start_upgrade(package, options_)

    h = make(Broken([], speed=200))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.runner.wait()
    a, b = h.runner.view.items
    assert a.state is ItemState.FAILED and "no pseudo console" in a.message and b.state is ItemState.DONE


async def test_stream_ending_without_finish_counts_as_failed(make):
    h = make(Scripted([ScriptedHandle([StageEvent(Stage.DOWNLOADING), OutputEvent("x")])]))
    await h.runner.start([pkg("A")], options)
    await h.runner.wait()
    assert h.runner.view.items[0].state is ItemState.FAILED


async def test_a_broken_screen_callback_does_not_stop_the_run(make):
    h = make(FakeBackend([], speed=200))

    def explode(view):
        raise ValueError("screen bug")

    h.runner.on_change = explode
    await h.runner.start([pkg("A")], options)
    await h.runner.wait()
    assert h.store.history()[0].outcome == "done"
    assert any("screen bug" in str(e.fields) for e in h.log.events("ERROR"))


async def test_view_names_the_active_package(make):
    h = make(FakeBackend([], speed=5))
    await h.runner.start([pkg("Git.Git")], options)
    await h.until_stage(Stage.DOWNLOADING)
    assert h.runner.view.active_name == "Git.Git"
    await h.runner.shutdown()


async def test_second_start_during_a_run_is_refused(make):
    h = make(FakeBackend([], speed=5))
    await h.runner.start([pkg("A")], options)
    with pytest.raises(RuntimeError):
        await h.runner.start([pkg("B")], options)
    await h.runner.shutdown()


async def test_direct_downloader_read_from_capabilities(make):
    h = make(FakeBackend([], speed=5, direct_downloader=False))
    await h.runner.start([pkg("A")], options)
    await h.until_stage(Stage.DOWNLOADING)
    assert h.runner.view.controls.pause_label == "Pause after this package"
    await h.runner.shutdown()


async def test_elapsed_stops_when_the_run_finishes(make):
    clock = {"now": 10.0}
    h = make(FakeBackend([], speed=200), clock=lambda: clock["now"])
    await h.runner.start([pkg("A")], options)
    clock["now"] = 13.0
    await h.runner.wait()
    clock["now"] = 500.0
    assert h.runner.view.elapsed_s == 3.0


async def test_emergency_stop_when_console_closes_thaws_kills_and_saves(make):
    h = make(Recording([], speed=5))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.pause()
    h.runner.emergency_stop()
    assert h.backend.actions == ["freeze", "thaw", "kill"]
    assert [i.id for i in h.store.load_queue().items] == ["A", "B"]
    await h.runner.shutdown()
    assert h.backend.actions == ["freeze", "thaw", "kill"], "only once"


async def test_emergency_stop_leaves_an_installer_alone(make):
    h = make(Recording([], speed=20))
    await h.runner.start([pkg("A")], options)
    await h.until_stage(Stage.INSTALLING)
    h.runner.emergency_stop()
    assert h.backend.actions == []
    await h.runner.shutdown()


def test_emergency_stop_with_no_run_is_harmless(make):
    make(FakeBackend([])).runner.emergency_stop()


async def test_view_carries_recent_output_and_a_running_total(make):
    h = make(FakeBackend([], speed=200))
    await h.runner.start([pkg("A")], options)
    await h.runner.wait()
    view = h.runner.view
    assert view.output_total == len(view.output) and any("Successfully installed" in line for _, line in view.output)


async def test_output_says_what_happened_to_each_package(make):
    h = make(FakeBackend([], speed=200, script={"A": IN_USE}))
    await h.runner.start([pkg("A")], options)
    await h.runner.wait()
    assert any("0x8A150101" in line for _, line in h.runner.view.output)


async def test_move_and_remove_go_through_the_queue(make):
    h = make(FakeBackend([], speed=5))
    await h.runner.start([pkg("A"), pkg("B"), pkg("C")], options)
    assert h.runner.move_item("C", -1)
    assert [i.package.id for i in h.runner.view.items] == ["A", "C", "B"]
    assert [i.id for i in h.store.load_queue().items] == ["A", "C", "B"], "saved"
    assert h.runner.remove_item("B") and not h.runner.remove_item("A")
    assert [i.id for i in h.store.load_queue().items] == ["A", "C"]
    await h.runner.shutdown()


async def test_summary_in_view_when_finished(make):
    h = make(FakeBackend([], speed=200, script={"B": IN_USE}))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.runner.wait()
    assert (h.runner.view.summary.done, h.runner.view.summary.failed) == (1, 1)


async def test_turning_on_direct_downloader_applies_from_the_next_package(make):
    h = make(Recording([], speed=8, direct_downloader=False))
    await h.runner.start([pkg("A"), pkg("B")], options)
    await h.until_stage(Stage.DOWNLOADING)
    h.runner.set_direct_downloader(True)
    assert not h.runner.view.direct_downloader
    h.runner.pause()
    assert h.backend.actions == []
    await h.runner.shutdown()
