import asyncio

from wingetdeck.winget.backend import (
    FinishedEvent,
    ProgressEvent,
    StageEvent,
    UpgradeOptions,
)
from wingetdeck.winget.fake import FakeBackend
from wingetdeck.winget.models import ChangeKind, Package, Stage


def pkg(i="Git.Git"):
    return Package("Git", i, "1.0", "1.1", "winget", ChangeKind.MINOR)


async def collect(handle):
    return [e async for e in handle.events()]


async def test_scan_returns_given_packages():
    b = FakeBackend([pkg()])
    assert (await b.scan(None)).packages == [pkg()]


async def test_scan_filters_by_source():
    b = FakeBackend([pkg()])
    assert (await b.scan("msstore")).packages == []


async def test_upgrade_emits_stages_in_order_and_finishes():
    events = await collect(FakeBackend([pkg()], speed=500).start_upgrade(pkg(), UpgradeOptions()))
    stages = [e.stage for e in events if isinstance(e, StageEvent)]
    assert stages == [Stage.DOWNLOADING, Stage.VERIFYING, Stage.INSTALLING]
    assert isinstance(events[-1], FinishedEvent) and events[-1].exit_code == 0
    assert any(isinstance(e, ProgressEvent) for e in events)


async def test_freeze_holds_events_until_thaw():
    h = FakeBackend([pkg()], speed=500).start_upgrade(pkg(), UpgradeOptions())
    seen = []

    async def run():
        async for e in h.events():
            seen.append(e)

    task = asyncio.create_task(run())
    await asyncio.sleep(0.01)
    h.freeze()
    await asyncio.sleep(0.05)
    count = len(seen)
    await asyncio.sleep(0.05)
    assert len(seen) == count and not task.done()
    h.thaw()
    await asyncio.wait_for(task, 5)
    assert isinstance(seen[-1], FinishedEvent)


async def test_scripted_failure_returns_code():
    b = FakeBackend([pkg()], speed=500, script={"Git.Git": 0x8A150101})
    events = await collect(b.start_upgrade(pkg(), UpgradeOptions()))
    assert events[-1].exit_code == 0x8A150101


async def test_scripted_code_list_changes_each_try():
    b = FakeBackend([pkg()], speed=500, script={"Git.Git": [1, 0]})
    assert (await collect(b.start_upgrade(pkg(), UpgradeOptions())))[-1].exit_code == 1
    assert (await collect(b.start_upgrade(pkg(), UpgradeOptions())))[-1].exit_code == 0


async def test_kill_ends_stream():
    h = FakeBackend([pkg()], speed=1).start_upgrade(pkg(), UpgradeOptions())
    task = asyncio.create_task(collect(h))
    await asyncio.sleep(0.01)
    assert h.kill().killed
    events = await asyncio.wait_for(task, 2)
    assert isinstance(events[-1], FinishedEvent) and events[-1].exit_code != 0


async def test_successful_upgrade_removes_package_from_next_scan():
    b = FakeBackend([pkg()], speed=500)
    await collect(b.start_upgrade(pkg(), UpgradeOptions()))
    assert (await b.scan(None)).packages == []


async def test_add_package_shows_in_next_scan():
    b = FakeBackend([])
    b.add_package(pkg())
    assert (await b.scan(None)).packages == [pkg()]
